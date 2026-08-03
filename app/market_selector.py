"""
app/market_selector.py — Multi-Asset Market Selection Engine

Continuously ranks every enabled symbol using a composite confidence
score built from 6 orthogonal factors:

  1. Trend strength        (25%) — EMA50/200 cross-TF alignment
  2. Volatility quality    (20%) — ATR regime (prefer EXPANDING, reject EXPLOSIVE)
  3. Order flow momentum   (20%) — CVD direction & strength over ranking window
  4. Session suitability   (15%) — Active session weighted by symbol preference
  5. Spread quality        (10%) — Current spread vs expected for symbol
  6. Volume rank           (10%) — Relative tick-volume vs baseline

A symbol is tradeable only when:
  - score >= settings.selector.min_symbol_score
  - spread <= SymbolConfig.max_spread_pts
  - ATR >= SymbolConfig.min_atr (if configured)
  - Not in news blackout (for its relevant currencies)

The engine returns a ranked list; the orchestrator picks the top symbol
that also passes the full quality gate (trade_quality.py).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

from app.config import settings, SYMBOL_CONFIGS, SymbolConfig
from app.market_data import MarketData, MultiSymbolMarketData, TF_M5, TF_M15, TF_H1

logger = logging.getLogger(__name__)


# ── Currency → symbol mapping for news blackout propagation ─────────────────

_SYMBOL_CURRENCIES: Dict[str, List[str]] = {
    "XAUUSD": ["USD", "XAU"],
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "NAS100": ["USD"],
    "US30":   ["USD"],
    "BTCUSD": ["USD", "BTC"],
}

# Session → preferred symbols
_SESSION_SYMBOL_BOOST: Dict[str, List[str]] = {
    "LONDON":    ["GBPUSD", "EURUSD", "XAUUSD"],
    "NEW_YORK":  ["EURUSD", "GBPUSD", "XAUUSD", "NAS100", "US30"],
    "OVERLAP":   ["EURUSD", "GBPUSD", "XAUUSD", "NAS100"],
    "TOKYO":     ["USDJPY"],
}


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class SymbolRanking:
    """Score and state for one symbol at one point in time."""
    symbol:      str
    score:       float        # 0–100 composite
    direction:   str          # "LONG" | "SHORT" | "NEUTRAL"
    atr:         float        # ATR(M5)
    spread:      float        # current spread
    vol_regime:  str          # COMPRESSED | NORMAL | EXPANDING | EXPLOSIVE
    tradeable:   bool         # passes all filters
    skip_reason: str = ""

    # Sub-scores (0–100)
    trend_score:   float = 50.0
    vol_score:     float = 50.0
    of_score:      float = 50.0
    session_score: float = 50.0
    spread_score:  float = 50.0
    volume_score:  float = 50.0

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SelectorState:
    """Full ranking snapshot — one entry per symbol."""
    rankings:    List[SymbolRanking] = field(default_factory=list)
    best_symbol: Optional[str]       = None
    best_score:  float               = 0.0
    timestamp:   datetime            = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── MarketSelector ────────────────────────────────────────────────────────────

class MarketSelector:
    """
    Continuously ranks all enabled symbols and picks the best setup.

    Call `rank_all()` every scan interval (default 5 s) from the orchestrator.
    Call `best()` to get the highest-scoring tradeable symbol.
    """

    def __init__(self):
        self._cfg        = settings.selector
        self._risk_cfg   = settings.risk
        self._state      = SelectorState()
        self._last_scan  = 0.0

        # Rolling tick-volume baseline per symbol (for relative volume rank)
        self._vol_baseline: Dict[str, Deque[float]] = {
            sym: deque(maxlen=60)
            for sym in SYMBOL_CONFIGS
            if SYMBOL_CONFIGS[sym].enabled
        }

        logger.info(
            f"MarketSelector ready — tracking "
            f"{[s for s,c in SYMBOL_CONFIGS.items() if c.enabled]}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def rank_all(
        self,
        msd:           MultiSymbolMarketData,
        session_state,                          # app.session.SessionState
        news_events:   Optional[List] = None,   # list of NewsEvent
    ) -> SelectorState:
        """
        Score every enabled symbol and return a ranked SelectorState.
        Throttled to self._cfg.scan_interval_s internally.
        """
        now = time.time()
        if now - self._last_scan < self._cfg.scan_interval_s:
            return self._state
        self._last_scan = now

        rankings: List[SymbolRanking] = []

        for canonical, sym_cfg in SYMBOL_CONFIGS.items():
            if not sym_cfg.enabled:
                continue

            md = msd.get(canonical)
            if md is None:
                continue

            ranking = self._score_symbol(
                canonical, sym_cfg, md, session_state, news_events or []
            )
            rankings.append(ranking)

        # Sort: tradeable first, then by score descending
        rankings.sort(key=lambda r: (not r.tradeable, -r.score))

        best = next((r for r in rankings if r.tradeable), None)

        self._state = SelectorState(
            rankings=rankings,
            best_symbol=best.symbol if best else None,
            best_score=best.score if best else 0.0,
        )

        if best:
            logger.info(
                f"[SELECTOR] Best={best.symbol} score={best.score:.1f} "
                f"dir={best.direction} regime={best.vol_regime}"
            )
        else:
            reasons = [f"{r.symbol}({r.skip_reason})" for r in rankings if not r.tradeable]
            logger.debug(f"[SELECTOR] No tradeable symbol — {reasons}")

        return self._state

    def best(self) -> Optional[SymbolRanking]:
        """Return the best-ranked tradeable symbol, or None."""
        for r in self._state.rankings:
            if r.tradeable:
                return r
        return None

    def get_ranking(self, symbol: str) -> Optional[SymbolRanking]:
        """Return ranking for a specific symbol."""
        for r in self._state.rankings:
            if r.symbol == symbol:
                return r
        return None

    @property
    def state(self) -> SelectorState:
        return self._state

    def snapshot_dict(self) -> Dict:
        return {
            "best_symbol": self._state.best_symbol,
            "best_score":  round(self._state.best_score, 1),
            "rankings": [
                {
                    "symbol":    r.symbol,
                    "score":     round(r.score, 1),
                    "direction": r.direction,
                    "tradeable": r.tradeable,
                    "regime":    r.vol_regime,
                    "skip":      r.skip_reason,
                }
                for r in self._state.rankings
            ],
        }

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_symbol(
        self,
        canonical:   str,
        sym_cfg:     SymbolConfig,
        md:          MarketData,
        sess,
        news_events: List,
    ) -> SymbolRanking:
        """Compute composite score for one symbol."""
        w = self._cfg

        tick = md.latest_tick
        if tick is None or not md.is_fresh:
            return SymbolRanking(
                symbol=canonical, score=0.0, direction="NEUTRAL",
                atr=0.0, spread=0.0, vol_regime="UNKNOWN",
                tradeable=False, skip_reason="no_tick",
            )

        atr   = md.atr(TF_M5) or 0.0
        spread = tick.spread
        vol   = md.volatility

        # ── Hard filters ─────────────────────────────────────────────────────

        if sym_cfg.max_spread_pts > 0 and spread > sym_cfg.max_spread_pts:
            return SymbolRanking(
                symbol=canonical, score=0.0, direction="NEUTRAL",
                atr=atr, spread=spread, vol_regime=vol.regime,
                tradeable=False,
                skip_reason=f"spread_too_high({spread:.4f}>{sym_cfg.max_spread_pts})",
            )

        if sym_cfg.min_atr > 0 and atr < sym_cfg.min_atr:
            return SymbolRanking(
                symbol=canonical, score=0.0, direction="NEUTRAL",
                atr=atr, spread=spread, vol_regime=vol.regime,
                tradeable=False,
                skip_reason=f"atr_too_low({atr:.5f}<{sym_cfg.min_atr})",
            )

        if vol.regime == "EXPLOSIVE":
            return SymbolRanking(
                symbol=canonical, score=10.0, direction="NEUTRAL",
                atr=atr, spread=spread, vol_regime=vol.regime,
                tradeable=False, skip_reason="explosive_volatility",
            )

        # News blackout for this symbol's currencies
        if self._is_news_blocked(canonical, news_events):
            return SymbolRanking(
                symbol=canonical, score=0.0, direction="NEUTRAL",
                atr=atr, spread=spread, vol_regime=vol.regime,
                tradeable=False, skip_reason="news_blackout",
            )

        # ── Component scores ──────────────────────────────────────────────────

        # 1. Trend strength (EMA cross-TF alignment)
        trend_score, direction = self._trend_score(md)

        # 2. Volatility quality
        vol_score = self._vol_score(vol)

        # 3. Order flow momentum
        of_score = self._of_score(md)

        # 4. Session suitability
        session_score = self._session_score(canonical, sym_cfg, sess)

        # 5. Spread quality
        sp_score = self._spread_score(spread, sym_cfg)

        # 6. Volume rank
        tick_vol = md.latest_bar(TF_M5).tick_vol if md.latest_bar(TF_M5) else 0
        volume_score = self._volume_rank_score(canonical, float(tick_vol))

        # ── Weighted composite ────────────────────────────────────────────────
        score = (
            trend_score   * w.w_trend       +
            vol_score     * w.w_volatility  +
            of_score      * w.w_order_flow  +
            session_score * w.w_session     +
            sp_score      * w.w_spread      +
            volume_score  * w.w_volume
        )
        score = round(max(0.0, min(100.0, score)), 1)

        tradeable = score >= self._cfg.min_symbol_score

        ranking = SymbolRanking(
            symbol=canonical,
            score=score,
            direction=direction,
            atr=atr,
            spread=spread,
            vol_regime=vol.regime,
            tradeable=tradeable,
            skip_reason="" if tradeable else f"score_low({score:.1f})",
            trend_score=trend_score,
            vol_score=vol_score,
            of_score=of_score,
            session_score=session_score,
            spread_score=sp_score,
            volume_score=volume_score,
        )
        return ranking

    def _trend_score(self, md: MarketData) -> Tuple[float, str]:
        """
        Score EMA cross-TF trend strength (0–100).
        Returns (score, direction).
        """
        bull_h1  = md.is_ema_bull(TF_H1)
        bear_h1  = md.is_ema_bear(TF_H1)
        bull_m15 = md.is_ema_bull(TF_M15)
        bear_m15 = md.is_ema_bear(TF_M15)
        bull_m5  = md.is_ema_bull(TF_M5)
        bear_m5  = md.is_ema_bear(TF_M5)

        # Count bullish signals
        bull_signals = sum([bull_h1, bull_m15, bull_m5])
        bear_signals = sum([bear_h1, bear_m15, bear_m5])

        if bull_signals >= 3:
            return 95.0, "LONG"
        elif bull_signals == 2:
            return 75.0, "LONG"
        elif bear_signals >= 3:
            return 95.0, "SHORT"
        elif bear_signals == 2:
            return 75.0, "SHORT"
        elif bull_signals == 1:
            return 45.0, "LONG"
        elif bear_signals == 1:
            return 45.0, "SHORT"
        else:
            return 25.0, "NEUTRAL"

    def _vol_score(self, vol) -> float:
        """Score ATR volatility regime (0–100)."""
        regime = vol.regime
        pct    = vol.percentile

        if regime == "EXPANDING" and 35 <= pct <= 78:
            return 90.0   # ideal: moving, not extreme
        elif regime == "EXPANDING":
            return 72.0
        elif regime == "NORMAL" and 25 <= pct <= 65:
            return 65.0
        elif regime == "NORMAL":
            return 52.0
        elif regime == "COMPRESSED":
            return 40.0   # low vol — range, skip
        elif regime == "EXPLOSIVE":
            return 5.0    # too dangerous
        return 50.0

    def _of_score(self, md: MarketData) -> float:
        """
        Score order flow momentum from recent bars.
        Positive CVD proxy: count of bullish vs bearish bars
        on M5 over last 10 bars.
        """
        bars = md.bars(TF_M5)[-10:]
        if not bars:
            return 50.0
        bulls = sum(1 for b in bars if b.is_bull)
        bears = len(bars) - bulls
        if bulls > bears:
            ratio = bulls / len(bars)
            return 50.0 + ratio * 50.0
        elif bears > bulls:
            ratio = bears / len(bars)
            return 50.0 - ratio * 50.0
        return 50.0

    def _session_score(self, canonical: str, sym_cfg: SymbolConfig, sess) -> float:
        """Score how well the current session suits this symbol (0–100)."""
        if sess is None:
            return 50.0

        base_quality = getattr(sess, "session_quality", 50.0)

        # Determine active session name
        active_sessions = []
        if getattr(sess, "is_overlap", False):
            active_sessions.append("OVERLAP")
        elif getattr(sess, "is_london", False):
            active_sessions.append("LONDON")
        if getattr(sess, "is_ny", False):
            active_sessions.append("NEW_YORK")
        if getattr(sess, "is_asian", False):
            active_sessions.append("TOKYO")

        # Symbol preferred sessions
        pref = sym_cfg.preferred_sessions or []
        if not pref:
            return base_quality  # 24/7 symbol (BTC), use session quality as-is

        # Check for match between active sessions and symbol preferences
        boost = 0.0
        for active in active_sessions:
            if active in pref:
                boost = 20.0
                break
            # Check if symbol appears in session boost table
            for sess_name, syms in _SESSION_SYMBOL_BOOST.items():
                if canonical in syms and sess_name in active_sessions:
                    boost = max(boost, 10.0)

        return min(100.0, base_quality + boost)

    def _spread_score(self, spread: float, sym_cfg: SymbolConfig) -> float:
        """Score spread quality relative to the symbol's typical range (0–100)."""
        max_sp = sym_cfg.max_spread_pts
        if max_sp <= 0:
            return 70.0

        ratio = spread / max_sp
        if ratio <= 0.3:   return 100.0
        elif ratio <= 0.5: return 85.0
        elif ratio <= 0.7: return 70.0
        elif ratio <= 0.9: return 50.0
        elif ratio <= 1.0: return 25.0
        return 0.0   # above max — should have been filtered already

    def _volume_rank_score(self, symbol: str, tick_vol: float) -> float:
        """Score tick volume relative to rolling baseline (0–100)."""
        buf = self._vol_baseline.get(symbol)
        if buf is None:
            return 50.0

        buf.append(tick_vol)
        if len(buf) < 5:
            return 50.0

        baseline = sum(buf) / len(buf)
        if baseline <= 0:
            return 50.0

        ratio = tick_vol / baseline
        if ratio >= 2.0:   return 95.0
        elif ratio >= 1.5: return 80.0
        elif ratio >= 1.0: return 65.0
        elif ratio >= 0.7: return 50.0
        elif ratio >= 0.5: return 35.0
        return 20.0

    def _is_news_blocked(self, canonical: str, news_events: List) -> bool:
        """
        Check if any high-impact news event is active for this symbol's currencies.
        Uses the same pre/post window as session.py.
        """
        if not news_events:
            return False

        currencies = set(_SYMBOL_CURRENCIES.get(canonical, []))
        if not currencies:
            return False

        now   = datetime.now(timezone.utc)
        pre_m  = settings.session.news_pre_m
        post_m = settings.session.news_post_m

        for event in news_events:
            if getattr(event, "impact", "") != "HIGH":
                continue
            event_currency = getattr(event, "currency", "")
            if event_currency not in currencies:
                continue
            try:
                diff_m = (event.time - now).total_seconds() / 60.0
                if -post_m <= diff_m <= pre_m:
                    return True
            except Exception:
                continue

        return False
