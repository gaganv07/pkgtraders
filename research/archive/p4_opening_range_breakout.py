"""
P4 — Opening Range Breakout (ORB)
===================================
Session open range defines the day's directional bias.

Entry logic:
  - Opening Range (OR): First 60 minutes of London open — 07:00-07:59 UTC.
  - Track OR High and OR Low across all M15 bars in that window.
  - Trade Window: 08:00-12:59 UTC only (post-OR, pre-NY close).
  - LONG : M15 bar closes above OR High with volume ≥ 1.2× avg AND EMA50 above EMA200.
  - SHORT: M15 bar closes below OR Low  with volume ≥ 1.2× avg AND EMA50 below EMA200.
  - OR is reset daily at 07:00 UTC.
  - Confidence: proportional to breakout momentum (close beyond OR).

SL: 0.3×ATR inside OR (just below OR high for long / above OR low for short).
TP: 1×OR range projected from breakout level.
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


class OpeningRangeBreakoutStrategy(BaseStrategy):
    name    = "P4_OpeningRangeBreakout"
    version = "1.0"

    default_sl_atr_mult = 0.5
    default_tp_rr       = 2.0

    # OR definition
    _OR_START_HOUR = 7     # 07:00 UTC
    _OR_END_HOUR   = 8     # 08:00 UTC (exclusive)
    # Trade window: 08:00 – 13:00 UTC
    _TRADE_START = 8
    _TRADE_END   = 13
    # Volume expansion ratio
    _VOL_RATIO = 1.2
    # Rolling volume window for avg
    _VOL_WINDOW = 20

    def __init__(self):
        super().__init__()
        self._or_high:  Optional[float] = None
        self._or_low:   Optional[float] = None
        self._or_date:  Optional[str]   = None
        self._signal_fired_today: bool  = False
        self._vol_buf:  Deque[int] = deque(maxlen=self._VOL_WINDOW)
        self._bar_buf:  Deque[Bar] = deque(maxlen=5)

    # ── OR tracking ───────────────────────────────────────────────────────────

    def _update_or(self, bar: Bar, timestamp: datetime) -> None:
        date_key = timestamp.strftime("%Y-%m-%d")
        h = timestamp.hour

        # New day reset
        if date_key != self._or_date:
            self._or_high = None
            self._or_low  = None
            self._or_date = date_key
            self._signal_fired_today = False

        # Accumulate OR bars (07:00 – 07:59 UTC)
        if h == self._OR_START_HOUR:
            self._or_high = max(self._or_high, bar.high) if self._or_high else bar.high
            self._or_low  = min(self._or_low,  bar.low)  if self._or_low  else bar.low

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def on_bar(self, ctx: StrategyContext) -> None:
        if not ctx.bars_m15:
            return
        bar = ctx.bars_m15[-1]
        self._bar_buf.append(bar)
        self._vol_buf.append(bar.tick_vol)
        self._update_or(bar, ctx.timestamp)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if self._or_high is None or self._or_low is None:
            return self._flat("OR not set", ["or_defined"])

        h = ctx.timestamp.hour
        if not (self._TRADE_START <= h < self._TRADE_END):
            return self._flat(f"outside trade window (hour={h})", ["trade_window"])

        if self._signal_fired_today:
            return self._flat("already traded today", ["daily_limit"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        bars = list(self._bar_buf)
        if not bars:
            return self._flat("no bars", ["bars"])
        curr = bars[-1]

        or_range = self._or_high - self._or_low
        if or_range <= ctx.atr * 0.2:
            return self._flat("OR too narrow", ["or_range"])

        # Volume check
        avg_vol = statistics.mean(self._vol_buf) if self._vol_buf else 1
        vol_ok  = curr.tick_vol >= avg_vol * self._VOL_RATIO

        # ── LONG: close above OR High ─────────────────────────────────────────
        if curr.close > self._or_high and vol_ok and ctx.ema_bull:
            penetration = (curr.close - self._or_high) / or_range
            conf = min(90.0, 50.0 + penetration * 200.0)
            tp_rr_actual = or_range / (ctx.atr * self.default_sl_atr_mult)
            self._signal_fired_today = True
            return self._long(
                confidence=conf,
                reason=f"ORB LONG: close={curr.close:.2f} OR_H={self._or_high:.2f} OR_range={or_range:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr_actual),
                passed=["or_breakout", "volume_expansion", "ema_bull"],
            )

        # ── SHORT: close below OR Low ─────────────────────────────────────────
        if curr.close < self._or_low and vol_ok and ctx.ema_bear:
            penetration = (self._or_low - curr.close) / or_range
            conf = min(90.0, 50.0 + penetration * 200.0)
            tp_rr_actual = or_range / (ctx.atr * self.default_sl_atr_mult)
            self._signal_fired_today = True
            return self._short(
                confidence=conf,
                reason=f"ORB SHORT: close={curr.close:.2f} OR_L={self._or_low:.2f} OR_range={or_range:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr_actual),
                passed=["or_breakout", "volume_expansion", "ema_bear"],
            )

        failed = []
        if not vol_ok:             failed.append("volume_low")
        if curr.close <= self._or_high and curr.close >= self._or_low:
            failed.append("price_inside_or")
        return self._flat("no breakout", failed)
