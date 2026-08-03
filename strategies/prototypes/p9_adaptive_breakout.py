"""
P9 — Adaptive Breakout Strategy
================================
Designed using forensic RCA findings to avoid standard ORB weaknesses:
- Excludes range and compressed regimes (ATR percentile >= 50.0).
- Requires H1 + H4 (longer H1 EMA) trend alignment.
- Employs a Breakout-Pullback-Continuation trigger (never enters on the first breakout candle).
- Requires momentum confirmation.
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Optional

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from app.market_data import Bar

logger = logging.getLogger(__name__)


class AdaptiveBreakoutStrategy(BaseStrategy):
    name = "P9_Adaptive_Breakout"
    version = "1.0"

    # Default parameters
    default_sl_atr_mult = 1.5
    default_tp_rr = 2.5

    def __init__(self):
        super().__init__()
        # State tracking
        self._swing_len = 20
        self._m15_highs: Deque[float] = deque(maxlen=self._swing_len)
        self._m15_lows: Deque[float] = deque(maxlen=self._swing_len)
        
        # Breakout-Pullback-Continuation (BPC) state machine
        # States: "NONE", "BULL_BREAKOUT", "BULL_PULLBACK", "BEAR_BREAKOUT", "BEAR_PULLBACK"
        self._bpc_state = "NONE"
        self._breakout_trigger_px = 0.0
        self._breakout_extreme_px = 0.0
        self._state_age = 0
        self._max_state_age = 8  # state expires after 2 hours (8 M15 bars)

    def on_bar(self, ctx: StrategyContext) -> None:
        if not ctx.bars_m15:
            return
        bar = ctx.bars_m15[-1]
        self._m15_highs.append(bar.high)
        self._m15_lows.append(bar.low)
        
        if self._bpc_state != "NONE":
            self._state_age += 1
            if self._state_age > self._max_state_age:
                self._reset_state()

    def _reset_state(self):
        self._bpc_state = "NONE"
        self._breakout_trigger_px = 0.0
        self._breakout_extreme_px = 0.0
        self._state_age = 0

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        # Pre-checks
        if len(self._m15_highs) < self._swing_len:
            return self._flat("Warm-up in progress", ["warmup"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        # ── 1. ATR Percentile Floor (Configurable median check) ───────────────
        vol = ctx.vol_state
        atr_pct = vol.percentile if vol else 50.0
        if atr_pct < 50.0:
            return self._flat(f"Low ATR regime ({atr_pct:.1f} < 50.0)", ["low_atr"])

        # ── 2. Ignore Compression and Explosive Regimes ───────────────────────
        if vol:
            if vol.compression or vol.regime == "COMPRESSED":
                return self._flat("Ignore compression", ["compression"])
            if vol.regime == "EXPLOSIVE":
                return self._flat("Ignore explosive volatility", ["explosive"])

        # ── 3. Higher-Timeframe Trend Alignment (H1 + H4 proxy) ───────────────
        # H1 alignment is ctx.ema_bull (EMA50 > EMA200).
        # We proxy H4 alignment by comparing H1 EMA200 vs H1 EMA800 (or close vs EMA200).
        ema50 = ctx.ema50
        ema200 = ctx.ema200
        if not ema50 or not ema200:
            return self._flat("H1 EMAs not ready", ["ema_h1"])

        h1_bull = ema50 > ema200
        h1_bear = ema50 < ema200

        # Estimate H4 alignment (price vs EMA200 as proxy)
        curr_price = ctx.price
        h4_bull = curr_price > ema200
        h4_bear = curr_price < ema200

        trend_long = h1_bull and h4_bull
        trend_short = h1_bear and h4_bear

        if not trend_long and not trend_short:
            return self._flat("Ranging regime / trend mismatch", ["regime_trend"])

        # ── 4. Breakout-Pullback-Continuation (BPC) Engine ────────────────────
        bars = ctx.bars_m15
        curr = bars[-1]
        
        # Calculate recent swing high/low (excluding the current bar)
        swing_high = max(list(self._m15_highs)[:-1])
        swing_low = min(list(self._m15_lows)[:-1])

        # State machine transition
        if self._bpc_state == "NONE":
            if curr.close > swing_high:
                self._bpc_state = "BULL_BREAKOUT"
                self._breakout_trigger_px = swing_high
                self._breakout_extreme_px = curr.high
                self._state_age = 0
                return self._flat("Bullish breakout detected; waiting for pullback")
            elif curr.close < swing_low:
                self._bpc_state = "BEAR_BREAKOUT"
                self._breakout_trigger_px = swing_low
                self._breakout_extreme_px = curr.low
                self._state_age = 0
                return self._flat("Bearish breakout detected; waiting for pullback")

        elif self._bpc_state == "BULL_BREAKOUT":
            # Track extreme high of breakout phase
            self._breakout_extreme_px = max(self._breakout_extreme_px, curr.high)
            # Pullback condition: Close pulls back below swing high or down towards it
            if curr.close <= self._breakout_trigger_px or curr.close < (self._breakout_extreme_px - ctx.atr * 0.5):
                self._bpc_state = "BULL_PULLBACK"
                return self._flat("Bullish pullback confirmed; waiting for continuation")

        elif self._bpc_state == "BEAR_BREAKOUT":
            self._breakout_extreme_px = min(self._breakout_extreme_px, curr.low)
            if curr.close >= self._breakout_trigger_px or curr.close > (self._breakout_extreme_px + ctx.atr * 0.5):
                self._bpc_state = "BEAR_PULLBACK"
                return self._flat("Bearish pullback confirmed; waiting for continuation")

        elif self._bpc_state == "BULL_PULLBACK":
            # Continuation: Close breaks above the breakout extreme high
            if curr.close > self._breakout_extreme_px:
                # Momentum confirmation check: bullish close
                if curr.close > curr.open and trend_long:
                    self._reset_state()
                    return self._long(
                        confidence=85.0,
                        reason=f"Adaptive Breakout LONG: Close={curr.close:.4f} > Extreme={self._breakout_extreme_px:.4f}",
                        passed=["expansion_confirmed", "htf_alignment", "bpc_trigger", "momentum"]
                    )

        elif self._bpc_state == "BEAR_PULLBACK":
            if curr.close < self._breakout_extreme_px:
                if curr.close < curr.open and trend_short:
                    self._reset_state()
                    return self._short(
                        confidence=85.0,
                        reason=f"Adaptive Breakout SHORT: Close={curr.close:.4f} < Extreme={self._breakout_extreme_px:.4f}",
                        passed=["expansion_confirmed", "htf_alignment", "bpc_trigger", "momentum"]
                    )

        return self._flat("BPC pattern setup in progress", ["bpc_setup"])
