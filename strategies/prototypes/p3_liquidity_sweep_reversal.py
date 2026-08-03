"""
P3 — Liquidity Sweep Reversal (LSR)
=====================================
Institutional stop-hunt detection followed by reversal confirmation.

Entry logic:
  - Track rolling swing highs/lows from M15 bars (last 50 bars, 3-bar pivot).
  - SWEEP: Price extends ≥ 0.5×ATR beyond a recent swing, then closes back.
  - CONFIRMATION: The close-back bar itself has body > 60% of bar range.
  - LONG : Sweep of swing LOW (stop run below support) + bullish confirmation.
  - SHORT: Sweep of swing HIGH (stop run above resistance) + bearish confirmation.
  - Confidence: speed of reversal (1-bar sweep = highest confidence) + body ratio.

SL: 0.5×ATR beyond the sweep extreme (tight stop; the sweep low/high is the worst case).
TP: 3×R (momentum follow-through after the sweep).
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from app.market_data import Bar

logger = logging.getLogger(__name__)


@dataclass
class _SwingPoint:
    price: float
    kind:  str    # "HIGH" | "LOW"
    index: int    # bar index in the rolling buffer


class LiquiditySweepReversalStrategy(BaseStrategy):
    name    = "P3_LiquiditySweepReversal"
    version = "1.0"

    default_sl_atr_mult = 0.5
    default_tp_rr       = 3.0

    # Pivot confirmation: bars on each side
    _PIVOT_N = 3
    # Rolling bar buffer
    _BAR_WINDOW = 60
    # Sweep extension: minimum distance beyond swing
    _SWEEP_ATR_MIN = 0.3
    # Body ratio for confirmation bar
    _MIN_BODY_RATIO = 0.55

    def __init__(self):
        super().__init__()
        self._bar_buf: Deque[Bar] = deque(maxlen=self._BAR_WINDOW + 10)
        self._swings: List[_SwingPoint] = []
        self._bar_idx: int = 0
        self._last_signal_idx: int = -10   # cooldown

    # ── Swing detection ───────────────────────────────────────────────────────

    def _detect_swings(self) -> None:
        bars = list(self._bar_buf)
        n    = len(bars)
        if n < self._PIVOT_N * 2 + 1:
            return

        self._swings.clear()
        p = self._PIVOT_N
        for i in range(p, n - p):
            mid = bars[i]
            left  = bars[i - p : i]
            right = bars[i + 1 : i + p + 1]

            is_high = (mid.high >= max(b.high for b in left) and
                       mid.high >= max(b.high for b in right))
            is_low  = (mid.low <= min(b.low for b in left) and
                       mid.low <= min(b.low for b in right))

            if is_high:
                self._swings.append(_SwingPoint(mid.high, "HIGH", i))
            if is_low:
                self._swings.append(_SwingPoint(mid.low, "LOW", i))

    # ── Sweep detection ───────────────────────────────────────────────────────

    def _find_sweep(self, bars: List[Bar], atr: float) -> Optional[Tuple[str, float, float]]:
        """
        Returns (direction, sweep_extreme, swing_price) or None.
        direction: "LONG" (sweep of swing low) or "SHORT" (sweep of swing high).
        """
        if len(bars) < 2 or not self._swings or atr <= 0:
            return None

        prev = bars[-2]
        curr = bars[-1]

        # ── Long setup: sweep below recent swing LOW ──────────────────────────
        recent_lows = [s for s in self._swings if s.kind == "LOW"][-3:]
        for sw in recent_lows:
            min_sweep = sw.price - atr * self._SWEEP_ATR_MIN
            if prev.low <= min_sweep and curr.close > sw.price:
                # Confirmation: bullish body
                body_ratio = (curr.close - curr.open) / max(curr.range, 0.0001)
                if curr.is_bull and body_ratio >= self._MIN_BODY_RATIO:
                    return ("LONG", prev.low, sw.price)

        # ── Short setup: sweep above recent swing HIGH ────────────────────────
        recent_highs = [s for s in self._swings if s.kind == "HIGH"][-3:]
        for sw in recent_highs:
            max_sweep = sw.price + atr * self._SWEEP_ATR_MIN
            if prev.high >= max_sweep and curr.close < sw.price:
                body_ratio = (curr.open - curr.close) / max(curr.range, 0.0001)
                if curr.is_bear and body_ratio >= self._MIN_BODY_RATIO:
                    return ("SHORT", prev.high, sw.price)

        return None

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            self._bar_buf.append(ctx.bars_m15[-1])
        self._bar_idx += 1
        self._detect_swings()

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        bars = list(self._bar_buf)
        if len(bars) < self._PIVOT_N * 2 + 3:
            return self._flat("insufficient bars", ["bars"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        # Cooldown: at most 1 signal per 3 bars
        if self._bar_idx - self._last_signal_idx < 3:
            return self._flat("cooldown")

        result = self._find_sweep(bars, ctx.atr)
        if result is None:
            return self._flat("no sweep", ["sweep"])

        direction, sweep_extreme, swing_price = result
        curr = bars[-1]

        # Confidence: body ratio + extension depth
        body_ratio    = abs(curr.close - curr.open) / max(curr.range, 0.0001)
        sweep_depth   = abs(sweep_extreme - swing_price) / ctx.atr
        confidence    = min(90.0, 40.0 + body_ratio * 30.0 + sweep_depth * 20.0)

        self._last_signal_idx = self._bar_idx

        if direction == "LONG":
            return self._long(
                confidence=confidence,
                reason=f"Sweep LOW: extreme={sweep_extreme:.2f} swing={swing_price:.2f} body={body_ratio:.2f}",
                sl_mult=self.default_sl_atr_mult,
                tp_rr=self.default_tp_rr,
                passed=["sweep_low", "bull_confirmation", "body_ratio"],
            )
        else:
            return self._short(
                confidence=confidence,
                reason=f"Sweep HIGH: extreme={sweep_extreme:.2f} swing={swing_price:.2f} body={body_ratio:.2f}",
                sl_mult=self.default_sl_atr_mult,
                tp_rr=self.default_tp_rr,
                passed=["sweep_high", "bear_confirmation", "body_ratio"],
            )
