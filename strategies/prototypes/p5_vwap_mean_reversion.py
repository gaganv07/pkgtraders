"""
P5 — VWAP Mean Reversion (VMR)
================================
Price stretched from session VWAP in a non-trending regime.

Entry logic:
  - VWAP deviation: (price − VWAP) / VWAP × 100  (%)
  - LONG : deviation ≤ −0.15% (price below VWAP) AND momentum turning up
           (last 3 M15 closes trending toward VWAP) AND vol_regime ≠ EXPLOSIVE.
  - SHORT: deviation ≥ +0.15% AND momentum turning down AND vol_regime ≠ EXPLOSIVE.
  - Regime filter: COMPRESSED or NORMAL only (mean-reversion fails in trending/expanding).
  - Confidence: proportional to deviation magnitude (more stretched = higher confidence).

SL: 0.5×ATR away from VWAP (i.e. further from the mean).
TP: VWAP level (1:2-1:3 R depending on deviation).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class VWAPMeanReversionStrategy(BaseStrategy):
    name    = "P5_VWAPMeanReversion"
    version = "1.0"

    default_sl_atr_mult = 0.5
    default_tp_rr       = 2.5

    # Minimum VWAP deviation to trigger (%)
    _MIN_DEV_PCT  = 0.12
    # Max deviation (beyond this price has broken away — not mean reversion)
    _MAX_DEV_PCT  = 0.60
    # Regime requirement
    _BAD_REGIMES  = ("EXPLOSIVE",)
    # Momentum lookback (bars must be moving toward VWAP)
    _MOMENTUM_N   = 3

    def on_bar(self, ctx: StrategyContext) -> None:
        pass  # no stateful indicator — uses ctx.vwap directly

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if ctx.vwap is None or ctx.vwap <= 0:
            return self._flat("VWAP not ready", ["vwap"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        if ctx.vol_regime in self._BAD_REGIMES:
            return self._flat(f"regime={ctx.vol_regime}", ["regime"])

        price = ctx.price
        dev   = (price - ctx.vwap) / ctx.vwap * 100.0

        if abs(dev) < self._MIN_DEV_PCT:
            return self._flat(f"dev={dev:.3f}% too small", ["deviation_min"])

        if abs(dev) > self._MAX_DEV_PCT:
            return self._flat(f"dev={dev:.3f}% too large (blown away)", ["deviation_max"])

        bars = ctx.recent_m15(self._MOMENTUM_N + 1)
        if len(bars) < self._MOMENTUM_N:
            return self._flat("insufficient bars", ["bars"])

        # Momentum: are last N closes moving toward VWAP?
        vwap = ctx.vwap
        closes = [b.close for b in bars[-self._MOMENTUM_N:]]

        # ── LONG: price below VWAP, momentum pointing up toward VWAP ─────────
        if dev < -self._MIN_DEV_PCT:
            # Each close should be closer to vwap than the previous
            moving_toward = sum(1 for i in range(1, len(closes))
                                if closes[i] > closes[i-1]) >= (self._MOMENTUM_N - 1)
            if not moving_toward:
                return self._flat(f"momentum not up: dev={dev:.3f}%", ["momentum"])

            conf = min(90.0, 50.0 + abs(dev) / self._MAX_DEV_PCT * 40.0)
            tp_dist = abs(vwap - price)
            tp_rr   = tp_dist / (ctx.atr * self.default_sl_atr_mult)

            return self._long(
                confidence=conf,
                reason=f"VWAP rev LONG: dev={dev:.3f}% VWAP={vwap:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr),
                passed=["dev_below", "momentum_up", "regime_ok"],
            )

        # ── SHORT: price above VWAP, momentum pointing down toward VWAP ──────
        if dev > self._MIN_DEV_PCT:
            moving_toward = sum(1 for i in range(1, len(closes))
                                if closes[i] < closes[i-1]) >= (self._MOMENTUM_N - 1)
            if not moving_toward:
                return self._flat(f"momentum not down: dev={dev:.3f}%", ["momentum"])

            conf = min(90.0, 50.0 + abs(dev) / self._MAX_DEV_PCT * 40.0)
            tp_dist = abs(vwap - price)
            tp_rr   = tp_dist / (ctx.atr * self.default_sl_atr_mult)

            return self._short(
                confidence=conf,
                reason=f"VWAP rev SHORT: dev={dev:.3f}% VWAP={vwap:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr),
                passed=["dev_above", "momentum_down", "regime_ok"],
            )

        return self._flat("no setup")
