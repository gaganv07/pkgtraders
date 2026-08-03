"""
app/volume_analytics.py — Volume Analytics Engine

Computes:
  - Relative volume (current vs rolling average)
  - Volume expansion / contraction
  - Volume spike detection
  - Volume profile approximation (price × volume histogram)
  - Delta approximation (buy vol - sell vol)
  - Participation rate
  - Volume-weighted directional bias
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

from app.market_data import Bar, Tick

logger = logging.getLogger(__name__)


@dataclass
class VolumeSnapshot:
    timestamp: datetime

    # Relative volume
    current_volume:   float = 0.0
    avg_volume:       float = 0.0
    relative_vol:     float = 1.0    # current / average

    # Regime
    expansion:        bool  = False
    contraction:      bool  = False
    spike:            bool  = False
    spike_multiplier: float = 1.0

    # Delta
    delta:            float = 0.0    # buy_vol - sell_vol (approximated)
    cum_delta:        float = 0.0
    delta_divergence: bool  = False  # price up but delta down (or vice versa)

    # Participation
    participation_rate: float = 1.0  # vs session average

    # Directional bias from volume
    vol_bull_bias: float = 0.5   # 0-1
    vol_score:     float = 50.0  # 0-100


@dataclass
class VolumeProfileLevel:
    price:   float
    volume:  float
    buy_vol: float
    sell_vol: float

    @property
    def delta(self) -> float:
        return self.buy_vol - self.sell_vol

    @property
    def is_poc(self) -> bool:
        """Point of Control flag (set externally)."""
        return False


class VolumeAnalytics:
    """
    Tick-based volume analytics engine.
    Approximates buy/sell split from price direction.
    Builds a rolling volume profile.
    """

    _WINDOW      = 200   # bars for avg volume
    _SPIKE_MULT  = 2.5   # N× avg = spike
    _EXP_MULT    = 1.6
    _CON_MULT    = 0.5
    _PROFILE_BUCKETS = 50

    def __init__(self):
        self._bar_vols:   Deque[float] = deque(maxlen=self._WINDOW)
        self._tick_vols:  Deque[int]   = deque(maxlen=500)
        self._buy_vols:   Deque[float] = deque(maxlen=500)
        self._sell_vols:  Deque[float] = deque(maxlen=500)
        self._cum_delta:  float = 0.0
        self._price_hist: Deque[float] = deque(maxlen=200)
        self._delta_hist: Deque[float] = deque(maxlen=50)

        # Profile: {price_bucket: VolumeProfileLevel}
        self._profile: Dict[float, VolumeProfileLevel] = {}
        self._poc:     Optional[float] = None   # point of control

        self._session_avg_vol: float = 0.0
        self._latest: Optional[VolumeSnapshot] = None

    def process_tick(self, tick: Tick, prev_mid: Optional[float]) -> None:
        """Ingest a tick for real-time delta tracking."""
        vol = max(tick.volume, 1)
        self._tick_vols.append(vol)
        self._price_hist.append(tick.mid)

        # Classify volume side
        if prev_mid is not None:
            if tick.mid > prev_mid + 0.005:
                bv, sv = float(vol), 0.0
            elif tick.mid < prev_mid - 0.005:
                bv, sv = 0.0, float(vol)
            else:
                bv = sv = vol / 2.0
        else:
            bv = sv = vol / 2.0

        self._buy_vols.append(bv)
        self._sell_vols.append(sv)

        delta = bv - sv
        self._cum_delta += delta
        self._delta_hist.append(delta)

        # Update profile
        bucket = round(tick.mid * 2) / 2.0   # $0.50 buckets
        if bucket not in self._profile:
            self._profile[bucket] = VolumeProfileLevel(
                price=bucket, volume=0, buy_vol=0, sell_vol=0
            )
        self._profile[bucket].volume   += vol
        self._profile[bucket].buy_vol  += bv
        self._profile[bucket].sell_vol += sv

        # Trim profile to last 10k buckets
        if len(self._profile) > 500:
            oldest = sorted(self._profile)[:100]
            for k in oldest:
                del self._profile[k]

    def process_bar(self, bar: Bar) -> VolumeSnapshot:
        """Process a closed bar for volume regime analysis."""
        tv = float(bar.tick_vol)
        self._bar_vols.append(tv)

        avg = statistics.mean(self._bar_vols) if self._bar_vols else tv

        # Taker buy/sell split from bar (if real_vol = 0, use tick direction)
        buy_est  = tv * 0.5
        sell_est = tv * 0.5
        if bar.is_bull:
            buy_est  = tv * 0.65
            sell_est = tv * 0.35
        elif bar.is_bear:
            buy_est  = tv * 0.35
            sell_est = tv * 0.65

        delta = buy_est - sell_est
        self._cum_delta += delta
        self._delta_hist.append(delta)
        self._buy_vols.append(buy_est)
        self._sell_vols.append(sell_est)

        rel_vol     = tv / avg if avg > 0 else 1.0
        expansion   = rel_vol >= self._EXP_MULT
        contraction = rel_vol <= self._CON_MULT
        spike       = rel_vol >= self._SPIKE_MULT

        # Delta divergence: price direction ≠ delta direction
        price_up = bar.is_bull
        delta_pos = delta > 0
        divergence = price_up != delta_pos

        # Participation
        part = rel_vol  # simplified

        # Vol bias
        bv_fast = sum(list(self._buy_vols)[-20:])
        sv_fast = sum(list(self._sell_vols)[-20:])
        total_v = bv_fast + sv_fast or 1
        vol_bull_bias = bv_fast / total_v

        # Score
        score = 50.0
        if expansion:       score += 15.0
        if spike:           score += 10.0
        if not contraction: score += 5.0
        if vol_bull_bias > 0.60: score += 10.0
        elif vol_bull_bias < 0.40: score -= 10.0
        if divergence:      score -= 8.0

        snap = VolumeSnapshot(
            timestamp=bar.time,
            current_volume=tv,
            avg_volume=avg,
            relative_vol=round(rel_vol, 2),
            expansion=expansion,
            contraction=contraction,
            spike=spike,
            spike_multiplier=round(rel_vol, 2),
            delta=round(delta, 1),
            cum_delta=round(self._cum_delta, 1),
            delta_divergence=divergence,
            participation_rate=round(part, 2),
            vol_bull_bias=round(vol_bull_bias, 3),
            vol_score=round(min(100.0, max(0.0, score)), 1),
        )
        self._latest = snap

        # Update POC
        self._update_poc()
        return snap

    def _update_poc(self) -> None:
        if self._profile:
            self._poc = max(self._profile, key=lambda k: self._profile[k].volume)

    def reset_session(self) -> None:
        """Call at start of each trading session."""
        self._cum_delta = 0.0
        self._profile.clear()
        self._poc = None
        self._bar_vols.clear()

    @property
    def latest(self) -> Optional[VolumeSnapshot]:
        return self._latest

    @property
    def cum_delta(self) -> float:
        return self._cum_delta

    @property
    def poc_price(self) -> Optional[float]:
        return self._poc

    def get_profile(self, top_n: int = 20) -> List[VolumeProfileLevel]:
        """Return top N levels by volume (sorted desc)."""
        levels = sorted(self._profile.values(), key=lambda x: -x.volume)
        return levels[:top_n]

    def vol_score(self) -> float:
        return self._latest.vol_score if self._latest else 50.0

    def snapshot_dict(self) -> Dict:
        s = self._latest
        if s is None:
            return {}
        return {
            "rel_vol":        s.relative_vol,
            "expansion":      s.expansion,
            "contraction":    s.contraction,
            "spike":          s.spike,
            "delta":          s.delta,
            "cum_delta":      s.cum_delta,
            "delta_diverge":  s.delta_divergence,
            "vol_bull_bias":  s.vol_bull_bias,
            "vol_score":      s.vol_score,
            "poc_price":      self._poc,
        }
