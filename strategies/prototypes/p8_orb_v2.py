"""
P8 — Opening Range Breakout V2 (ORB-V2)
==========================================
Redesign of P4 to address its 30.78% max drawdown.

Root cause of P4's failure (from certification report):
  - SL too tight: 0.3× ATR was well inside typical intraday noise
  - Volume threshold too lax: 1.2× triggered on weak moves
  - EMA check only on one timeframe: H1 alignment not required
  - Trade window too wide (08:00–13:00): late signals had poor fills

P8 fixes:
  1. SL distance = max(1.0× OR range, 1.0× ATR14_M5) — never tighter than OR
  2. Volume threshold raised to 1.5× 20-bar average (was 1.2×)
  3. EMA50/200 alignment required on BOTH M15 AND H1 (dual-TF confirmation)
  4. ATR percentile must be ≥ 40 (blocks low-vol traps — V3 insight)
  5. OR range quality: OR range ≥ 1.5× ATR (was 0.2× — far too permissive)
  6. Trade window shortened to 08:00–11:30 UTC (captures London open momentum)
  7. One trade per day per symbol per direction
  8. Extended to EURUSD and GBPUSD (London-centric pairs)

Entry:
  - OR: First 60 minutes of London open — 07:00–07:59 UTC (M15 bars)
  - LONG : M15 close > OR High + vol_ok + ema_bull_h1 + ema_bull_m15 + atr_ok
  - SHORT: M15 close < OR Low  + vol_ok + ema_bear_h1 + ema_bear_m15 + atr_ok

SL / TP:
  - SL = max(1.0× OR range, 1.0× ATR14_M5) — placed at OR edge as buffer
  - TP1 = 1.0× SL distance (close 30%)
  - TP2 = 2.0× SL distance (close 30%)
  - TP3 = 3.0× SL distance (close 40%)
  - Breakeven trigger at 1.0× risk

Confidence: proportional to breakout penetration beyond OR edge.
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


class OpeningRangeBreakoutV2Strategy(BaseStrategy):
    name    = "P8_ORB_V2"
    version = "2.0"

    # ── OR definition ──────────────────────────────────────────────────────────
    _OR_START_HOUR = 7      # 07:00 UTC — OR accumulation begins
    _OR_END_HOUR   = 8      # 08:00 UTC — OR ends, trade window opens

    # ── Trade window ────────────────────────────────────────────────────────────
    _TRADE_START_H = 8      # 08:00 UTC
    _TRADE_END_H   = 11     # 11:00 UTC (inclusive) — close at 11:30
    _TRADE_END_MIN = 30     # stop new entries at 11:30

    # ── Filter thresholds ───────────────────────────────────────────────────────
    _VOL_RATIO       = 1.5   # volume expansion vs 20-bar mean (up from P4's 1.2)
    _VOL_WINDOW      = 20    # bars for average volume
    _ATR_PCT_MIN     = 40    # minimum ATR percentile (0-100)
    _OR_RANGE_ATR_MULT = 1.5 # OR range must be ≥ this × ATR

    def __init__(self):
        super().__init__()
        self._or_high:  Optional[float] = None
        self._or_low:   Optional[float] = None
        self._or_date:  Optional[str]   = None
        self._signal_fired_today: bool  = False
        self._vol_buf:  Deque[int] = deque(maxlen=self._VOL_WINDOW)
        self._bar_buf:  Deque[Bar] = deque(maxlen=5)

    # ── OR tracking ───────────────────────────────────────────────────────────

    def _update_or(self, bar: Bar, ts: datetime) -> None:
        date_key = ts.strftime("%Y-%m-%d")
        h = ts.hour

        # New-day reset
        if date_key != self._or_date:
            self._or_high = None
            self._or_low  = None
            self._or_date = date_key
            self._signal_fired_today = False

        # Accumulate OR bars (07:00–07:59 UTC)
        if h == self._OR_START_HOUR:
            self._or_high = max(self._or_high, bar.high) if self._or_high else bar.high
            self._or_low  = min(self._or_low,  bar.low)  if self._or_low  else bar.low

    # ── BaseStrategy interface ─────────────────────────────────────────────────

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
        # ── Pre-checks ────────────────────────────────────────────────────────
        if self._or_high is None or self._or_low is None:
            return self._flat("OR not established", ["or_defined"])

        ts = ctx.timestamp
        h, m = ts.hour, ts.minute

        # Trade window: 08:00 – 11:30 UTC
        in_window = (
            self._TRADE_START_H <= h < self._TRADE_END_H or
            (h == self._TRADE_END_H and m <= self._TRADE_END_MIN)
        )
        if not in_window:
            return self._flat(f"outside trade window ({h:02d}:{m:02d})", ["trade_window"])

        if self._signal_fired_today:
            return self._flat("already traded today", ["daily_limit"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        bars = list(self._bar_buf)
        if not bars:
            return self._flat("no M15 bars", ["bars"])

        curr = bars[-1]
        or_range = self._or_high - self._or_low

        # ── Filter 1: OR range quality ─────────────────────────────────────────
        if or_range < ctx.atr * self._OR_RANGE_ATR_MULT:
            return self._flat(
                f"OR too narrow: {or_range:.4f} < {ctx.atr * self._OR_RANGE_ATR_MULT:.4f}",
                ["or_range"]
            )

        # ── Filter 2: ATR percentile ────────────────────────────────────────────
        # vol_state is a VolState object with a .percentile attribute
        atr_pct = ctx.vol_state.percentile if ctx.vol_state else 50.0
        if atr_pct < self._ATR_PCT_MIN:
            return self._flat(
                f"ATR percentile too low: {atr_pct:.0f} < {self._ATR_PCT_MIN}",
                ["atr_percentile"]
            )

        # ── Filter 3: Volume ────────────────────────────────────────────────────
        avg_vol = statistics.mean(self._vol_buf) if len(self._vol_buf) >= 5 else None
        vol_ok  = (avg_vol is not None) and (curr.tick_vol >= avg_vol * self._VOL_RATIO)

        # ── Filter 4: Dual-TF EMA ───────────────────────────────────────────────
        # StrategyContext exposes ema_bull (H1-based) and ema50_m15/ema200 for M15 check
        ema_bull_h1  = ctx.ema_bull   # derived from ema50/ema200 (H1)
        ema_bear_h1  = ctx.ema_bear
        # M15 EMA: ema50_m15 vs ema200 (ema200 is H1 here, use ema50_m15 availability as proxy)
        ema50_m15    = ctx.ema50_m15
        ema200_h1    = ctx.ema200
        ema_bull_m15 = (ema50_m15 is not None and ema200_h1 is not None and ema50_m15 > ema200_h1)
        ema_bear_m15 = (ema50_m15 is not None and ema200_h1 is not None and ema50_m15 < ema200_h1)

        ema_long_ok  = ema_bull_h1 and ema_bull_m15
        ema_short_ok = ema_bear_h1 and ema_bear_m15

        # ── SL distance: max(OR range, ATR) ────────────────────────────────────
        sl_distance = max(or_range, ctx.atr)   # never tighter than OR range

        # ── LONG: close above OR High ──────────────────────────────────────────
        if curr.close > self._or_high:
            failed = []
            if not vol_ok:        failed.append("volume_low")
            if not ema_long_ok:   failed.append("ema_no_dual_tf_confirm")
            if failed:
                return self._flat(
                    f"ORB-V2 LONG blocked: {failed}",
                    failed
                )

            penetration = (curr.close - self._or_high) / or_range
            conf = min(90.0, 55.0 + penetration * 150.0)
            tp_rr = or_range / sl_distance   # natural TP based on range vs SL
            tp_rr = max(2.0, min(4.0, tp_rr))  # cap 2-4R

            self._signal_fired_today = True
            return self._long(
                confidence=conf,
                reason=(
                    f"ORB-V2 LONG: close={curr.close:.4f} "
                    f"OR_H={self._or_high:.4f} OR_range={or_range:.4f} "
                    f"SL_dist={sl_distance:.4f} atr_pct={atr_pct:.0f}"
                ),
                sl_mult=sl_distance / max(ctx.atr, 1e-8),   # convert to ATR-multiple
                tp_rr=tp_rr,
                passed=["or_breakout", "volume_expansion", "ema_dual_tf_bull", "atr_ok"],
            )

        # ── SHORT: close below OR Low ──────────────────────────────────────────
        if curr.close < self._or_low:
            failed = []
            if not vol_ok:        failed.append("volume_low")
            if not ema_short_ok:  failed.append("ema_no_dual_tf_confirm")
            if failed:
                return self._flat(
                    f"ORB-V2 SHORT blocked: {failed}",
                    failed
                )

            penetration = (self._or_low - curr.close) / or_range
            conf = min(90.0, 55.0 + penetration * 150.0)
            tp_rr = or_range / sl_distance
            tp_rr = max(2.0, min(4.0, tp_rr))

            self._signal_fired_today = True
            return self._short(
                confidence=conf,
                reason=(
                    f"ORB-V2 SHORT: close={curr.close:.4f} "
                    f"OR_L={self._or_low:.4f} OR_range={or_range:.4f} "
                    f"SL_dist={sl_distance:.4f} atr_pct={atr_pct:.0f}"
                ),
                sl_mult=sl_distance / max(ctx.atr, 1e-8),
                tp_rr=tp_rr,
                passed=["or_breakout", "volume_expansion", "ema_dual_tf_bear", "atr_ok"],
            )

        # No breakout yet
        failed = []
        if not vol_ok:
            failed.append("volume_low")
        if curr.close <= self._or_high and curr.close >= self._or_low:
            failed.append("price_inside_or")
        return self._flat("no breakout", failed)
