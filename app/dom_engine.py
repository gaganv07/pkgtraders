"""
app/dom_engine.py — Depth of Market Engine

When DOM is available:
  - Total bid/ask volume, bid/ask imbalance
  - Liquidity concentration, walls, vacuums
  - Book slope, order book skew, price ladder pressure
  - Stacked bids/offers
  - Liquidity Score 0-100

When DOM is unavailable:
  - Tick-frequency estimation
  - Synthetic delta, liquidity, aggressive buyer/seller estimates
  - Tick clustering, velocity, acceleration, spread behaviour

Automatically selects the correct mode.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from app.mt5_client import DOMSnapshot
from app.market_data import Tick

logger = logging.getLogger(__name__)


# ── Snapshot outputs ──────────────────────────────────────────────

@dataclass
class DOMMetrics:
    """Full DOM-based liquidity metrics (when Level II available)."""
    timestamp:          datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Volume totals
    total_bid_vol:      float = 0.0
    total_ask_vol:      float = 0.0

    # Imbalance: +1 = all bids, -1 = all asks
    imbalance:          float = 0.0

    # Concentration: how evenly spread is the book
    bid_concentration:  float = 0.0
    ask_concentration:  float = 0.0

    # Walls (single level > N× average)
    buy_wall:           bool  = False
    buy_wall_price:     float = 0.0
    buy_wall_vol:       float = 0.0
    sell_wall:          bool  = False
    sell_wall_price:    float = 0.0
    sell_wall_vol:      float = 0.0

    # Vacuums (thin zones in book)
    bid_vacuum:         bool  = False
    ask_vacuum:         bool  = False
    vacuum_price:       float = 0.0

    # Slopes (gradient of volume vs price distance)
    bid_slope:          float = 0.0   # positive = volume builds away
    ask_slope:          float = 0.0

    # Book skew (which side is heavier in upper percentile)
    book_skew:          float = 0.0   # +1 bid-heavy, -1 ask-heavy

    # Price ladder pressure (top-5 levels)
    bid_ladder_pressure: float = 0.0
    ask_ladder_pressure: float = 0.0

    # Stacked levels (multiple consecutive large levels)
    stacked_bids:       bool  = False
    stacked_asks:       bool  = False

    # Final score
    liquidity_score:    float = 50.0

    dom_available:      bool  = True


@dataclass
class FallbackMetrics:
    """Synthetic order flow when DOM is unavailable."""
    timestamp:              datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    tick_frequency:         float = 0.0   # ticks per second
    tick_imbalance:         float = 0.0   # -100..+100
    tick_velocity:          float = 0.0   # rate of change of price
    tick_acceleration:      float = 0.0   # rate of change of velocity
    tick_clustering:        float = 0.0   # burstiness 0-1

    synthetic_delta:        float = 0.0
    aggressive_buy_est:     float = 0.5
    aggressive_sell_est:    float = 0.5

    volume_burst:           bool  = False
    spread_tightening:      bool  = False
    price_response:         float = 0.0   # price move per tick cluster

    liquidity_score:        float = 50.0
    dom_available:          bool  = False


# ── DOM Engine ────────────────────────────────────────────────────

class DOMEngine:
    """
    Dual-mode order book analyser.
    Automatically uses DOM when available, falls back to tick inference.
    """

    _WALL_MULT    = 3.5    # level volume > N× avg = wall
    _VACUUM_MULT  = 0.2    # level volume < N× avg = vacuum
    _STACK_COUNT  = 3      # consecutive large levels = stacked

    def __init__(self):
        self._dom_available = False
        self._tick_buf:    Deque[Tick]  = deque(maxlen=500)
        self._price_hist:  Deque[float] = deque(maxlen=100)
        self._vel_hist:    Deque[float] = deque(maxlen=50)
        self._imb_hist:    Deque[float] = deque(maxlen=80)
        self._vol_hist:    Deque[int]   = deque(maxlen=100)
        self._spread_hist: Deque[float] = deque(maxlen=50)
        self._ts_hist:     Deque[float] = deque(maxlen=200)  # arrival timestamps
        self._vol_sum:     float        = 0.0  # O(1) rolling sum of self._vol_hist

        self._latest_dom:      Optional[DOMMetrics]     = None
        self._latest_fallback: Optional[FallbackMetrics] = None

    # ── Primary interface ─────────────────────────────────────────

    def process(self, tick: Tick, dom_snap: DOMSnapshot,
                avg_spread: float) -> "DOMMetrics | FallbackMetrics":
        """
        Process a tick and optional DOM snapshot.
        Returns the most informative metrics available.
        """
        self._tick_buf.append(tick)
        self._price_hist.append(tick.mid)
        
        # Maintain self._vol_sum incrementally before appending to self._vol_hist
        if len(self._vol_hist) == self._vol_hist.maxlen:
            removed = self._vol_hist[0]
            self._vol_sum -= removed
        self._vol_hist.append(tick.volume)
        self._vol_sum += tick.volume
        
        self._spread_hist.append(tick.spread)
        self._ts_hist.append(tick.time.timestamp())

        if dom_snap.available and (dom_snap.bids or dom_snap.asks):
            self._dom_available = True
            result = self._analyse_dom(dom_snap, tick)
            self._latest_dom = result
            return result
        else:
            self._dom_available = False
            result = self._analyse_fallback(tick, avg_spread)
            self._latest_fallback = result
            return result

    # ── DOM analysis ─────────────────────────────────────────────

    def _analyse_dom(self, snap: DOMSnapshot, tick: Tick) -> DOMMetrics:
        m = DOMMetrics(timestamp=snap.timestamp)

        bids = snap.bids  # sorted desc
        asks = snap.asks  # sorted asc

        if not bids and not asks:
            return m

        # ── Totals ────────────────────────────────────────────────
        m.total_bid_vol = sum(l.volume for l in bids)
        m.total_ask_vol = sum(l.volume for l in asks)
        total = m.total_bid_vol + m.total_ask_vol or 1.0
        m.imbalance = (m.total_bid_vol - m.total_ask_vol) / total

        # Track imbalance history
        self._imb_hist.append(m.imbalance)

        # ── Concentration (Herfindahl-like) ───────────────────────
        if bids:
            b_shares = [l.volume / m.total_bid_vol for l in bids if m.total_bid_vol > 0]
            m.bid_concentration = sum(s ** 2 for s in b_shares)
        if asks:
            a_shares = [l.volume / m.total_ask_vol for l in asks if m.total_ask_vol > 0]
            m.ask_concentration = sum(s ** 2 for s in a_shares)

        # ── Walls ─────────────────────────────────────────────────
        all_vols = [l.volume for l in bids + asks]
        if all_vols:
            avg_vol = statistics.mean(all_vols)
            wall_thr = avg_vol * self._WALL_MULT
            vac_thr  = avg_vol * self._VACUUM_MULT

            # Best bid ± 5 levels for wall detection
            for lvl in bids[:6]:
                if lvl.volume >= wall_thr:
                    m.buy_wall = True
                    m.buy_wall_price = lvl.price
                    m.buy_wall_vol   = lvl.volume
                    break

            for lvl in asks[:6]:
                if lvl.volume >= wall_thr:
                    m.sell_wall = True
                    m.sell_wall_price = lvl.price
                    m.sell_wall_vol   = lvl.volume
                    break

            # Vacuums (thin liquidity zones)
            for lvl in bids[:10]:
                if lvl.volume < vac_thr:
                    m.bid_vacuum = True
                    m.vacuum_price = lvl.price
                    break
            for lvl in asks[:10]:
                if lvl.volume < vac_thr:
                    m.ask_vacuum = True
                    m.vacuum_price = lvl.price
                    break

            # Stacked levels
            big_bids = sum(1 for l in bids[:8] if l.volume >= avg_vol * 2)
            big_asks = sum(1 for l in asks[:8] if l.volume >= avg_vol * 2)
            m.stacked_bids = big_bids >= self._STACK_COUNT
            m.stacked_asks = big_asks >= self._STACK_COUNT

        # ── Slopes ────────────────────────────────────────────────
        if len(bids) >= 3:
            dists = [abs(bids[i].price - bids[0].price) for i in range(1, min(5, len(bids)))]
            vols  = [bids[i].volume for i in range(1, min(5, len(bids)))]
            if dists and any(d > 0 for d in dists):
                m.bid_slope = statistics.mean(
                    vols[i] / dists[i] for i in range(len(dists)) if dists[i] > 0
                )

        if len(asks) >= 3:
            dists = [abs(asks[i].price - asks[0].price) for i in range(1, min(5, len(asks)))]
            vols  = [asks[i].volume for i in range(1, min(5, len(asks)))]
            if dists and any(d > 0 for d in dists):
                m.ask_slope = statistics.mean(
                    vols[i] / dists[i] for i in range(len(dists)) if dists[i] > 0
                )

        # ── Book skew (top 25% of depth by volume) ────────────────
        top_bid_vol = sum(l.volume for l in bids[:max(1, len(bids)//4)])
        top_ask_vol = sum(l.volume for l in asks[:max(1, len(asks)//4)])
        top_total   = top_bid_vol + top_ask_vol or 1
        m.book_skew = (top_bid_vol - top_ask_vol) / top_total

        # ── Price ladder pressure (top 5 levels each side) ────────
        m.bid_ladder_pressure = sum(l.volume for l in bids[:5])
        m.ask_ladder_pressure = sum(l.volume for l in asks[:5])

        # ── Liquidity score ───────────────────────────────────────
        m.liquidity_score = self._score_dom(m, tick)
        return m

    def _score_dom(self, m: DOMMetrics, tick: Tick) -> float:
        score = 60.0

        # Imbalance — extreme either way means thin one side
        abs_imb = abs(m.imbalance)
        if abs_imb < 0.20:  score += 15.0
        elif abs_imb < 0.40: score += 8.0
        elif abs_imb > 0.70: score -= 12.0

        # Walls: nearby walls = support/resistance = good for direction
        if m.buy_wall or m.sell_wall:
            score += 8.0

        # Vacuums: thin zones = slippage risk
        if m.bid_vacuum or m.ask_vacuum:
            score -= 15.0

        # Stacked orders: institutional depth = good
        if m.stacked_bids or m.stacked_asks:
            score += 10.0

        # Skew alignment with spread
        # (not punished — skew is informational)

        return round(max(0.0, min(100.0, score)), 1)

    # ── Fallback: tick-based estimation ──────────────────────────

    def _analyse_fallback(self, tick: Tick, avg_spread: float) -> FallbackMetrics:
        # Avoid creating lists of the entire buffers or large historical scans.
        # This keeps the analysis O(1) or O(k) where k is a tiny fixed lookback (<= 50).
        m = FallbackMetrics(timestamp=tick.time)

        n_prices = len(self._price_hist)
        if n_prices < 5:
            return m

        # ── Tick frequency (O(1)) ─────────────────────────────────
        n_ts = len(self._ts_hist)
        if n_ts >= 10:
            window = self._ts_hist[-1] - self._ts_hist[-10]
            m.tick_frequency = 9.0 / window if window > 0 else 0.0

        # ── Tick velocity & acceleration (O(1)) ───────────────────
        velocity = self._price_hist[-1] - self._price_hist[-5]
        self._vel_hist.append(velocity)
        m.tick_velocity = velocity

        if len(self._vel_hist) >= 5:
            m.tick_acceleration = self._vel_hist[-1] - self._vel_hist[-5]

        # ── Tick imbalance: up vs down moves (O(k)) ───────────────
        up = 0
        down = 0
        limit = min(50, n_prices)
        for i in range(1, limit):
            diff = self._price_hist[-i] - self._price_hist[-i-1]
            if diff > 0:
                up += 1
            elif diff < 0:
                down += 1
        tot = up + down
        m.tick_imbalance = (up - down) / tot * 100.0 if tot > 0 else 0.0

        # ── Clustering: compare recent tick rate vs overall (O(1)) ─
        if n_ts >= 20:
            recent_diff = self._ts_hist[-1] - self._ts_hist[-5]
            overall_diff = self._ts_hist[-1] - self._ts_hist[0]
            recent_rate = 5.0 / recent_diff if recent_diff > 0.001 else 5.0 / 0.001
            overall_rate = n_ts / overall_diff if overall_diff > 0.001 else n_ts / 0.001
            m.tick_clustering = max(0.0, min(1.0, recent_rate / overall_rate - 1.0)) if overall_rate > 0.001 else 0.0

        # ── Synthetic delta from up/down tick volume (O(k)) ───────
        total_up = 0.0
        total_down = 0.0
        n_ticks = len(self._tick_buf)
        start = max(1, n_ticks - 49)
        for i in range(start, n_ticks):
            t_curr = self._tick_buf[i]
            t_prev = self._tick_buf[i-1]
            # Dataclass tick field access (.mid property computes mid price)
            if t_curr.mid > t_prev.mid:
                total_up += t_curr.volume
            elif t_curr.mid < t_prev.mid:
                total_down += t_curr.volume

        total_v = total_up + total_down
        if total_v > 0:
            m.aggressive_buy_est  = total_up / total_v
            m.aggressive_sell_est = total_down / total_v
        else:
            m.aggressive_buy_est  = 0.5
            m.aggressive_sell_est = 0.5
        m.synthetic_delta = total_up - total_down

        # ── Volume burst (O(1) using self._vol_sum cache) ─────────
        n_vols = len(self._vol_hist)
        if n_vols >= 20:
            recent_sum = sum(self._vol_hist[-i] for i in range(1, 6))
            recent_v = recent_sum / 5.0
            avg_sum = self._vol_sum - recent_sum
            if n_vols > 5:
                avg_v = avg_sum / (n_vols - 5)
            else:
                avg_v = 0.0
            m.volume_burst = recent_v > avg_v * 2.0 if avg_v > 0.0 else False

        # ── Spread tightening (O(1)) ──────────────────────────────
        n_spreads = len(self._spread_hist)
        if n_spreads >= 10 and avg_spread > 0:
            recent_spread_sum = sum(self._spread_hist[-i] for i in range(1, 6))
            m.spread_tightening = (recent_spread_sum / 5.0) < avg_spread * 0.85

        # ── Price response (O(1)) ─────────────────────────────────
        m.price_response = abs(self._price_hist[-1] - self._price_hist[-10]) if n_prices >= 10 else 0.0

        # ── Liquidity score ───────────────────────────────────────
        m.liquidity_score = self._score_fallback(m)
        return m

    def _score_fallback(self, m: FallbackMetrics) -> float:
        score = 50.0

        # High frequency = good liquidity
        if m.tick_frequency > 2.0:  score += 15.0
        elif m.tick_frequency > 0.5: score += 5.0

        # Volume burst = activity surge
        if m.volume_burst: score += 10.0

        # Spread tightening = improving liquidity
        if m.spread_tightening: score += 10.0

        # Extreme tick imbalance = directional but potentially thin
        abs_imb = abs(m.tick_imbalance)
        if abs_imb > 80:  score -= 10.0
        elif abs_imb > 50: score += 5.0

        return round(max(0.0, min(100.0, score)), 1)

    # ── Accessors ─────────────────────────────────────────────────

    @property
    def using_dom(self) -> bool:
        return self._dom_available

    @property
    def latest_dom(self) -> Optional[DOMMetrics]:
        return self._latest_dom

    @property
    def latest_fallback(self) -> Optional[FallbackMetrics]:
        return self._latest_fallback

    def current_liquidity_score(self) -> float:
        if self._dom_available and self._latest_dom:
            return self._latest_dom.liquidity_score
        if self._latest_fallback:
            return self._latest_fallback.liquidity_score
        return 50.0

    def snapshot_dict(self) -> Dict:
        if self._dom_available and self._latest_dom:
            m = self._latest_dom
            return {
                "mode":        "DOM",
                "liq_score":   m.liquidity_score,
                "imbalance":   round(m.imbalance, 3),
                "buy_wall":    m.buy_wall,
                "sell_wall":   m.sell_wall,
                "bid_vacuum":  m.bid_vacuum,
                "ask_vacuum":  m.ask_vacuum,
                "stacked_bids": m.stacked_bids,
                "stacked_asks": m.stacked_asks,
                "book_skew":   round(m.book_skew, 3),
                "total_bid":   round(m.total_bid_vol, 1),
                "total_ask":   round(m.total_ask_vol, 1),
            }
        elif self._latest_fallback:
            m = self._latest_fallback
            return {
                "mode":         "FALLBACK",
                "liq_score":    m.liquidity_score,
                "tick_freq":    round(m.tick_frequency, 2),
                "tick_imb":     round(m.tick_imbalance, 1),
                "tick_vel":     round(m.tick_velocity, 4),
                "tick_accel":   round(m.tick_acceleration, 4),
                "synth_delta":  round(m.synthetic_delta, 1),
                "agg_buy_est":  round(m.aggressive_buy_est, 3),
                "agg_sell_est": round(m.aggressive_sell_est, 3),
                "vol_burst":    m.volume_burst,
            }
        return {"mode": "NONE", "liq_score": 50.0}
