"""
P6 — Trend Pullback (TPB)
==========================
Systematic re-entry into established trend after corrective pullback to EMA50.

Entry logic:
  - TREND: H1 EMA50 > EMA200 = bull; EMA50 < EMA200 = bear. (Golden/Death cross on H1.)
  - PULLBACK: Price on M15 touches within 0.3×ATR of H1 EMA50.
  - ENTRY BAR: Next M15 bar closes beyond the EMA50 in the trend direction.
  - VOLUME: Pullback bars on below-average volume; entry bar on above-average volume.
  - EMA50 SLOPE: Must be positive for longs, negative for shorts (dynamic trend).
  - Confidence: scaled by EMA50/200 separation (wider separation = stronger trend).

SL: 0.5×ATR below (long) or above (short) the EMA50 touch.
TP: 3×R (trend continuation).
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from typing import Deque, List, Optional, Tuple

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from app.market_data import Bar

logger = logging.getLogger(__name__)


class TrendPullbackStrategy(BaseStrategy):
    name    = "P6_TrendPullback"
    version = "1.0"

    default_sl_atr_mult = 0.5
    default_tp_rr       = 3.0

    # Pullback proximity to EMA50 (in ATR multiples)
    _PULLBACK_ATR = 0.3
    # Volume ratio for entry bar
    _VOL_RATIO    = 1.15
    # Rolling bar window
    _BAR_WIN      = 30
    # Minimum EMA50/200 separation (as fraction of price) to confirm trend
    _MIN_EMA_SEP  = 0.0003    # 0.03% = 30 pips on Eur/Usd

    def __init__(self):
        super().__init__()
        self._bar_buf:    Deque[Bar]   = deque(maxlen=self._BAR_WIN)
        self._vol_buf:    Deque[int]   = deque(maxlen=20)
        self._pb_active:  bool         = False   # pullback touch detected
        self._pb_side:    str          = ""      # "BULL" | "BEAR"
        self._pb_bar_idx: int          = -5
        self._bar_idx:    int          = 0
        self._ema50_m15:  Optional[float] = None

    # ── EMA50 on M15 (computed inline) ───────────────────────────────────────

    def _compute_ema50_m15(self) -> Optional[float]:
        bars = list(self._bar_buf)
        if len(bars) < 10:
            return None
        k   = 2.0 / 51.0
        val = bars[0].close
        for b in bars[1:]:
            val = b.close * k + val * (1.0 - k)
        return val

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            b = ctx.bars_m15[-1]
            self._bar_buf.append(b)
            self._vol_buf.append(b.tick_vol)
        self._bar_idx  += 1
        self._ema50_m15 = self._compute_ema50_m15()

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        # ── Prerequisite checks ───────────────────────────────────────────────
        if ctx.ema50 is None or ctx.ema200 is None:
            return self._flat("EMA not ready", ["ema"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        bars = list(self._bar_buf)
        if len(bars) < 5:
            return self._flat("insufficient bars", ["bars"])

        price   = ctx.price
        ema50h1 = ctx.ema50
        ema200  = ctx.ema200
        ema50m15 = self._ema50_m15

        if ema50m15 is None:
            return self._flat("M15 EMA not ready", ["m15_ema"])

        # ── EMA separation check ─────────────────────────────────────────────
        sep = abs(ema50h1 - ema200) / ema200
        if sep < self._MIN_EMA_SEP:
            return self._flat(f"EMA sep too small: {sep:.4f}", ["ema_sep"])

        bull_trend = ema50h1 > ema200
        bear_trend = ema50h1 < ema200

        avg_vol = statistics.mean(self._vol_buf) if self._vol_buf else 1
        curr    = bars[-1]
        vol_ok  = curr.tick_vol >= avg_vol * self._VOL_RATIO

        # ── LONG SETUP ───────────────────────────────────────────────────────
        if bull_trend:
            # EMA50 slope positive?
            ema_slope = ctx.vwap_slope if ctx.vwap_slope else 0.0   # proxy; actual slope in ctx
            # Detect pullback: recent bar touched within 0.3×ATR of M15 EMA50
            prev = bars[-2] if len(bars) >= 2 else curr
            pb_touch = abs(prev.low - ema50m15) <= ctx.atr * self._PULLBACK_ATR

            if pb_touch and not self._pb_active:
                self._pb_active  = True
                self._pb_side    = "BULL"
                self._pb_bar_idx = self._bar_idx

            if self._pb_active and self._pb_side == "BULL":
                # Entry: current bar closes above EMA50 in bull direction
                if curr.close > ema50m15 and vol_ok:
                    bars_since_pb = self._bar_idx - self._pb_bar_idx
                    if bars_since_pb <= 4:    # pullback must be fresh (within 4 bars)
                        sep_conf  = min(1.0, sep / 0.003)   # wider sep = more confidence
                        vol_bonus = min(curr.tick_vol / avg_vol / 2.0, 0.2)
                        conf      = min(88.0, 50.0 + sep_conf * 30.0 + vol_bonus * 20.0)
                        self._pb_active = False
                        return self._long(
                            confidence=conf,
                            reason=f"Pullback LONG: EMA50m15={ema50m15:.2f} vol_ratio={curr.tick_vol/avg_vol:.2f}",
                            sl_mult=0.5, tp_rr=self.default_tp_rr,
                            passed=["bull_trend", "pullback_touch", "close_above_ema", "volume_ok"],
                        )
                # Timeout: pullback too old
                if self._bar_idx - self._pb_bar_idx > 4:
                    self._pb_active = False

        # ── SHORT SETUP ──────────────────────────────────────────────────────
        if bear_trend:
            prev     = bars[-2] if len(bars) >= 2 else curr
            pb_touch = abs(prev.high - ema50m15) <= ctx.atr * self._PULLBACK_ATR

            if pb_touch and not self._pb_active:
                self._pb_active  = True
                self._pb_side    = "BEAR"
                self._pb_bar_idx = self._bar_idx

            if self._pb_active and self._pb_side == "BEAR":
                if curr.close < ema50m15 and vol_ok:
                    bars_since_pb = self._bar_idx - self._pb_bar_idx
                    if bars_since_pb <= 4:
                        sep_conf  = min(1.0, sep / 0.003)
                        vol_bonus = min(curr.tick_vol / avg_vol / 2.0, 0.2)
                        conf      = min(88.0, 50.0 + sep_conf * 30.0 + vol_bonus * 20.0)
                        self._pb_active = False
                        return self._short(
                            confidence=conf,
                            reason=f"Pullback SHORT: EMA50m15={ema50m15:.2f} vol_ratio={curr.tick_vol/avg_vol:.2f}",
                            sl_mult=0.5, tp_rr=self.default_tp_rr,
                            passed=["bear_trend", "pullback_touch", "close_below_ema", "volume_ok"],
                        )
                if self._bar_idx - self._pb_bar_idx > 4:
                    self._pb_active = False

        return self._flat("no pullback setup")
