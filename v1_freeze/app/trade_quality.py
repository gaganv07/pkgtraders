"""
app/trade_quality.py — Trade Quality Engine

Generates a composite score (0-100) per direction.
Threshold for trade entry: score >= settings.risk.min_quality_score.

Default weighting:
  35% Order Flow
  25% Liquidity (DOM or fallback)
  15% Market Structure (microstructure + price action)
  10% Volatility
  10% Session Quality
   5% News State

Multi-asset upgrade: evaluate() accepts an optional `symbol` parameter.
Per-symbol weight overrides are applied so each asset is scored
appropriately for its market microstructure characteristics.

Every component is scored 0-100 before weighting.
Hard veto rules can block a trade regardless of score.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.config import (
    settings, QualityWeights, USE_RECALIBRATED_SCORING,
    SHADOW_MODE, RECOMMENDED_WEIGHTS, RECOMMENDED_THRESHOLD
)
from app.order_flow import OFSnapshot
from app.dom_engine import DOMMetrics, FallbackMetrics
from app.microstructure import MicrostructureState
from app.market_data import VolState
from app.volume_analytics import VolumeSnapshot
from app.session import SessionState

logger = logging.getLogger(__name__)


# ── Per-symbol quality weight overrides ──────────────────────────────────────
# Forex pairs are more EMA/trend driven; metals are more OF/liquidity driven.
# Indices depend heavily on session and volatility regime.
# Weights must approximately sum to 1.0.
_SYMBOL_WEIGHTS: Dict[str, QualityWeights] = {
    "EURUSD": QualityWeights(
        order_flow=0.25, liquidity=0.20,
        market_structure=0.30, volatility=0.10,
        session=0.10, news=0.05,
    ),
    "GBPUSD": QualityWeights(
        order_flow=0.25, liquidity=0.20,
        market_structure=0.30, volatility=0.10,
        session=0.10, news=0.05,
    ),
    "USDJPY": QualityWeights(
        order_flow=0.25, liquidity=0.20,
        market_structure=0.25, volatility=0.10,
        session=0.15, news=0.05,
    ),
    "NAS100": QualityWeights(
        order_flow=0.30, liquidity=0.20,
        market_structure=0.15, volatility=0.20,
        session=0.10, news=0.05,
    ),
    "US30": QualityWeights(
        order_flow=0.30, liquidity=0.20,
        market_structure=0.15, volatility=0.20,
        session=0.10, news=0.05,
    ),
    "BTCUSD": QualityWeights(
        order_flow=0.40, liquidity=0.25,
        market_structure=0.10, volatility=0.15,
        session=0.05, news=0.05,
    ),
    # XAUUSD uses the global defaults (most OF/liquidity driven)
}


@dataclass
class QualityBreakdown:
    direction: str = "NEUTRAL"   # "LONG" | "SHORT"
    symbol:    str = "XAUUSD"    # which market this applies to

    # Component scores (0-100)
    of_score:      float = 50.0
    liq_score:     float = 50.0
    ms_score:      float = 50.0
    vol_score:     float = 50.0
    session_score: float = 50.0
    news_score:    float = 50.0

    # Weighted total
    total: float = 0.0

    # Veto flags
    vetoed:       bool = False
    veto_reasons: List[str] = field(default_factory=list)

    # Pass/fail
    tradeable: bool = False

    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TradeQualityEngine:
    """
    Institutional trade quality gate — multi-asset capable.
    Scores both LONG and SHORT and returns the better one if tradeable.
    Accepts optional `symbol` to apply per-symbol weight overrides.
    """

    def __init__(self):
        self._global_w = settings.quality
        self._min      = settings.risk.min_quality_score
        self._latest_long:  Optional[QualityBreakdown] = None
        self._latest_short: Optional[QualityBreakdown] = None
        # Rolling scores history for adaptive threshold (max 200 elements)
        self._score_history = deque(maxlen=200)

    def load_history(self, scores: List[float]) -> None:
        """Load recent quality scores to warm up the history queue."""
        self._score_history.clear()
        self._score_history.extend(scores)

    def get_adaptive_threshold(self) -> float:
        """Compute the adaptive 70th percentile threshold, falling back to 65.0."""
        if len(self._score_history) < 200:
            return 65.0
        
        recent_scores = sorted(list(self._score_history))
        idx = 0.70 * (len(recent_scores) - 1)
        idx_low = int(math.floor(idx))
        idx_high = int(math.ceil(idx))
        if idx_low == idx_high:
            p70 = recent_scores[idx_low]
        else:
            p70 = recent_scores[idx_low] * (idx_high - idx) + recent_scores[idx_high] * (idx - idx_low)
        
        return max(58.0, min(80.0, p70))

    def _weights(self, symbol: str) -> QualityWeights:
        """Return quality weights for the given symbol."""
        return _SYMBOL_WEIGHTS.get(symbol, self._global_w)

    def evaluate(
        self,
        of_snap:  Optional[OFSnapshot],
        liq_snap: "DOMMetrics | FallbackMetrics | None",
        ms_state: Optional[MicrostructureState],
        vol_state: Optional[VolState],
        vol_snap: Optional[VolumeSnapshot],
        sess:     Optional[SessionState],
        ema_bull_h1:  bool,
        ema_bear_h1:  bool,
        ema_bull_m15: bool,
        ema_bear_m15: bool,
        price_above_vwap: Optional[bool],
        current_spread:   float,
        avg_spread:       float,
        symbol:           str = "XAUUSD",
    ) -> Optional[QualityBreakdown]:
        """
        Evaluate quality using the active scoring engine based on configuration switch.
        """
        if USE_RECALIBRATED_SCORING:
            return self.evaluate_recalibrated(
                of_snap, liq_snap, ms_state, vol_state, vol_snap, sess,
                ema_bull_h1, ema_bear_h1, ema_bull_m15, ema_bear_m15,
                price_above_vwap, current_spread, avg_spread, symbol
            )
        else:
            return self.evaluate_legacy(
                of_snap, liq_snap, ms_state, vol_state, vol_snap, sess,
                ema_bull_h1, ema_bear_h1, ema_bull_m15, ema_bear_m15,
                price_above_vwap, current_spread, avg_spread, symbol
            )

    def evaluate_legacy(
        self,
        of_snap:  Optional[OFSnapshot],
        liq_snap: "DOMMetrics | FallbackMetrics | None",
        ms_state: Optional[MicrostructureState],
        vol_state: Optional[VolState],
        vol_snap: Optional[VolumeSnapshot],
        sess:     Optional[SessionState],
        ema_bull_h1:  bool,
        ema_bear_h1:  bool,
        ema_bull_m15: bool,
        ema_bear_m15: bool,
        price_above_vwap: Optional[bool],
        current_spread:   float,
        avg_spread:       float,
        symbol:           str = "XAUUSD",
    ) -> Optional[QualityBreakdown]:
        long_bd  = self._score_legacy("LONG",  of_snap, liq_snap, ms_state,
                                      vol_state, vol_snap, sess,
                                      ema_bull_h1, ema_bear_h1,
                                      ema_bull_m15, ema_bear_m15,
                                      price_above_vwap, current_spread, avg_spread,
                                      symbol)
        short_bd = self._score_legacy("SHORT", of_snap, liq_snap, ms_state,
                                      vol_state, vol_snap, sess,
                                      ema_bull_h1, ema_bear_h1,
                                      ema_bull_m15, ema_bear_m15,
                                      price_above_vwap, current_spread, avg_spread,
                                      symbol)

        self._latest_long  = long_bd
        self._latest_short = short_bd

        best = max([long_bd, short_bd], key=lambda x: x.total)
        if best.tradeable:
            logger.debug(
                f"Quality PASS (Legacy): {symbol} {best.direction} score={best.total:.1f}"
            )
            return best

        logger.debug(
            f"Quality FAIL (Legacy): {symbol} LONG={long_bd.total:.1f} "
            f"SHORT={short_bd.total:.1f} (need {self._min})"
        )
        return None

    def evaluate_recalibrated(
        self,
        of_snap:  Optional[OFSnapshot],
        liq_snap: "DOMMetrics | FallbackMetrics | None",
        ms_state: Optional[MicrostructureState],
        vol_state: Optional[VolState],
        vol_snap: Optional[VolumeSnapshot],
        sess:     Optional[SessionState],
        ema_bull_h1:  bool,
        ema_bear_h1:  bool,
        ema_bull_m15: bool,
        ema_bear_m15: bool,
        price_above_vwap: Optional[bool],
        current_spread:   float,
        avg_spread:       float,
        symbol:           str = "XAUUSD",
    ) -> Optional[QualityBreakdown]:
        long_bd  = self._score_recalibrated("LONG",  of_snap, liq_snap, ms_state,
                                            vol_state, vol_snap, sess,
                                            ema_bull_h1, ema_bear_h1,
                                            ema_bull_m15, ema_bear_m15,
                                            price_above_vwap, current_spread, avg_spread,
                                            symbol)
        short_bd = self._score_recalibrated("SHORT", of_snap, liq_snap, ms_state,
                                            vol_state, vol_snap, sess,
                                            ema_bull_h1, ema_bear_h1,
                                            ema_bull_m15, ema_bear_m15,
                                            price_above_vwap, current_spread, avg_spread,
                                            symbol)

        self._latest_long  = long_bd
        self._latest_short = short_bd

        best = max([long_bd, short_bd], key=lambda x: x.total)
        
        # Evaluate tradeability using adaptive threshold
        threshold = self.get_adaptive_threshold()
        if best.total >= threshold and not best.vetoed:
            best.tradeable = True
            logger.debug(
                f"Quality PASS (Recalibrated): {symbol} {best.direction} score={best.total:.1f}"
            )
            return best
        else:
            best.tradeable = False

        logger.debug(
            f"Quality FAIL (Recalibrated): {symbol} LONG={long_bd.total:.1f} "
            f"SHORT={short_bd.total:.1f} (need {threshold})"
        )
        return None

    def _score_legacy(
        self,
        direction: str,
        of_snap:   Optional[OFSnapshot],
        liq_snap,
        ms_state:  Optional[MicrostructureState],
        vol_state: Optional[VolState],
        vol_snap:  Optional[VolumeSnapshot],
        sess:      Optional[SessionState],
        ema_bull_h1:  bool,
        ema_bear_h1:  bool,
        ema_bull_m15: bool,
        ema_bear_m15: bool,
        price_above_vwap: Optional[bool],
        spread:    float,
        avg_spread: float,
        symbol:    str = "XAUUSD",
    ) -> QualityBreakdown:
        is_long = direction == "LONG"
        bd = QualityBreakdown(direction=direction, symbol=symbol)
        veto_reasons: List[str] = []

        # ── 1. Order Flow (35%) ────────────────────────────────────
        if of_snap:
            ms = of_snap.of_score
            if is_long:
                if ms >= 75:   bd.of_score = 95.0
                elif ms >= 62: bd.of_score = 78.0
                elif ms >= 52: bd.of_score = 58.0
                else:
                    bd.of_score = 20.0
                    veto_reasons.append(f"OF bearish ({ms:.0f})")
            else:
                if ms <= 25:   bd.of_score = 95.0
                elif ms <= 38: bd.of_score = 78.0
                elif ms <= 48: bd.of_score = 58.0
                else:
                    bd.of_score = 20.0
                    veto_reasons.append(f"OF bullish ({ms:.0f})")
        else:
            bd.of_score = 35.0
            veto_reasons.append("No OF data")

        # ── 2. Liquidity (25%) ────────────────────────────────────
        if liq_snap:
            bd.liq_score = liq_snap.liquidity_score
            if bd.liq_score < 25:
                veto_reasons.append(f"Liquidity critical ({bd.liq_score:.0f})")
        else:
            bd.liq_score = 45.0

        # Spread overlay
        if avg_spread > 0:
            sr = spread / avg_spread
            sp_adj = max(-20.0, min(10.0, 10.0 - (sr - 1.0) * 25.0))
            bd.liq_score = max(0.0, min(100.0, bd.liq_score + sp_adj))

        # ── 3. Market Structure (15%) ─────────────────────────────
        if ms_state:
            # Primary: EMA alignment
            if is_long:
                if ema_bull_h1 and ema_bull_m15:   ema_pts = 100.0
                elif ema_bull_h1:                   ema_pts = 75.0
                elif ema_bull_m15:                  ema_pts = 55.0
                elif ema_bear_h1:
                    ema_pts = 15.0
                    veto_reasons.append("EMA bearish vs LONG")
                else:                               ema_pts = 45.0
            else:
                if ema_bear_h1 and ema_bear_m15:   ema_pts = 100.0
                elif ema_bear_h1:                   ema_pts = 75.0
                elif ema_bear_m15:                  ema_pts = 55.0
                elif ema_bull_h1:
                    ema_pts = 15.0
                    veto_reasons.append("EMA bullish vs SHORT")
                else:                               ema_pts = 45.0

            # VWAP
            if price_above_vwap is True:
                vwap_adj = 10.0 if is_long else -10.0
            elif price_above_vwap is False:
                vwap_adj = -10.0 if is_long else 10.0
            else:
                vwap_adj = 0.0

            # Microstructure score
            if is_long:
                micro = ms_state.bull_ms_score
            else:
                micro = ms_state.bear_ms_score

            # Bonus: key events
            if is_long and (ms_state.liq_grab_down or ms_state.choch_bull):
                micro = min(100.0, micro + 15.0)
            if not is_long and (ms_state.liq_grab_up or ms_state.choch_bear):
                micro = min(100.0, micro + 15.0)

            # FVG confluence
            if is_long and ms_state.price_in_bull_fvg:
                micro = min(100.0, micro + 8.0)
            if not is_long and ms_state.price_in_bear_fvg:
                micro = min(100.0, micro + 8.0)

            bd.ms_score = round(max(0.0, min(100.0,
                ema_pts * 0.40 + micro * 0.45 + vwap_adj * 0.15
            )), 1)
        else:
            bd.ms_score = 45.0

        # ── 4. Volatility (10%) ───────────────────────────────────
        if vol_state:
            r = vol_state.regime
            p = vol_state.percentile
            if r == "EXPANDING" and 45 <= p <= 80:
                bd.vol_score = 88.0
            elif r == "NORMAL" and 25 <= p <= 70:
                bd.vol_score = 72.0
            elif r == "COMPRESSED":
                bd.vol_score = 55.0   # breakout potential
            elif r == "EXPLOSIVE":
                bd.vol_score = 30.0
                veto_reasons.append("Explosive volatility")
            else:
                bd.vol_score = 60.0

            # Volume confirmation
            if vol_snap:
                if vol_snap.expansion: bd.vol_score = min(100.0, bd.vol_score + 10.0)
                if vol_snap.contraction: bd.vol_score = max(0.0, bd.vol_score - 8.0)
                if is_long and vol_snap.vol_bull_bias > 0.65:
                    bd.vol_score = min(100.0, bd.vol_score + 8.0)
                if not is_long and vol_snap.vol_bull_bias < 0.35:
                    bd.vol_score = min(100.0, bd.vol_score + 8.0)
        else:
            bd.vol_score = 50.0

        # ── 5. Session Quality (10%) ──────────────────────────────
        if sess:
            bd.session_score = sess.session_quality
            if not sess.is_active:
                veto_reasons.append("Outside active session")
        else:
            bd.session_score = 50.0

        # ── 6. News State (5%) ───────────────────────────────────
        if sess:
            if sess.news_blackout:
                bd.news_score = 0.0
                veto_reasons.append("News blackout active")
            else:
                bd.news_score = sess.news_score
                if is_long and sess.news_sentiment == "BEARISH":
                    bd.news_score = max(0.0, bd.news_score - 15.0)
                if not is_long and sess.news_sentiment == "BULLISH":
                    bd.news_score = max(0.0, bd.news_score - 15.0)
        else:
            bd.news_score = 50.0

        # ── Weighted total (symbol-aware weights) ─────────────────
        w = self._weights(symbol)
        bd.total = round(
            bd.of_score      * w.order_flow       +
            bd.liq_score     * w.liquidity        +
            bd.ms_score      * w.market_structure +
            bd.vol_score     * w.volatility       +
            bd.session_score * w.session          +
            bd.news_score    * w.news,
            1,
        )

        # ── Hard vetoes ───────────────────────────────────────────
        hard_veto = bool(
            bd.liq_score < 20
            or bd.session_score < 10
            or (sess and sess.news_blackout)
        )
        if hard_veto:
            bd.vetoed = True

        bd.veto_reasons = veto_reasons
        if veto_reasons:
            logger.info(
                f"{direction}: veto reasons -> {veto_reasons}, "
                f"score={bd.total}, vetoed={bd.vetoed} "
            )
        bd.tradeable = (
            bd.total >= self._min
            and not bd.vetoed 
        )
        return bd

    def _score_recalibrated(
        self,
        direction: str,
        of_snap:   Optional[OFSnapshot],
        liq_snap,
        ms_state:  Optional[MicrostructureState],
        vol_state: Optional[VolState],
        vol_snap:  Optional[VolumeSnapshot],
        sess:      Optional[SessionState],
        ema_bull_h1:  bool,
        ema_bear_h1:  bool,
        ema_bull_m15: bool,
        ema_bear_m15: bool,
        price_above_vwap: Optional[bool],
        spread:    float,
        avg_spread: float,
        symbol:    str = "XAUUSD",
    ) -> QualityBreakdown:
        is_long = direction == "LONG"
        bd = QualityBreakdown(direction=direction, symbol=symbol)
        veto_reasons: List[str] = []

        # Sigmoid helper
        def sigmoid(x: float, center: float = 55.0, steepness: float = 0.12) -> float:
            try:
                return 100.0 / (1.0 + math.exp(-steepness * (x - center)))
            except OverflowError:
                return 0.0 if x < center else 100.0

        # Piecewise linear EMA helper
        def smooth_ema_score(ema_pts_raw: float) -> float:
            anchors = [(0.0, 10.0), (15.0, 20.0), (45.0, 45.0), (55.0, 58.0), (75.0, 78.0), (100.0, 100.0)]
            for i in range(len(anchors) - 1):
                x0, y0 = anchors[i]
                x1, y1 = anchors[i+1]
                if x0 <= ema_pts_raw <= x1:
                    return round(y0 + (y1 - y0) * (ema_pts_raw - x0) / (x1 - x0), 1)
            return 50.0

        # Volatility sigmoid helper
        def smooth_vol_score(regime: str, percentile: float) -> float:
            regime_base = {"EXPANDING": 75.0, "NORMAL": 65.0,
                           "COMPRESSED": 55.0, "EXPLOSIVE": 30.0}.get(regime, 60.0)
            if percentile < 20:
                p_adj = -15.0
            elif percentile < 40:
                p_adj = -5.0
            elif percentile <= 75:
                p_adj = 10.0
            elif percentile <= 90:
                p_adj = 0.0
            else:
                p_adj = -20.0
            return round(max(0.0, min(100.0, regime_base + p_adj)), 1)

        # ── 1. Order Flow (22% dynamic) ────────────────────────────────────
        if of_snap:
            raw_of_score = of_snap.of_score
            if raw_of_score <= 35.0:
                raw_of_score = 50.0
        else:
            raw_of_score = 50.0

        if is_long:
            bd.of_score = round(sigmoid(raw_of_score, center=55.0, steepness=0.12), 1)
        else:
            bd.of_score = round(sigmoid(100.0 - raw_of_score, center=55.0, steepness=0.12), 1)

        # ── 2. Liquidity (14.1% + 4.9% DOM = 19% dynamic) ─────────────────
        if liq_snap:
            bd.liq_score = liq_snap.liquidity_score
        else:
            bd.liq_score = 50.0

        # Spread overlay
        if avg_spread > 0:
            sr = spread / avg_spread
            sp_adj = max(-20.0, min(10.0, 10.0 - (sr - 1.0) * 25.0))
            bd.liq_score = max(0.0, min(100.0, bd.liq_score + sp_adj))

        # ── 3. Market Structure (25.8% dynamic) ─────────────────────────────
        if ms_state:
            # Primary: EMA alignment
            if is_long:
                if ema_bull_h1 and ema_bull_m15:   ema_pts_raw = 100.0
                elif ema_bull_h1:                   ema_pts_raw = 75.0
                elif ema_bull_m15:                  ema_pts_raw = 55.0
                elif ema_bear_h1:                   ema_pts_raw = 15.0
                else:                               ema_pts_raw = 45.0
            else:
                if ema_bear_h1 and ema_bear_m15:   ema_pts_raw = 100.0
                elif ema_bear_h1:                   ema_pts_raw = 75.0
                elif ema_bear_m15:                  ema_pts_raw = 55.0
                elif ema_bull_h1:                   ema_pts_raw = 15.0
                else:                               ema_pts_raw = 45.0

            ema_pts = smooth_ema_score(ema_pts_raw)

            # VWAP
            if price_above_vwap is True:
                vwap_adj = 10.0 if is_long else -10.0
            elif price_above_vwap is False:
                vwap_adj = -10.0 if is_long else 10.0
            else:
                vwap_adj = 0.0

            # Microstructure score
            if is_long:
                micro = ms_state.bull_ms_score
            else:
                micro = ms_state.bear_ms_score

            # Bonus: key events
            if is_long and (ms_state.liq_grab_down or ms_state.choch_bull):
                micro = min(100.0, micro + 15.0)
            if not is_long and (ms_state.liq_grab_up or ms_state.choch_bear):
                micro = min(100.0, micro + 15.0)

            # FVG confluence
            if is_long and ms_state.price_in_bull_fvg:
                micro = min(100.0, micro + 8.0)
            if not is_long and ms_state.price_in_bear_fvg:
                micro = min(100.0, micro + 8.0)

            bd.ms_score = round(max(0.0, min(100.0,
                ema_pts * 0.40 + micro * 0.45 + vwap_adj * 0.15
            )), 1)
        else:
            bd.ms_score = 45.0

        # ── 4. Volatility (5.2% dynamic) ───────────────────────────────────
        if vol_state:
            bd.vol_score = smooth_vol_score(vol_state.regime, vol_state.percentile)

            # Volume confirmation
            if vol_snap:
                if vol_snap.expansion: bd.vol_score = min(100.0, bd.vol_score + 10.0)
                if vol_snap.contraction: bd.vol_score = max(0.0, bd.vol_score - 8.0)
                if is_long and vol_snap.vol_bull_bias > 0.65:
                    bd.vol_score = min(100.0, bd.vol_score + 8.0)
                if not is_long and vol_snap.vol_bull_bias < 0.35:
                    bd.vol_score = min(100.0, bd.vol_score + 8.0)
        else:
            bd.vol_score = 50.0

        # ── 5. Session Quality (8.8% dynamic) ──────────────────────────────
        if sess:
            bd.session_score = sess.session_quality
        else:
            bd.session_score = 50.0

        # ── 6. News State (19.3% dynamic) ──────────────────────────────────
        if sess:
            if sess.news_blackout:
                bd.news_score = 0.0
                veto_reasons.append("News blackout active")
            else:
                bd.news_score = sess.news_score
                if is_long and sess.news_sentiment == "BEARISH":
                    bd.news_score = max(0.0, bd.news_score - 15.0)
                if not is_long and sess.news_sentiment == "BULLISH":
                    bd.news_score = max(0.0, bd.news_score - 15.0)
        else:
            bd.news_score = 50.0

        # ── Core Weighted total ───────────────────────────────────────────
        w = RECOMMENDED_WEIGHTS.get("recommended_blended_weights", {})
        w_of = w.get("order_flow", 0.22)
        w_liq = w.get("liquidity", 0.141)
        w_ms = w.get("market_structure", 0.258)
        w_vol = w.get("volatility", 0.052)
        w_sess = w.get("session", 0.088)
        w_news = w.get("news", 0.193)
        w_dom = w.get("dom", 0.049)

        core = (
            bd.of_score      * w_of +
            bd.liq_score     * (w_liq + w_dom) +
            bd.ms_score      * w_ms +
            bd.vol_score     * w_vol +
            bd.session_score * w_sess +
            bd.news_score    * w_news
        )

        # ── ICT confluences bonus ─────────────────────────────────────────
        bonus = 0.0
        if ms_state:
            # mss: +4
            if (is_long and ms_state.choch_bull) or (not is_long and ms_state.choch_bear):
                bonus += 4.0
            # fvg: +3
            if (is_long and ms_state.price_in_bull_fvg) or (not is_long and ms_state.price_in_bear_fvg):
                bonus += 3.0
            # liq sweep: +4
            if (is_long and ms_state.liq_grab_down) or (not is_long and ms_state.liq_grab_up):
                bonus += 4.0
            # bos: +4
            if (is_long and (ms_state.bos_bull or ms_state.choch_bull or ms_state.structure_bias == "BULLISH")) or \
               (not is_long and (ms_state.bos_bear or ms_state.choch_bear or ms_state.structure_bias == "BEARISH")):
                bonus += 4.0

        bonus = min(15.0, bonus)

        # Final Score: core + bonus, capped at 100.0
        bd.total = round(min(100.0, core + bonus), 1)

        # ── Hard vetoes ───────────────────────────────────────────────────
        if sess and sess.news_blackout:
            bd.vetoed = True

        bd.veto_reasons = veto_reasons
        if veto_reasons:
            logger.info(
                f"{direction} (Recalibrated): veto reasons -> {veto_reasons}, "
                f"score={bd.total}, vetoed={bd.vetoed}"
            )
        
        bd.tradeable = False
        return bd

    @property
    def latest_long(self) -> Optional[QualityBreakdown]:
        return self._latest_long

    @property
    def latest_short(self) -> Optional[QualityBreakdown]:
        return self._latest_short

    def snapshot_dict(self) -> Dict:
        def _bd(bd: Optional[QualityBreakdown]) -> Dict:
            if not bd:
                return {}
            return {
                "symbol":       bd.symbol,
                "total":        bd.total,
                "tradeable":    bd.tradeable,
                "of_score":     bd.of_score,
                "liq_score":    bd.liq_score,
                "ms_score":     bd.ms_score,
                "vol_score":    bd.vol_score,
                "session_score": bd.session_score,
                "news_score":   bd.news_score,
                "veto_reasons": bd.veto_reasons,
            }
        return {"long": _bd(self._latest_long), "short": _bd(self._latest_short)}
