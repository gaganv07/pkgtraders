"""
app/order_flow.py — Institutional Order Flow Engine

Computes on every tick:
  - Tick imbalance, velocity, acceleration
  - Buy/sell pressure (0-100)
  - Rolling cumulative delta approximation
  - Aggressive buyer/seller ratio
  - Participation rate
  - Order flow score (0-100)

Updated on every incoming tick — no bar dependency.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from app.market_data import Tick

logger = logging.getLogger(__name__)


@dataclass
class OFSnapshot:
    timestamp: datetime

    # Delta
    cvd:           float = 0.0   # rolling cumulative volume delta
    delta_fast:    float = 0.0   # delta over last N ticks

    # Pressure (0-100, 50=neutral)
    buy_pressure:  float = 50.0
    sell_pressure: float = 50.0

    # Aggressors (0-1)
    agg_buy_ratio:  float = 0.5
    agg_sell_ratio: float = 0.5

    # Tick metrics
    tick_imbalance:   float = 0.0   # -100..+100
    tick_velocity:    float = 0.0   # price units per tick
    tick_acceleration: float = 0.0  # change in velocity

    # Volume
    participation_rate: float = 0.5   # current vol vs average
    volume_expansion:   bool  = False

    # Composite
    of_score:   float = 50.0
    direction:  str   = "NEUTRAL"  # STRONG_BUY|BUY|NEUTRAL|SELL|STRONG_SELL


class OrderFlowEngine:
    """
    Full institutional order flow computation from raw tick stream.

    Tick classification:
      mid > prev  →  +1 (aggressive buy)
      mid < prev  →  -1 (aggressive sell)
      mid == prev →   0 (neutral / passive)

    CVD = rolling Σ(classified_volume × classification)
    """

    _FAST  = 30    # fast window (ticks)
    _MED   = 100   # medium window
    _SLOW  = 300   # slow window

    def __init__(self):
        self._ticks:   Deque[Tick]  = deque(maxlen=self._SLOW)
        self._class:   Deque[int]   = deque(maxlen=self._SLOW)  # +1, -1, 0
        self._buy_vol: Deque[int]   = deque(maxlen=self._SLOW)
        self._sell_vol:Deque[int]   = deque(maxlen=self._SLOW)
        self._prices:  Deque[float] = deque(maxlen=self._SLOW)
        self._vel_hist:Deque[float] = deque(maxlen=60)
        self._imb_hist:Deque[float] = deque(maxlen=60)

        self._cvd:    float = 0.0
        self._prev:   Optional[float] = None
        self._latest: Optional[OFSnapshot] = None

    def process(self, tick: Tick) -> OFSnapshot:
        self._ticks.append(tick)
        self._prices.append(tick.mid)

        # Classify
        cls = self._classify(tick)
        self._class.append(cls)

        vol = max(tick.volume, 1)
        if cls > 0:
            self._buy_vol.append(vol)
            self._sell_vol.append(0)
        elif cls < 0:
            self._buy_vol.append(0)
            self._sell_vol.append(vol)
        else:
            half = vol // 2
            self._buy_vol.append(half)
            self._sell_vol.append(vol - half)

        # CVD
        self._cvd += cls * vol
        self._prev = tick.mid

        snap = self._compute(tick)
        self._latest = snap
        return snap

    def _classify(self, tick: Tick) -> int:
        if self._prev is None:
            return 0
        diff = tick.mid - self._prev
        if diff > 0.005:
            return 1
        if diff < -0.005:
            return -1
        # Flat: use ask proximity
        sp = tick.spread
        if sp > 0:
            prox = (tick.ask - tick.mid) / sp
            if prox < 0.35:
                return 1
            if prox > 0.65:
                return -1
        return 0

    def _compute(self, tick: Tick) -> OFSnapshot:
        cls    = list(self._class)
        bv     = list(self._buy_vol)
        sv     = list(self._sell_vol)
        prices = list(self._prices)

        fast_cls  = cls[-self._FAST:]
        med_cls   = cls[-100:]

        # ── Pressure ──────────────────────────────────────────────
        n = len(fast_cls) or 1
        buys   = sum(1 for c in fast_cls if c > 0)
        sells  = sum(1 for c in fast_cls if c < 0)
        buy_pressure  = buys  / n * 100
        sell_pressure = sells / n * 100

        # ── Tick imbalance ────────────────────────────────────────
        tick_imbalance = (buys - sells) / n * 100
        self._imb_hist.append(tick_imbalance)

        # ── Aggressive ratios ─────────────────────────────────────
        total_bv = sum(bv[-self._FAST:])
        total_sv = sum(sv[-self._FAST:])
        total_v  = total_bv + total_sv or 1
        agg_buy  = total_bv / total_v
        agg_sell = total_sv / total_v

        # ── Fast delta ────────────────────────────────────────────
        delta_fast = sum(
            (b - s) for b, s in zip(bv[-self._FAST:], sv[-self._FAST:])
        )

        # ── Velocity ──────────────────────────────────────────────
        tick_velocity = 0.0
        if len(prices) >= 10:
            tick_velocity = prices[-1] - prices[-10]
        self._vel_hist.append(tick_velocity)

        # ── Acceleration ──────────────────────────────────────────
        tick_acceleration = 0.0
        if len(self._vel_hist) >= 10:
            vl = list(self._vel_hist)
            tick_acceleration = vl[-1] - statistics.mean(vl[-10:-1])

        # ── Participation ─────────────────────────────────────────
        all_vols = [b + s for b, s in zip(bv, sv) if b + s > 0]
        avg_vol  = statistics.mean(all_vols) if all_vols else 1
        curr_vol = total_bv + total_sv
        participation = curr_vol / avg_vol if avg_vol > 0 else 1.0
        volume_expansion = participation > 1.8

        # ── Composite score ───────────────────────────────────────
        # Blend: imbalance 35%, aggressor ratio 30%, vel/accel 25%, participation 10%
        imb_norm  = (tick_imbalance + 100) / 2          # 0..100
        ratio_s   = agg_buy * 100                        # 0..100
        vel_n     = min(max((tick_velocity * 10 + 50), 0), 100)
        accel_n   = min(max((tick_acceleration * 5 + 50), 0), 100)
        part_s    = min(participation * 50, 80)

        of_score = (
            imb_norm  * 0.35 +
            ratio_s   * 0.30 +
            (vel_n * 0.5 + accel_n * 0.5) * 0.25 +
            part_s    * 0.10
        )
        of_score = round(min(100.0, max(0.0, of_score)), 1)

        # ── Direction ─────────────────────────────────────────────
        if of_score >= 75:   direction = "STRONG_BUY"
        elif of_score >= 60: direction = "BUY"
        elif of_score <= 25: direction = "STRONG_SELL"
        elif of_score <= 40: direction = "SELL"
        else:                direction = "NEUTRAL"

        return OFSnapshot(
            timestamp=tick.time,
            cvd=self._cvd,
            delta_fast=delta_fast,
            buy_pressure=round(buy_pressure, 1),
            sell_pressure=round(sell_pressure, 1),
            agg_buy_ratio=round(agg_buy, 4),
            agg_sell_ratio=round(agg_sell, 4),
            tick_imbalance=round(tick_imbalance, 2),
            tick_velocity=round(tick_velocity, 5),
            tick_acceleration=round(tick_acceleration, 5),
            participation_rate=round(participation, 3),
            volume_expansion=volume_expansion,
            of_score=of_score,
            direction=direction,
        )

    def of_score(self) -> float:
        return self._latest.of_score if self._latest else 50.0

    def reset_cvd(self) -> None:
        self._cvd = 0.0
        if self._latest is not None:
            self._latest.cvd = 0.0

    @property
    def latest(self) -> Optional[OFSnapshot]:
        return self._latest

    def snapshot_dict(self) -> Dict:
        s = self._latest
        if s is None:
            return {}
        return {
            "cvd":            round(s.cvd, 1),
            "of_score":       s.of_score,
            "direction":      s.direction,
            "buy_pressure":   s.buy_pressure,
            "sell_pressure":  s.sell_pressure,
            "agg_buy":        s.agg_buy_ratio,
            "agg_sell":       s.agg_sell_ratio,
            "tick_imb":       s.tick_imbalance,
            "tick_vel":       s.tick_velocity,
            "tick_accel":     s.tick_acceleration,
            "vol_expansion":  s.volume_expansion,
            "participation":  s.participation_rate,
        }
