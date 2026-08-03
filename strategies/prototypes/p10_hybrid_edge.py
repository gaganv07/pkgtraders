"""
P10 — Hybrid Edge Strategy
===========================
The first strategy built exclusively from Research Phase 2 statistical evidence.

Key Features:
- Regime switching (Trend vs Mean Reversion)
- EMA 20/50 alignment (r=0.33)
- RSI(14) momentum/extremes (r=0.56)
- VWAP deviation (r=0.37)
- ATR percentile gating (>80th pct strong, <30th avoid)
- Liquidity sweep confirmation
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Optional, Tuple

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class P10HybridEdgeStrategy(BaseStrategy):
    name = "P10_Hybrid_Edge"
    version = "1.0"

    # Default parameters
    default_sl_atr_mult = 1.2
    default_tp_rr = 2.0

    def __init__(self):
        super().__init__()
        # Buffers for liquidity sweep detection
        self._m15_highs: Deque[float] = deque(maxlen=20)
        self._m15_lows: Deque[float] = deque(maxlen=20)
        self._m15_closes: Deque[float] = deque(maxlen=20)
        self._m15_opens: Deque[float] = deque(maxlen=20)

        # Incremental indicators
        self._ema20: Optional[float] = None
        self._ema50: Optional[float] = None
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._rsi14: float = 50.0
        self._last_close: Optional[float] = None
        
        # VWAP
        self._vwap_cum_pv = 0.0
        self._vwap_cum_v = 0.0
        self._vwap_day = None
        self._vwap_val: Optional[float] = None

    def on_bar(self, ctx: StrategyContext) -> None:
        if not ctx.bars_m15:
            return
        bar = ctx.bars_m15[-1]
        
        self._m15_highs.append(bar.high)
        self._m15_lows.append(bar.low)
        self._m15_closes.append(bar.close)
        self._m15_opens.append(bar.open)

        c = bar.close
        # 1. Update EMAs
        if self._ema20 is None:
            self._ema20 = c
        else:
            k20 = 2.0 / (20 + 1)
            self._ema20 = (c - self._ema20) * k20 + self._ema20

        if self._ema50 is None:
            self._ema50 = c
        else:
            k50 = 2.0 / (50 + 1)
            self._ema50 = (c - self._ema50) * k50 + self._ema50

        # 2. Update RSI(14)
        if self._last_close is not None:
            change = c - self._last_close
            gain = change if change > 0 else 0.0
            loss = -change if change < 0 else 0.0
            
            # Smoothed moving average for RSI
            self._avg_gain = (self._avg_gain * 13 + gain) / 14
            self._avg_loss = (self._avg_loss * 13 + loss) / 14
            
            if self._avg_loss == 0:
                self._rsi14 = 100.0 if self._avg_gain > 0 else 50.0
            else:
                rs = self._avg_gain / self._avg_loss
                self._rsi14 = 100.0 - (100.0 / (1.0 + rs))
        # 3. Update VWAP
        day = bar.time.strftime("%Y-%m-%d") if bar.time else ctx.timestamp.strftime("%Y-%m-%d")
        if self._vwap_day != day:
            self._vwap_cum_pv = 0.0
            self._vwap_cum_v = 0.0
            self._vwap_day = day
            
        tp = (bar.high + bar.low + c) / 3.0
        v = max(getattr(bar, 'tick_vol', 1), 1)
        self._vwap_cum_pv += tp * v
        self._vwap_cum_v += v
        self._vwap_val = self._vwap_cum_pv / self._vwap_cum_v
                
        self._last_close = c

    def _check_liquidity_sweep(self) -> Tuple[bool, bool]:
        """
        Check if a liquidity sweep occurred recently.
        Returns: (bull_sweep, bear_sweep)
        Bull sweep: Wick below prior local low, closes back above it.
        Bear sweep: Wick above prior local high, closes back below it.
        """
        if len(self._m15_highs) < 10:
            return False, False
            
        highs = list(self._m15_highs)
        lows = list(self._m15_lows)
        closes = list(self._m15_closes)
        opens = list(self._m15_opens)

        bull_sweep = False
        bear_sweep = False

        # Look for a sweep in the last 4 bars against a 5-bar prior local extreme
        for i in range(-4, 0):
            if i - 5 < -len(highs):
                continue
            # Prior 5 bars before the sweep bar i
            prior_high = max(highs[i-5:i])
            prior_low = min(lows[i-5:i])
            
            bar_h = highs[i]
            bar_l = lows[i]
            bar_c = closes[i]
            bar_o = opens[i]
            
            body_max = max(bar_o, bar_c)
            body_min = min(bar_o, bar_c)

            if bar_l < prior_low and bar_c > prior_low and (body_min - bar_l) > (body_max - body_min):
                bull_sweep = True
                
            if bar_h > prior_high and bar_c < prior_high and (bar_h - body_max) > (body_max - body_min):
                bear_sweep = True

        return bull_sweep, bear_sweep

    def _classify_regime(self, atr_pct: float, ema_gap_atr: float) -> str:
        if atr_pct > 85:
            return "HIGH_VOL"
        if atr_pct < 20:
            return "COMPRESSION"
        if atr_pct < 40:
            if abs(ema_gap_atr) < 0.3:
                return "RANGE"
            return "LOW_VOL"
        
        if atr_pct > 65:
            return "EXPANSION"
            
        if abs(ema_gap_atr) > 1.0:
            return "STRONG_TREND"
            
        return "WEAK_TREND"

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if len(self._m15_highs) < 15 or self._ema50 is None:
            return self._flat("Warmup", ["warmup"])
            
        if ctx.atr <= 0 or self._vwap_val is None:
            return self._flat("Missing ATR/VWAP", ["data_missing"])

        # Core Phase 2 Indicators
        atr = ctx.atr
        atr_pct = ctx.atr_percentile
        vwap = self._vwap_val
        c = ctx.price
        
        ema_gap_atr = (self._ema20 - self._ema50) / atr
        vwap_dev = (c - vwap) / atr
        rsi = self._rsi14
        
        # Current bar metrics
        curr_bar = ctx.bars_m15[-1]
        bar_range = curr_bar.high - curr_bar.low
        body_pct = abs(curr_bar.close - curr_bar.open) / bar_range if bar_range > 0 else 0
        bull_close = curr_bar.close >= curr_bar.open
        bear_close = curr_bar.close < curr_bar.open

        bull_sweep, bear_sweep = self._check_liquidity_sweep()
        regime = self._classify_regime(atr_pct, ema_gap_atr)

        # ── Mode 1: Trend Continuation ──────────────────────────────────────────
        if regime in ("STRONG_TREND", "HIGH_VOL", "EXPANSION", "WEAK_TREND"):
            # Session check
            if not (ctx.is_overlap or ctx.is_london):
                return self._flat(f"Off-session for trend ({regime})", ["session"])
                
            # Bullish Continuation
            if self._ema20 > self._ema50 and ctx.ema_bull:
                if atr_pct >= 50.0 and 45 < rsi < 75:
                    if abs(vwap_dev) <= 1.5:  # Near VWAP (pullback)
                        if bull_sweep and body_pct >= 0.4 and bull_close:
                            return self._long(
                                confidence=85.0,
                                reason=f"Trend Cont LONG ({regime})",
                                sl_mult=1.2,
                                tp_rr=2.0,
                                passed=["regime", "ema_align", "rsi_mom", "vwap_pb", "sweep"]
                            )
            
            # Bearish Continuation
            elif self._ema20 < self._ema50 and ctx.ema_bear:
                if atr_pct >= 50.0 and 25 < rsi < 55:
                    if abs(vwap_dev) <= 1.5:
                        if bear_sweep and body_pct >= 0.4 and bear_close:
                            return self._short(
                                confidence=85.0,
                                reason=f"Trend Cont SHORT ({regime})",
                                sl_mult=1.2,
                                tp_rr=2.0,
                                passed=["regime", "ema_align", "rsi_mom", "vwap_pb", "sweep"]
                            )
                            
        # ── Mode 2: Mean Reversion ──────────────────────────────────────────────
        elif regime in ("RANGE", "COMPRESSION"):
            if atr_pct < 45 and abs(ema_gap_atr) < 0.3:
                
                # Buy the dip (reversion to VWAP)
                if rsi < 32 and vwap_dev <= -1.5:
                    if bull_sweep and body_pct >= 0.4 and bull_close:
                        target_dist = abs(vwap - c) / atr
                        sl_dist = 1.0
                        if target_dist > 1.0:  # Ensure minimum RR
                            return self._long(
                                confidence=75.0,
                                reason=f"Mean Rev LONG ({regime})",
                                sl_mult=sl_dist,
                                tp_rr=target_dist / sl_dist,
                                passed=["regime", "rsi_ext", "vwap_dev", "sweep"]
                            )
                            
                # Sell the rally (reversion to VWAP)
                elif rsi > 68 and vwap_dev >= 1.5:
                    if bear_sweep and body_pct >= 0.4 and bear_close:
                        target_dist = abs(vwap - c) / atr
                        sl_dist = 1.0
                        if target_dist > 1.0:
                            return self._short(
                                confidence=75.0,
                                reason=f"Mean Rev SHORT ({regime})",
                                sl_mult=sl_dist,
                                tp_rr=target_dist / sl_dist,
                                passed=["regime", "rsi_ext", "vwap_dev", "sweep"]
                            )

        return self._flat(f"No setup in {regime}", ["no_trigger"])
