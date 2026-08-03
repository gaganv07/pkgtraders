"""
P1 — Market Auction Theory (MAT)
=================================
Value Area + Point of Control from rolling Volume Profile.

Entry logic:
  - Build a 12-hour (48×M15) rolling volume profile using tick volume as proxy.
  - Compute POC, VAH, VAL  (Value Area = 70% of total volume around POC).
  - LONG  : Price dips below VAL then closes back inside the Value Area.
  - SHORT : Price spikes above VAH then closes back inside the Value Area.
  - Confidence scales with distance from POC (deeper rejection = stronger signal).

SL: 0.5×ATR beyond the rejected VA edge.
TP: POC level (implicit R:R depends on distance from entry to POC).
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from strategies.base import BaseStrategy
from strategies.context import StrategyContext
from strategies.signal import StrategySignal

logger = logging.getLogger(__name__)


class MarketAuctionStrategy(BaseStrategy):
    name    = "P1_MarketAuction"
    version = "1.0"

    default_sl_atr_mult = 0.5
    default_tp_rr       = 2.0      # entry→POC defines actual target; this is fallback

    # Rolling window: 48 × M15 = 12 hours
    _PROFILE_BARS = 48
    # Value Area = 70% of total volume
    _VA_PCT = 0.70
    # Minimum VA width as fraction of ATR (filters micro-range days)
    _MIN_VA_ATR_RATIO = 0.5

    def __init__(self):
        super().__init__()
        self._bar_buf: Deque = deque(maxlen=self._PROFILE_BARS + 5)
        self._poc:  Optional[float] = None
        self._vah:  Optional[float] = None
        self._val:  Optional[float] = None
        self._prev_below_val: bool  = False
        self._prev_above_vah: bool  = False

    # ── Volume Profile ────────────────────────────────────────────────────────

    def _build_profile(self, bars) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (POC, VAH, VAL) from bar sequence, or (None, None, None)."""
        if len(bars) < 10:
            return None, None, None

        # Price grid: 100 buckets spanning the bar range
        lo = min(b.low  for b in bars)
        hi = max(b.high for b in bars)
        if hi <= lo:
            return None, None, None

        n_buckets = 100
        bucket_sz = (hi - lo) / n_buckets
        vol_at: Dict[int, float] = {i: 0.0 for i in range(n_buckets)}

        for b in bars:
            bar_lo_i = int((b.low  - lo) / bucket_sz)
            bar_hi_i = int((b.high - lo) / bucket_sz)
            bar_hi_i = min(bar_hi_i, n_buckets - 1)
            bar_lo_i = max(bar_lo_i, 0)
            span = max(bar_hi_i - bar_lo_i + 1, 1)
            v_per_bucket = max(b.tick_vol, 1) / span
            for i in range(bar_lo_i, bar_hi_i + 1):
                vol_at[i] = vol_at.get(i, 0.0) + v_per_bucket

        total_vol = sum(vol_at.values()) or 1.0
        poc_i = max(vol_at, key=lambda i: vol_at[i])
        poc_price = lo + (poc_i + 0.5) * bucket_sz

        # Expand from POC until VA_PCT captured
        target = total_vol * self._VA_PCT
        cum    = vol_at[poc_i]
        lo_i, hi_i = poc_i, poc_i

        while cum < target:
            expand_lo = lo_i > 0 and vol_at.get(lo_i - 1, 0) >= vol_at.get(hi_i + 1, 0)
            expand_hi = hi_i < n_buckets - 1 and not expand_lo

            if expand_lo:
                lo_i -= 1
                cum += vol_at.get(lo_i, 0.0)
            elif expand_hi:
                hi_i += 1
                cum += vol_at.get(hi_i, 0.0)
            elif lo_i > 0:
                lo_i -= 1
                cum += vol_at.get(lo_i, 0.0)
            elif hi_i < n_buckets - 1:
                hi_i += 1
                cum += vol_at.get(hi_i, 0.0)
            else:
                break

        vah = lo + (hi_i + 1) * bucket_sz
        val = lo + lo_i       * bucket_sz
        return poc_price, vah, val

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def on_bar(self, ctx: StrategyContext) -> None:
        if ctx.bars_m15:
            self._bar_buf.append(ctx.bars_m15[-1])
        bars = list(self._bar_buf)
        self._poc, self._vah, self._val = self._build_profile(bars)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        try:
            return self._evaluate(ctx)
        except Exception as e:
            logger.debug(f"{self.name}: error {e}")
            return self._flat(f"error: {e}")

    def _evaluate(self, ctx: StrategyContext) -> StrategySignal:
        if self._poc is None or self._vah is None or self._val is None:
            return self._flat("profile not ready", ["profile"])

        if ctx.atr <= 0:
            return self._flat("ATR not ready", ["atr"])

        va_width = self._vah - self._val
        if va_width < ctx.atr * self._MIN_VA_ATR_RATIO:
            return self._flat("VA too narrow", ["va_width"])

        price = ctx.price
        bars  = ctx.bars_m15

        if not bars:
            return self._flat("no bars")

        prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
        curr_bar = bars[-1]

        # ── LONG: prev bar dipped below VAL, curr closes above VAL ───────────
        if prev_bar.low < self._val and curr_bar.close > self._val:
            dist_from_poc = abs(curr_bar.close - self._poc)
            # Deeper rejection from POC = higher confidence
            conf = min(90.0, 50.0 + (dist_from_poc / va_width) * 40.0)
            tp_rr = max(1.5, (self._poc - curr_bar.close) / (ctx.atr * self.default_sl_atr_mult))
            return self._long(
                confidence=conf,
                reason=f"VAL rejection: prev_low={prev_bar.low:.2f} VAL={self._val:.2f} POC={self._poc:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr),
                passed=["val_dip", "close_inside", "va_width"],
            )

        # ── SHORT: prev bar spiked above VAH, curr closes below VAH ──────────
        if prev_bar.high > self._vah and curr_bar.close < self._vah:
            dist_from_poc = abs(curr_bar.close - self._poc)
            conf = min(90.0, 50.0 + (dist_from_poc / va_width) * 40.0)
            tp_rr = max(1.5, (curr_bar.close - self._poc) / (ctx.atr * self.default_sl_atr_mult))
            return self._short(
                confidence=conf,
                reason=f"VAH rejection: prev_high={prev_bar.high:.2f} VAH={self._vah:.2f} POC={self._poc:.2f}",
                sl_mult=0.5, tp_rr=max(1.5, tp_rr),
                passed=["vah_spike", "close_inside", "va_width"],
            )

        return self._flat(f"price={price:.2f} VAL={self._val:.2f} VAH={self._vah:.2f}")
