"""
app/microstructure.py — Market Microstructure Engine

Detects automatically:
  - Liquidity grabs / stop hunts
  - Fake breakouts
  - Break of structure (BOS) — bullish and bearish
  - Change of character (CHoCH)
  - Absorption patterns
  - Momentum ignition
  - Exhaustion signals
  - Failed auctions
  - Fair Value Gaps (FVG)
  - Reversal probability
  - Continuation probability
  - Swing highs / lows, support / resistance
  - Internal / external structure
  - Consolidation zones
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.market_data import Bar, TF_M5, TF_M15

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────

@dataclass
class SwingPoint:
    time:    datetime
    price:   float
    kind:    str     # "HIGH" | "LOW"
    tf:      int     = TF_M15
    broken:  bool    = False
    strength: int    = 1   # confirmation bars each side


@dataclass
class FairValueGap:
    """Three-candle imbalance zone."""
    time:       datetime
    low:        float
    high:       float
    direction:  str    # "BULL" | "BEAR"
    filled:     bool   = False
    fill_pct:   float  = 0.0


@dataclass
class StructureLevel:
    price:     float
    kind:      str    # "SUPPORT" | "RESISTANCE"
    touches:   int    = 1
    strength:  float  = 1.0
    last_touch: Optional[datetime] = None


@dataclass
class MicrostructureState:
    # ── Structure ─────────────────────────────────────────────────
    trend:           str = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    structure_bias:  str = "NEUTRAL"   # from HH/HL or LH/LL

    # ── BOS / CHoCH ───────────────────────────────────────────────
    bos_bull:  bool = False
    bos_bear:  bool = False
    choch_bull: bool = False
    choch_bear: bool = False

    # ── Microstructure events (per-bar) ───────────────────────────
    liq_grab_up:   bool = False   # swept highs (sell setup)
    liq_grab_down: bool = False   # swept lows (buy setup)
    fake_break_up:   bool = False
    fake_break_down: bool = False
    absorption_bull: bool = False
    absorption_bear: bool = False
    momentum_ignition_bull: bool = False
    momentum_ignition_bear: bool = False
    exhaustion_bull: bool = False
    exhaustion_bear: bool = False
    failed_auction:  bool = False

    # ── FVGs ─────────────────────────────────────────────────────
    active_fvgs: List[FairValueGap] = field(default_factory=list)
    price_in_bull_fvg: bool = False
    price_in_bear_fvg: bool = False

    # ── Swing references ──────────────────────────────────────────
    last_swing_high: Optional[SwingPoint] = None
    last_swing_low:  Optional[SwingPoint] = None
    prev_swing_high: Optional[SwingPoint] = None
    prev_swing_low:  Optional[SwingPoint] = None

    # ── S/R ───────────────────────────────────────────────────────
    at_support:    bool = False
    at_resistance: bool = False
    support_levels:     List[StructureLevel] = field(default_factory=list)
    resistance_levels:  List[StructureLevel] = field(default_factory=list)

    # ── Probability scores ────────────────────────────────────────
    reversal_prob:     float = 0.5
    continuation_prob: float = 0.5

    # ── Consolidation ─────────────────────────────────────────────
    consolidating: bool = False

    # ── Composite scores ──────────────────────────────────────────
    bull_ms_score: float = 50.0
    bear_ms_score: float = 50.0


class MicrostructureEngine:
    """
    Stateful engine for full market microstructure analysis.
    Primary: M15.  Refinement: M5.
    """

    _LB      = 5    # swing lookback (each side)
    _MAX_SR  = 8    # max S/R levels
    _FVG_MAX = 10   # max tracked FVGs
    _CLUSTER = 0.50  # XAUUSD S/R clustering tolerance ($)
    _CONSOL_RATIO = 0.40  # range < N× ATR = consolidating

    def __init__(self):
        self._swings:     List[SwingPoint]     = []
        self._support:    List[StructureLevel] = []
        self._resistance: List[StructureLevel] = []
        self._fvgs:       List[FairValueGap]   = []
        self._state = MicrostructureState()
        self._prev_bos_high: Optional[float] = None
        self._prev_bos_low:  Optional[float] = None

    def analyse(self, bars: List[Bar], atr: Optional[float] = None) -> MicrostructureState:
        """Full analysis on M15 bar list."""
        if len(bars) < self._LB * 2 + 2:
            return self._state

        # Reset per-bar event flags
        s = self._state
        s.bos_bull = s.bos_bear = s.choch_bull = s.choch_bear = False
        s.liq_grab_up = s.liq_grab_down = False
        s.fake_break_up = s.fake_break_down = False
        s.absorption_bull = s.absorption_bear = False
        s.momentum_ignition_bull = s.momentum_ignition_bear = False
        s.exhaustion_bull = s.exhaustion_bear = False
        s.failed_auction  = False
        s.price_in_bull_fvg = s.price_in_bear_fvg = False

        self._detect_swings(bars)
        self._build_sr_levels()
        self._detect_bos_choch(bars[-1])
        self._detect_microstructure(bars, atr)
        self._detect_fvgs(bars)
        self._update_fvg_state(bars[-1].close)
        self._check_sr_proximity(bars[-1].close, atr)
        self._detect_consolidation(bars, atr)
        self._compute_probabilities()
        self._compute_scores()

        return self._state

    # ── Swing detection ───────────────────────────────────────────

    def _detect_swings(self, bars: List[Bar]) -> None:
        lb = self._LB
        new_swings: List[SwingPoint] = []

        for i in range(lb, len(bars) - lb):
            b = bars[i]
            window_h = bars[i - lb: i + lb + 1]
            window_l = bars[i - lb: i + lb + 1]

            if b.high == max(x.high for x in window_h):
                new_swings.append(SwingPoint(b.time, b.high, "HIGH", strength=lb))
            if b.low == min(x.low  for x in window_l):
                new_swings.append(SwingPoint(b.time, b.low,  "LOW",  strength=lb))

        self._swings = sorted(new_swings, key=lambda x: x.time)[-50:]

        highs = [x for x in self._swings if x.kind == "HIGH"]
        lows  = [x for x in self._swings if x.kind == "LOW"]

        s = self._state
        if len(highs) >= 2:
            s.prev_swing_high = highs[-2]
            s.last_swing_high = highs[-1]
        elif len(highs) == 1:
            s.last_swing_high = highs[-1]

        if len(lows) >= 2:
            s.prev_swing_low = lows[-2]
            s.last_swing_low = lows[-1]
        elif len(lows) == 1:
            s.last_swing_low = lows[-1]

        # Structure bias
        if (s.last_swing_high and s.prev_swing_high and
                s.last_swing_low and s.prev_swing_low):
            hh = s.last_swing_high.price > s.prev_swing_high.price
            hl = s.last_swing_low.price  > s.prev_swing_low.price
            lh = s.last_swing_high.price < s.prev_swing_high.price
            ll = s.last_swing_low.price  < s.prev_swing_low.price

            if hh and hl:   s.structure_bias = "BULLISH"
            elif lh and ll: s.structure_bias = "BEARISH"
            else:           s.structure_bias = "NEUTRAL"

    # ── S/R levels ────────────────────────────────────────────────

    def _build_sr_levels(self) -> None:
        new_s: List[StructureLevel] = []
        new_r: List[StructureLevel] = []

        for sw in self._swings[-30:]:
            if sw.kind == "LOW":
                target = new_s
                kind   = "SUPPORT"
            else:
                target = new_r
                kind   = "RESISTANCE"

            clustered = False
            for lvl in target:
                if abs(lvl.price - sw.price) <= self._CLUSTER:
                    lvl.touches += 1
                    lvl.strength = min(3.0, lvl.strength + 0.4)
                    lvl.last_touch = sw.time
                    clustered = True
                    break
            if not clustered:
                target.append(StructureLevel(price=sw.price, kind=kind,
                                             touches=1, last_touch=sw.time))

        self._support    = sorted(new_s, key=lambda x: -x.strength)[:self._MAX_SR]
        self._resistance = sorted(new_r, key=lambda x: -x.strength)[:self._MAX_SR]
        self._state.support_levels    = self._support
        self._state.resistance_levels = self._resistance

    # ── BOS / CHoCH ───────────────────────────────────────────────

    def _detect_bos_choch(self, bar: Bar) -> None:
        s  = self._state
        lh = s.last_swing_high
        ll = s.last_swing_low

        if lh and bar.close > lh.price:
            if s.structure_bias == "BEARISH":
                s.choch_bull = True
            else:
                s.bos_bull = True
            self._prev_bos_high = lh.price
            s.trend = "BULLISH"

        if ll and bar.close < ll.price:
            if s.structure_bias == "BULLISH":
                s.choch_bear = True
            else:
                s.bos_bear = True
            self._prev_bos_low = ll.price
            s.trend = "BEARISH"

    # ── Microstructure events ─────────────────────────────────────

    def _detect_microstructure(self, bars: List[Bar],
                                atr: Optional[float]) -> None:
        if len(bars) < 4:
            return
        c  = bars[-1]
        p  = bars[-2]
        pp = bars[-3]
        s  = self._state

        atr_ref = atr or 1.5

        # ── Liquidity grab (stop hunt): spike through high/low then retrace ──
        prior_high = max(pp.high, p.high)
        prior_low  = min(pp.low,  p.low)

        if (c.high > prior_high + atr_ref * 0.15 and
                c.close < prior_high - atr_ref * 0.05):
            s.liq_grab_up = True    # swept highs → bearish reversal setup

        if (c.low < prior_low - atr_ref * 0.15 and
                c.close > prior_low + atr_ref * 0.05):
            s.liq_grab_down = True  # swept lows → bullish reversal setup

        # ── Fake breakout ─────────────────────────────────────────
        if self._prev_bos_high and c.high > self._prev_bos_high:
            if c.close < self._prev_bos_high:
                s.fake_break_up = True
        if self._prev_bos_low and c.low < self._prev_bos_low:
            if c.close > self._prev_bos_low:
                s.fake_break_down = True

        # ── Absorption: large-range bar that barely moves price ───
        large_range   = c.range > atr_ref * 1.8
        small_net_move = abs(c.close - c.open) < c.range * 0.25
        if large_range and small_net_move:
            if c.close > c.open:
                s.absorption_bull = True
            else:
                s.absorption_bear = True

        # ── Momentum ignition: accelerating move with volume surge ─
        if len(bars) >= 5:
            ranges = [bars[-i].range for i in range(1, 5)]
            if c.range > statistics.mean(ranges) * 2.0:
                if c.is_bull:
                    s.momentum_ignition_bull = True
                else:
                    s.momentum_ignition_bear = True

        # ── Exhaustion: extended move + decreasing bar ranges ─────
        if len(bars) >= 6:
            rng_list = [bars[-i].range for i in range(1, 6)]
            avg_rng  = statistics.mean(rng_list[1:])
            if rng_list[0] < avg_rng * 0.4:
                last_5_bull = sum(1 for b in bars[-5:] if b.is_bull)
                last_5_bear = sum(1 for b in bars[-5:] if b.is_bear)
                if last_5_bull >= 4:
                    s.exhaustion_bull = True
                if last_5_bear >= 4:
                    s.exhaustion_bear = True

        # ── Failed auction: price rejected aggressively at level ──
        if s.at_resistance and c.close < p.low:
            s.failed_auction = True
        if s.at_support and c.close > p.high:
            s.failed_auction = True

    # ── Fair Value Gaps ───────────────────────────────────────────

    def _detect_fvgs(self, bars: List[Bar]) -> None:
        if len(bars) < 3:
            return

        for i in range(2, len(bars)):
            b1 = bars[i - 2]
            b2 = bars[i - 1]  # middle (impulse)
            b3 = bars[i]

            # Bullish FVG: gap between b1.high and b3.low
            if b3.low > b1.high and b2.is_bull:
                fvg = FairValueGap(
                    time=b3.time, low=b1.high, high=b3.low, direction="BULL"
                )
                # Avoid duplicates
                if not any(abs(f.low - fvg.low) < 0.05 for f in self._fvgs):
                    self._fvgs.append(fvg)

            # Bearish FVG: gap between b3.high and b1.low
            if b3.high < b1.low and b2.is_bear:
                fvg = FairValueGap(
                    time=b3.time, low=b3.high, high=b1.low, direction="BEAR"
                )
                if not any(abs(f.low - fvg.low) < 0.05 for f in self._fvgs):
                    self._fvgs.append(fvg)

        # Keep only recent FVGs
        self._fvgs = [f for f in self._fvgs if not f.filled][-self._FVG_MAX:]
        self._state.active_fvgs = self._fvgs

    def _update_fvg_state(self, price: float) -> None:
        s = self._state
        for fvg in self._fvgs:
            if fvg.low <= price <= fvg.high:
                if fvg.direction == "BULL":
                    s.price_in_bull_fvg = True
                else:
                    s.price_in_bear_fvg = True
                # Compute fill %
                fvg.fill_pct = (price - fvg.low) / (fvg.high - fvg.low) * 100
                if fvg.fill_pct >= 95:
                    fvg.filled = True

    # ── S/R proximity ─────────────────────────────────────────────

    def _check_sr_proximity(self, price: float, atr: Optional[float]) -> None:
        tol = (atr or 1.5) * 0.6
        s   = self._state
        s.at_support    = any(abs(price - l.price) <= tol for l in self._support)
        s.at_resistance = any(abs(price - l.price) <= tol for l in self._resistance)

    # ── Consolidation ─────────────────────────────────────────────

    def _detect_consolidation(self, bars: List[Bar], atr: Optional[float]) -> None:
        if len(bars) < 10 or not atr:
            return
        recent_range = (max(b.high for b in bars[-10:])
                        - min(b.low  for b in bars[-10:]))
        self._state.consolidating = recent_range < atr * self._CONSOL_RATIO * 10

    # ── Probabilities ─────────────────────────────────────────────

    def _compute_probabilities(self) -> None:
        s  = self._state
        rv = 0.5
        cv = 0.5

        # Reversal signals
        rev_signals = [
            s.liq_grab_up, s.liq_grab_down,
            s.fake_break_up, s.fake_break_down,
            s.choch_bull, s.choch_bear,
            s.absorption_bull, s.absorption_bear,
            s.exhaustion_bull, s.exhaustion_bear,
            s.failed_auction,
        ]
        con_signals = [
            s.bos_bull, s.bos_bear,
            s.momentum_ignition_bull, s.momentum_ignition_bear,
        ]

        rv_count = sum(1 for r in rev_signals if r)
        cv_count = sum(1 for c in con_signals if c)

        rv = min(0.95, 0.5 + rv_count * 0.10)
        cv = min(0.95, 0.5 + cv_count * 0.12)

        # Mutually reduce
        if rv > cv:
            cv = max(0.1, cv - (rv - 0.5) * 0.5)
        elif cv > rv:
            rv = max(0.1, rv - (cv - 0.5) * 0.5)

        s.reversal_prob     = round(rv, 3)
        s.continuation_prob = round(cv, 3)

    # ── Composite scores ──────────────────────────────────────────

    def _compute_scores(self) -> None:
        s = self._state
        bull = 50.0
        bear = 50.0

        if s.structure_bias == "BULLISH": bull += 15
        elif s.structure_bias == "BEARISH": bear += 15

        if s.trend == "BULLISH": bull += 10
        elif s.trend == "BEARISH": bear += 10

        if s.bos_bull:   bull += 12
        if s.choch_bull: bull += 18
        if s.bos_bear:   bear += 12
        if s.choch_bear: bear += 18

        if s.liq_grab_down:   bull += 14  # swept lows = buy setup
        if s.liq_grab_up:     bear += 14  # swept highs = sell setup
        if s.absorption_bull: bull += 10
        if s.absorption_bear: bear += 10
        if s.exhaustion_bear: bull += 12
        if s.exhaustion_bull: bear += 12
        if s.momentum_ignition_bull: bull += 8
        if s.momentum_ignition_bear: bear += 8

        if s.at_support:    bull += 10
        if s.at_resistance: bear += 10

        if s.price_in_bull_fvg: bull += 8
        if s.price_in_bear_fvg: bear += 8

        s.bull_ms_score = round(min(100.0, bull), 1)
        s.bear_ms_score = round(min(100.0, bear), 1)

    def state(self) -> MicrostructureState:
        return self._state

    def snapshot_dict(self) -> Dict:
        s = self._state
        return {
            "trend":          s.trend,
            "structure_bias": s.structure_bias,
            "bos_bull":       s.bos_bull,
            "bos_bear":       s.bos_bear,
            "choch_bull":     s.choch_bull,
            "choch_bear":     s.choch_bear,
            "liq_grab_up":    s.liq_grab_up,
            "liq_grab_down":  s.liq_grab_down,
            "fake_break_up":  s.fake_break_up,
            "fake_break_down": s.fake_break_down,
            "absorption_bull": s.absorption_bull,
            "absorption_bear": s.absorption_bear,
            "exhaustion_bull": s.exhaustion_bull,
            "exhaustion_bear": s.exhaustion_bear,
            "momentum_ig_bull": s.momentum_ignition_bull,
            "momentum_ig_bear": s.momentum_ignition_bear,
            "failed_auction":  s.failed_auction,
            "at_support":     s.at_support,
            "at_resistance":  s.at_resistance,
            "bull_fvg":       s.price_in_bull_fvg,
            "bear_fvg":       s.price_in_bear_fvg,
            "reversal_prob":  s.reversal_prob,
            "continuation_prob": s.continuation_prob,
            "consolidating":  s.consolidating,
            "bull_ms_score":  s.bull_ms_score,
            "bear_ms_score":  s.bear_ms_score,
            "active_fvgs":    len(s.active_fvgs),
        }
