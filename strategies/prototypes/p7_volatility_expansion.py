"""
P7 — Volatility Expansion (VEX)
=================================
Enter at the leading edge of a volatility expansion phase.

Entry logic:
  - REGIME TRANSITION: vol_regime transitions COMPRESSED→NORMAL or NORMAL→EXPANDING.
  - ATR confirmation: Current ATR > rolling 10-bar ATR mean (expansion confirmed on M15).
  - DIRECTION: EMA20 slope on M15 defines bias (which way compression broke).
  - ENTRY TRIGGER: First M15 close that breaks the recent 10-bar high (LONG) or
    10-bar low (SHORT) after the regime transition.
  - COMMITMENT: Entry bar body must be > 50% of bar range.
  - Confidence: proportional to ATR percentile jump (sharpness of transition).

SL: Low of the trigger bar (LONG) or high (SHORT).
TP: 2.5×ATR.
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from typing import Deque, List, Optional

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from app.market_data import Bar

logger = logging.getLogger(__name__)


class VolatilityExpansionStrategy(BaseStrategy):
    name    = "P7_VolatilityExpansion"
    version = "1.0"

    default_sl_atr_mult = 1.0   # overridden by bar low/high
    default_tp_rr       = 2.5

    # ATR rolling mean window
    _ATR_WINDOW = 10
    # Breakout lookback
    _BREAKOUT_N = 10
    # Body commitment ratio
    _MIN_BODY   = 0.50
    # Signal cooldown bars
    _COOLDOWN   = 4
    # EMA20 calc window
    _EMA20_WIN  = 20

    def __init__(self):
        super().__init__()
        self._bar_buf:     Deque[Bar]   = deque(maxlen=self._BREAKOUT_N + 5)
        self._atr_buf:     Deque[float] = deque(maxlen=self._ATR_WINDOW + 5)
        self._prev_regime: str          = "NORMAL"
        self._transition:  bool         = False
        self._bar_idx:     int          = 0
        self._last_signal: int          = -10
        self._ema20_vals:  Deque[float] = deque(maxlen=self._EMA20_WIN * 3)

    # ── EMA20 slope ───────────────────────────────────────────────────────────

    def _ema20_slope(self) -> float:
        """Positive = bullish, negative = bearish."""
        closes = [b.close for b in self._bar_buf]
        if len(closes) < self._EMA20_WIN + 1:
            return 0.0
        k   = 2.0 / (self._EMA20_WIN + 1)
        val = closes[0]
        history = []
        for c in closes[1:]:
            val = c * k + val * (1.0 - k)
            history.append(val)
        if len(history) < 2:
            return 0.0
        return history[-1] - history[-2]

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            self._bar_buf.append(ctx.bars_m15[-1])
        if ctx.atr > 0:
            self._atr_buf.append(ctx.atr)

        # Detect regime transition
        curr_regime = ctx.vol_regime
        if (self._prev_regime in ("COMPRESSED", "NORMAL") and
                curr_regime in ("NORMAL", "EXPANDING")):
            self._transition = True
        self._prev_regime = curr_regime
        self._bar_idx    += 1

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        bars = list(self._bar_buf)
        if len(bars) < self._BREAKOUT_N:
            return self._flat("insufficient bars", ["bars"])

        # Cooldown
        if self._bar_idx - self._last_signal < self._COOLDOWN:
            return self._flat("cooldown")

        if not self._transition:
            return self._flat("no regime transition", ["regime"])

        # ATR must be expanding
        if len(self._atr_buf) >= self._ATR_WINDOW:
            atr_ma = statistics.mean(list(self._atr_buf)[-self._ATR_WINDOW:])
            if ctx.atr <= atr_ma:
                return self._flat("ATR not expanding", ["atr_expand"])

        # Reset transition flag after checking
        self._transition = False

        # Explosive regime = too hot for a trend entry (whipsaw risk)
        if ctx.vol_regime == "EXPLOSIVE":
            return self._flat("regime=EXPLOSIVE", ["regime"])

        curr   = bars[-1]
        window = bars[-self._BREAKOUT_N:-1]   # exclude current bar

        if not window:
            return self._flat("window empty", ["window"])

        recent_high = max(b.high for b in window)
        recent_low  = min(b.low  for b in window)

        body_ratio  = curr.body / max(curr.range, 0.0001)
        ema_slope   = self._ema20_slope()

        # ── LONG: close above recent 10-bar high, bullish body, EMA rising ───
        if (curr.close > recent_high and
                body_ratio >= self._MIN_BODY and
                ema_slope > 0):
            sl_dist = curr.close - curr.low
            sl_mult = sl_dist / ctx.atr if ctx.atr > 0 else 1.0
            conf    = min(90.0, 45.0 + ctx.atr_percentile * 0.4 + body_ratio * 15.0)
            self._last_signal = self._bar_idx
            return self._long(
                confidence=conf,
                reason=f"VEX LONG: close={curr.close:.2f} > H10={recent_high:.2f} EMA_slope={ema_slope:.4f}",
                sl_mult=max(0.3, sl_mult), tp_rr=self.default_tp_rr,
                passed=["regime_transition", "atr_expanding", "breakout_high", "body_ok", "ema_up"],
            )

        # ── SHORT: close below recent 10-bar low, bearish body, EMA falling ──
        if (curr.close < recent_low and
                body_ratio >= self._MIN_BODY and
                ema_slope < 0):
            sl_dist = curr.high - curr.close
            sl_mult = sl_dist / ctx.atr if ctx.atr > 0 else 1.0
            conf    = min(90.0, 45.0 + ctx.atr_percentile * 0.4 + body_ratio * 15.0)
            self._last_signal = self._bar_idx
            return self._short(
                confidence=conf,
                reason=f"VEX SHORT: close={curr.close:.2f} < L10={recent_low:.2f} EMA_slope={ema_slope:.4f}",
                sl_mult=max(0.3, sl_mult), tp_rr=self.default_tp_rr,
                passed=["regime_transition", "atr_expanding", "breakout_low", "body_ok", "ema_down"],
            )

        failed = []
        if curr.close <= recent_high and curr.close >= recent_low:
            failed.append("no_breakout")
        if body_ratio < self._MIN_BODY:
            failed.append("body_too_small")
        return self._flat("no VEX setup", failed)
