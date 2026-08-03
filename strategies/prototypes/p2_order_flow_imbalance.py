"""
P2 — Order Flow Imbalance (OFI)
================================
CVD trend direction + absorption detection.

Entry logic:
  - CVD trending: slope of CVD over last 200 ticks is positive (bull) or negative (bear).
  - Absorption: high tick volume at a price level with minimal price movement
    (vol_expansion=True but tick_velocity near zero).
  - LONG : CVD trending positive AND absorption on bid side (sellers absorbed).
  - SHORT: CVD trending negative AND absorption on ask side (buyers absorbed).
  - Confidence: CVD slope steepness × absorption strength.

SL: 1×ATR (momentum trade needs room).
TP: 2×R.
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from typing import Deque, List

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class OrderFlowImbalanceStrategy(BaseStrategy):
    name    = "P2_OrderFlowImbalance"
    version = "1.0"

    default_sl_atr_mult = 1.0
    default_tp_rr       = 2.0

    # Min CVD history entries before issuing signals
    _MIN_CVD_HISTORY = 20
    # Absorption: velocity threshold (price units per tick — small = absorbed)
    _ABS_VELOCITY_THRESHOLD = 0.015
    # Min OF score to even consider a signal
    _MIN_OF_SCORE = 55.0

    def __init__(self):
        super().__init__()
        self._cvd_history: Deque[float] = deque(maxlen=50)
        self._prev_cvd: float = 0.0

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.of_snapshot:
            self._cvd_history.append(ctx.of_snapshot.cvd)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        of = ctx.of_snapshot
        if of is None:
            return self._flat("no OF data", ["of_data"])

        if len(self._cvd_history) < self._MIN_CVD_HISTORY:
            return self._flat("insufficient CVD history", ["cvd_hist"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        # ── CVD trend (slope of last 20 readings) ────────────────────────────
        cvd_vals = list(self._cvd_history)[-20:]
        n = len(cvd_vals)
        if n < 5:
            return self._flat("insufficient CVD", ["cvd_n"])

        # Linear slope (simple: last - first normalised)
        cvd_slope = (cvd_vals[-1] - cvd_vals[0]) / max(n, 1)
        cvd_bull   = cvd_slope > 0
        cvd_bear   = cvd_slope < 0

        # ── Absorption detection ─────────────────────────────────────────────
        vol_expansion = of.volume_expansion                       # bool
        low_velocity  = abs(of.tick_velocity) < self._ABS_VELOCITY_THRESHOLD
        absorption    = vol_expansion and low_velocity

        # ── Direction confirmation from OF score ─────────────────────────────
        of_bull = of.of_score >= self._MIN_OF_SCORE and of.buy_pressure > of.sell_pressure
        of_bear = of.of_score <= (100.0 - self._MIN_OF_SCORE) or \
                  (of.of_score < 50.0 and of.sell_pressure > of.buy_pressure)

        # ── Confidence ───────────────────────────────────────────────────────
        abs_strength = of.participation_rate   # > 1.0 = above-average volume
        slope_mag    = min(abs(cvd_slope) / 5.0, 1.0)  # normalise to 0-1
        base_conf    = 40.0 + slope_mag * 30.0 + min(abs_strength - 1.0, 1.0) * 20.0

        # ── LONG ─────────────────────────────────────────────────────────────
        if cvd_bull and of_bull and absorption:
            conf = min(90.0, base_conf + 10.0)  # absorption bonus
            return self._long(
                confidence=conf,
                reason=f"CVD bull slope={cvd_slope:.1f} absorption={absorption} OF={of.of_score:.1f}",
                passed=["cvd_bull", "absorption", "of_bull"],
            )

        if cvd_bull and of_bull and not absorption:
            conf = min(75.0, base_conf)
            return self._long(
                confidence=conf,
                reason=f"CVD bull slope={cvd_slope:.1f} OF={of.of_score:.1f} (no abs)",
                passed=["cvd_bull", "of_bull"],
                sl_mult=1.2,
            )

        # ── SHORT ────────────────────────────────────────────────────────────
        if cvd_bear and of_bear and absorption:
            conf = min(90.0, base_conf + 10.0)
            return self._short(
                confidence=conf,
                reason=f"CVD bear slope={cvd_slope:.1f} absorption={absorption} OF={of.of_score:.1f}",
                passed=["cvd_bear", "absorption", "of_bear"],
            )

        if cvd_bear and of_bear and not absorption:
            conf = min(75.0, base_conf)
            return self._short(
                confidence=conf,
                reason=f"CVD bear slope={cvd_slope:.1f} OF={of.of_score:.1f} (no abs)",
                passed=["cvd_bear", "of_bear"],
                sl_mult=1.2,
            )

        return self._flat(
            f"no signal: cvd_slope={cvd_slope:.2f} OF={of.of_score:.1f} abs={absorption}",
            failed=["no_confluence"],
        )
