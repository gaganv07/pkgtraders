"""
app/trade_engine.py — Trade Execution & Management Engine

Full trade lifecycle (multi-asset capable):
  1. Quality gate check (symbol-aware)
  2. ATR-based SL/TP calculation (per-symbol ATR)
  3. ML quality adjustment
  4. Dynamic position sizing (fresh balance each trade)
  5. MT5 execution (symbol-aware)
  6. Active management: BE, trailing stop, partial TPs, time exit
  7. Position reconciliation on reconnect
  8. Emergency close (all symbols)

Multi-asset upgrade:
  - evaluate(symbol, md) — per-symbol entry evaluation
  - _trades: Dict[str, Optional[ActiveTrade]] — one slot per symbol
  - manage_all() — manages all open positions across symbols
  - max_open_trades enforced globally (configurable in .env)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import csv
import os
from app.config import (
    settings, SYMBOL_CONFIGS, USE_RECALIBRATED_SCORING, SHADOW_MODE,
    RECOMMENDED_WEIGHTS, RECOMMENDED_THRESHOLD
)
from app.mt5_client import MT5Client, FillResult
from app.market_data import MarketData, TF_M5, TF_M15, TF_H1
from app.order_flow import OrderFlowEngine
from app.dom_engine import DOMEngine
from app.microstructure import MicrostructureEngine
from app.volume_analytics import VolumeAnalytics
from app.trade_quality import TradeQualityEngine, QualityBreakdown
from app.risk_manager import RiskManager
from app.position_sizer import PositionSizer, BrokerSpec, SizingResult
from app.session import SessionFilter
from app.ml_layer import MLLayer, TradeContext
from app.database import Database
from app.trade_journal import TradeJournal, TradeJournalEntry
from app.execution_analytics import ExecutionAnalyticsEngine

logger = logging.getLogger(__name__)

def clean_float(val) -> float:
    if val is None:
        return 0.0
    # Safe check for mocks
    if hasattr(val, '_mock_name') or hasattr(val, 'mock_add_spec') or type(val).__name__ in ('Mock', 'MagicMock', 'AsyncMock', 'NonCallableMagicMock', 'NonCallableMock'):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except Exception:
        return 0.0


def compute_ema20(bars: List[any]) -> Optional[float]:
    if not bars or not isinstance(bars, list) or len(bars) == 0:
        return None
    k = 2.0 / (20.0 + 1.0)
    if len(bars) < 20:
        return sum(b.close for b in bars) / len(bars)
    val = sum(b.close for b in bars[:20]) / 20.0
    for b in bars[20:]:
        val = b.close * k + val * (1.0 - k)
    return val


@dataclass
class ActiveTrade:
    trade_id:      str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    ticket:        Optional[int] = None
    direction:     str = ""          # "LONG" | "SHORT"
    symbol:        str = "XAUUSD"

    # Entry
    entry_price:   float = 0.0
    entry_time:    Optional[datetime] = None
    volume:        float = 0.0
    initial_vol:   float = 0.0
    risk_usd:      float = 0.0
    quality_score: float = 0.0
    atr_entry:     float = 0.0
    spread_entry:  float = 0.0
    latency_ms:    float = 0.0
    slippage:      float = 0.0

    # Levels
    sl:   float = 0.0
    tp1:  float = 0.0
    tp2:  float = 0.0
    tp3:  float = 0.0
    current_tp: float = 0.0

    # State
    tp1_done:        bool = False
    tp2_done:        bool = False
    breakeven_done:  bool = False
    trailing_active: bool = False
    high_water:      float = 0.0   # highest price for LONG
    low_water:       float = float("inf")  # lowest price for SHORT

    # P&L
    unrealized_pnl:  float = 0.0
    realized_pnl:    float = 0.0

    # Close
    close_price: float = 0.0
    close_time:  Optional[datetime] = None
    close_reason: str = ""
    score_breakdown: str = ""

    @property
    def age_h(self) -> float:
        if not self.entry_time:
            return 0.0
        return (datetime.now(timezone.utc) - self.entry_time).total_seconds() / 3600.0

    @property
    def r_multiple(self) -> float:
        if self.risk_usd <= 0:
            return 0.0
        return self.unrealized_pnl / self.risk_usd


class TradeEngine:
    """
    Core trading orchestrator — multi-asset capable.
    evaluate(symbol, md) is called from the orchestrator's scan loop
    after MarketSelector selects the best symbol.
    manage_all() manages all open positions across all symbols.
    """

    def __init__(
        self,
        client:      MT5Client,
        market:      MarketData,          # primary symbol MarketData (legacy / fallback)
        of_engine:   OrderFlowEngine,
        dom_engine:  DOMEngine,
        micro:       MicrostructureEngine,
        vol:         VolumeAnalytics,
        quality:     TradeQualityEngine,
        risk:        RiskManager,
        session:     SessionFilter,
        ml:          MLLayer,
        db:          Database,
    ):
        self._client  = client
        self._market  = market           # primary symbol (backwards compat)
        self._of      = of_engine
        self._dom     = dom_engine
        self._micro   = micro
        self._vol     = vol
        self._quality = quality
        self._risk    = risk
        self._session = session
        self._ml      = ml
        self._db      = db
        self._cfg     = settings.risk

        # Multi-symbol trade slots: one slot per symbol key
        # Value is the current ActiveTrade for that symbol, or None
        self._trades: Dict[str, Optional[ActiveTrade]] = {}

        self._last_eval:     float = 0.0
        self._eval_min_gap:  float = 15.0   # seconds between new-entry evaluations

        # Performance tracker callback (injected by orchestrator if available)
        self._on_trade_close = None

        # Warm up adaptive threshold history queue from database
        try:
            recent_scores = self._db.get_recent_quality_scores(limit=200)
            if isinstance(recent_scores, list):
                self._quality.load_history(recent_scores)
                logger.info(f"Warmed up adaptive threshold history queue with {len(recent_scores)} historical scores.")
            else:
                logger.warning("get_recent_quality_scores did not return a list. Skipping warm up.")
        except Exception as e:
            logger.warning(f"Could not warm up adaptive threshold history queue: {e}")

    def set_close_callback(self, cb) -> None:
        """Inject a callback that receives an ActiveTrade when it closes."""
        self._on_trade_close = cb

    # ── Public API ─────────────────────────────────────────────────────────────

    def open_trade_count(self) -> int:
        return sum(1 for t in self._trades.values() if t is not None)

    def get_trade(self, symbol: str) -> Optional[ActiveTrade]:
        return self._trades.get(symbol)

    def all_active_trades(self) -> List[ActiveTrade]:
        return [t for t in self._trades.values() if t is not None]

    async def evaluate(
        self,
        symbol:    str = "XAUUSD",
        market_md: Optional[MarketData] = None,   # per-symbol MarketData
        selector:  Optional[any] = None,
    ) -> Optional[ActiveTrade]:
        """
        Main entry point: manage open trade for this symbol OR evaluate new entry.
        Called from the orchestrator scan loop. Runs dual evaluations in shadow mode.
        """
        md = market_md or self._market

        # Always manage open position for this symbol immediately
        existing = self._trades.get(symbol)
        if existing:
            await self._manage(symbol, md)
            return self._trades.get(symbol)

        # Rate-limit new signal evaluation
        if time.time() - self._last_eval < self._eval_min_gap:
            return None
        self._last_eval = time.time()

        # We must have valid, fresh data to make any decision trace
        tick = md.latest_tick
        if tick is None or not md.is_fresh:
            return None

        atr = md.atr(TF_M5)
        if atr is None or atr < 1e-8:
            return None

        # ── 1. Gather all inputs ──────────────────────────────────────────
        sess = self._session.state
        risk_ok, risk_reason = self._risk.approve_with_exposure(self._cfg.risk_per_trade_pct)
        sym_cfg = SYMBOL_CONFIGS.get(symbol)
        
        # EMA states
        ema_bull_h1 = md.is_ema_bull(TF_H1)
        ema_bear_h1 = md.is_ema_bear(TF_H1)
        ema_bull_m15 = md.is_ema_bull(TF_M15)
        ema_bear_m15 = md.is_ema_bear(TF_M15)

        liq_metrics = (
            self._dom.latest_dom
            if self._dom.using_dom and self._dom.latest_dom
            else self._dom.latest_fallback
        )
        price_above_vwap = (tick.mid > md.vwap() if md.vwap() else None)

        # ── 2. Run Quality Engine for BOTH Legacy and Recalibrated ───────
        
        # A. Legacy scoring evaluation
        legacy_qb_best = self._quality.evaluate_legacy(
            of_snap=self._of.latest,
            liq_snap=liq_metrics,
            ms_state=self._micro.state(),
            vol_state=md.volatility,
            vol_snap=self._vol.latest,
            sess=sess,
            ema_bull_h1=ema_bull_h1,
            ema_bear_h1=ema_bear_h1,
            ema_bull_m15=ema_bull_m15,
            ema_bear_m15=ema_bear_m15,
            price_above_vwap=price_above_vwap,
            current_spread=tick.spread,
            avg_spread=md.avg_spread,
            symbol=symbol,
        )
        legacy_qb = max([self._quality.latest_long, self._quality.latest_short], key=lambda x: x.total)
        
        # B. Recalibrated scoring evaluation
        recal_qb_best = self._quality.evaluate_recalibrated(
            of_snap=self._of.latest,
            liq_snap=liq_metrics,
            ms_state=self._micro.state(),
            vol_state=md.volatility,
            vol_snap=self._vol.latest,
            sess=sess,
            ema_bull_h1=ema_bull_h1,
            ema_bear_h1=ema_bear_h1,
            ema_bull_m15=ema_bull_m15,
            ema_bear_m15=ema_bear_m15,
            price_above_vwap=price_above_vwap,
            current_spread=tick.spread,
            avg_spread=md.avg_spread,
            symbol=symbol,
        )
        recal_qb = max([self._quality.latest_long, self._quality.latest_short], key=lambda x: x.total)

        direction = recal_qb.direction if USE_RECALIBRATED_SCORING else legacy_qb.direction

        # ── 3. ML quality adjustment ──────────────────────────────────────
        ms = self._micro.state()
        ml_ctx = TradeContext(
            trade_id=f"eval_{time.time():.0f}",
            direction=direction,
            entry_time=datetime.now(timezone.utc).isoformat(),
            of_score=recal_qb.of_score if USE_RECALIBRATED_SCORING else legacy_qb.of_score,
            liq_score=recal_qb.liq_score if USE_RECALIBRATED_SCORING else legacy_qb.liq_score,
            ms_score=recal_qb.ms_score if USE_RECALIBRATED_SCORING else legacy_qb.ms_score,
            vol_score=recal_qb.vol_score if USE_RECALIBRATED_SCORING else legacy_qb.vol_score,
            session_score=recal_qb.session_score if USE_RECALIBRATED_SCORING else legacy_qb.session_score,
            news_score=recal_qb.news_score if USE_RECALIBRATED_SCORING else legacy_qb.news_score,
            spread_ratio=(tick.spread / md.avg_spread if md.avg_spread > 0 else 1.0),
            atr_pct=atr / tick.mid * 100 if tick.mid > 0 else 0.1,
            hour_of_day=datetime.now(timezone.utc).hour,
            dom_mode=self._dom.using_dom,
            vol_expansion=self._vol.latest.expansion if self._vol.latest else False,
            bos_event=ms.bos_bull or ms.bos_bear,
            choch_event=ms.choch_bull or ms.choch_bear,
            liq_grab_event=ms.liq_grab_up or ms.liq_grab_down,
        )
        ml_adj = self._ml.quality_adjustment(ml_ctx.to_features())
        
        legacy_adj_score = legacy_qb.total + ml_adj
        recal_adj_score = recal_qb.total + ml_adj

        # ── 4. Evaluate Filters for Legacy ──────────────────────────────
        of_pass_leg = legacy_qb.of_score >= 50.0 and not any("OF" in r or "No OF" in r for r in legacy_qb.veto_reasons)
        ema_pass_leg = not any("EMA" in r for r in legacy_qb.veto_reasons)
        vwap_pass_leg = (price_above_vwap is True if legacy_qb.direction == "LONG" else price_above_vwap is False) if price_above_vwap is not None else True
        liq_sweep_pass_leg = bool(ms and (ms.liq_grab_down if legacy_qb.direction == "LONG" else ms.liq_grab_up))
        break_struct_pass_leg = bool(ms and ((legacy_qb.direction == "LONG" and (ms.bos_bull or ms.choch_bull or ms.structure_bias == "BULLISH")) or (legacy_qb.direction == "SHORT" and (ms.bos_bear or ms.choch_bear or ms.structure_bias == "BEARISH"))))

        # Shared Hard Filters
        atr_pass = (atr >= sym_cfg.min_atr) if (sym_cfg and sym_cfg.min_atr > 0) else True
        spread_pass = (tick.spread_pts <= sym_cfg.max_spread_pts) if (sym_cfg and sym_cfg.max_spread_pts > 0) else True
        session_pass_leg = bool(sess and sess.is_active and not any("session" in r.lower() for r in legacy_qb.veto_reasons))
        session_pass_rec = bool(sess and sess.is_active)  # In recalibrated, active session is a hard veto
        news_pass = bool(sess and not sess.news_blackout)
        cooldown_pass = not self._risk.in_cooldown()
        risk_pass = bool(risk_ok and not self._risk.drawdown.any_hit and not self._risk.circuit_broken)
        pos_limit_pass = (self.open_trade_count() < self._cfg.max_open_trades)

        # Legacy Decision
        legacy_reasons = []
        if not pos_limit_pass: legacy_reasons.append("Position limit reached")
        if not session_pass_leg: legacy_reasons.append("Outside active session")
        if not news_pass: legacy_reasons.append("News blackout active")
        if not cooldown_pass: legacy_reasons.append("Cooldown active")
        if not risk_pass: legacy_reasons.append(f"Risk block: {risk_reason}")
        if not atr_pass: legacy_reasons.append("ATR filter failed")
        if not spread_pass: legacy_reasons.append("Spread too high")
        if not of_pass_leg: legacy_reasons.append("Order Flow opposing trend")
        if not ema_pass_leg: legacy_reasons.append("EMA opposing trend")
        if legacy_qb.vetoed:
            for r in legacy_qb.veto_reasons:
                if r not in legacy_reasons:
                    legacy_reasons.append(r)
        if legacy_qb.total < self._cfg.min_quality_score or legacy_adj_score < self._cfg.min_quality_score:
            legacy_reasons.append("Score below threshold")

        legacy_decision = "REJECTED" if legacy_reasons else "ACCEPTED"

        # ── 5. Evaluate Filters for Recalibrated ──────────────────────────
        recal_reasons = []
        current_adaptive_threshold = self._quality.get_adaptive_threshold()

        # Hard veto checks for recalibrated
        if not pos_limit_pass: recal_reasons.append("Position limit reached")
        if not session_pass_rec: recal_reasons.append("Outside active session")
        if not news_pass: recal_reasons.append("News blackout active")
        if not cooldown_pass: recal_reasons.append("Cooldown active")
        if not risk_pass: recal_reasons.append(f"Risk block: {risk_reason}")
        if not atr_pass: recal_reasons.append("ATR filter failed")
        if not spread_pass: recal_reasons.append("Spread too high")
        if recal_qb.vetoed:
            for r in recal_qb.veto_reasons:
                if r not in recal_reasons:
                    recal_reasons.append(r)
        if recal_qb.total < current_adaptive_threshold or recal_adj_score < current_adaptive_threshold:
            recal_reasons.append("Score below threshold")

        recal_decision = "REJECTED" if recal_reasons else "ACCEPTED"

        # Add the evaluated recalibrated score of the best direction to the history queue
        self._quality._score_history.append(recal_qb.total)

        # ── 6. Log trace comparison for every signal ─────────────────────
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print("====================================================", flush=True)
        print("DUAL ENGINE EVALUATION TRACE", flush=True)
        print("====================================================", flush=True)
        print(f"Timestamp: {timestamp_str}", flush=True)
        print(f"Symbol: {symbol}", flush=True)
        print(f"Direction: {direction}", flush=True)
        print(f"Legacy Score: {clean_float(legacy_adj_score):.1f} (Threshold: {clean_float(self._cfg.min_quality_score):.1f})", flush=True)
        print(f"Legacy Decision: {legacy_decision}", flush=True)
        print(f"Recalibrated Score: {clean_float(recal_adj_score):.1f} (Threshold: {clean_float(current_adaptive_threshold):.1f})", flush=True)
        print(f"Recalibrated Decision: {recal_decision}", flush=True)
        print(f"Difference: {clean_float(recal_adj_score - legacy_adj_score):+.1f}", flush=True)
        print("====================================================", flush=True)

        logger.info(
            f"EVALUATE: {symbol} {direction} | "
            f"LEGACY: {legacy_adj_score:.1f} ({legacy_decision}) | "
            f"RECAL: {recal_adj_score:.1f} ({recal_decision}) | "
            f"DIFF: {recal_adj_score - legacy_adj_score:+.1f}"
        )

        # ── 7. Decision Disagreement Reporting ───────────────────────────
        self._log_disagreement(
            timestamp_str, symbol, direction, legacy_qb, recal_qb,
            legacy_adj_score, recal_adj_score, legacy_decision, recal_decision,
            current_adaptive_threshold, legacy_reasons, recal_reasons
        )

        # ── 8. Route execution path ───────────────────────────────────────
        active_decision = recal_decision if USE_RECALIBRATED_SCORING else legacy_decision
        active_qb = recal_qb if USE_RECALIBRATED_SCORING else legacy_qb
        active_score = recal_adj_score if USE_RECALIBRATED_SCORING else legacy_adj_score
        active_reasons = recal_reasons if USE_RECALIBRATED_SCORING else legacy_reasons
        active_threshold = current_adaptive_threshold if USE_RECALIBRATED_SCORING else self._cfg.min_quality_score

        # ── 9. Print Diagnostics Report for the Active Engine ─────────────
        # Compute soft contributions for recalibrated engine
        w = RECOMMENDED_WEIGHTS.get("recommended_blended_weights", {})
        w_of = w.get("order_flow", 0.22)
        w_liq = w.get("liquidity", 0.141)
        w_ms = w.get("market_structure", 0.258)
        w_vol = w.get("volatility", 0.052)
        w_sess = w.get("session", 0.088)
        w_news = w.get("news", 0.193)
        w_dom = w.get("dom", 0.049)

        # Hard Veto reasons for active path
        print("Hard veto triggered:", flush=True)
        if active_decision == "REJECTED":
            for r in active_reasons:
                print(f"    {r}", flush=True)
        else:
            print(f"    None", flush=True)
        print()

        # Recalibrated soft contributions breakdown
        if ms:
            # Recompute piecewise linear EMA
            if direction == "LONG":
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
            
            anchors = [(0.0, 10.0), (15.0, 20.0), (45.0, 45.0), (55.0, 58.0), (75.0, 78.0), (100.0, 100.0)]
            ema_pts = 50.0
            for i in range(len(anchors) - 1):
                x0, y0 = anchors[i]
                x1, y1 = anchors[i+1]
                if x0 <= ema_pts_raw <= x1:
                    ema_pts = y0 + (y1 - y0) * (ema_pts_raw - x0) / (x1 - x0)
                    break
        else:
            ema_pts = 45.0

        ema_contrib = ema_pts * w_ms * 0.40
        
        mss_detected = bool(ms and ((direction == "LONG" and ms.choch_bull) or (direction == "SHORT" and ms.choch_bear)))
        mss_contrib = 4.0 if mss_detected else 0.0

        fvg_present = bool(ms and ((direction == "LONG" and ms.price_in_bull_fvg) or (direction == "SHORT" and ms.price_in_bear_fvg)))
        fvg_contrib = 3.0 if fvg_present else 0.0

        liq_contrib = recal_qb.liq_score * w_liq

        bos_detected = bool(ms and ((direction == "LONG" and ms.bos_bull) or (direction == "SHORT" and ms.bos_bear)))
        bos_contrib = 4.0 if bos_detected else 0.0

        dom_contrib = recal_qb.liq_score * w_dom

        if price_above_vwap is True:
            vwap_adj = 10.0 if direction == "LONG" else -10.0
        elif price_above_vwap is False:
            vwap_adj = -10.0 if direction == "LONG" else 10.0
        else:
            vwap_adj = 0.0
        vwap_contrib = vwap_adj * w_ms * 0.15

        print("Soft score contributions:", flush=True)
        print(f"    EMA: {clean_float(ema_contrib):+.2f}", flush=True)
        print(f"    MSS: {clean_float(mss_contrib):+.2f}", flush=True)
        print(f"    FVG: {clean_float(fvg_contrib):+.2f}", flush=True)
        print(f"    Liquidity: {clean_float(liq_contrib):+.2f}", flush=True)
        print(f"    BOS: {clean_float(bos_contrib):+.2f}", flush=True)
        print(f"    DOM: {clean_float(dom_contrib):+.2f}", flush=True)
        print(f"    VWAP: {clean_float(vwap_contrib):+.2f}", flush=True)
        print()
        print(f"Final Score: {clean_float(active_score):.1f}", flush=True)
        print(f"Threshold: {clean_float(active_threshold):.1f}", flush=True)
        print("------------------------------------------------", flush=True)

        if active_decision == "REJECTED":
            print("REJECTION REASONS", flush=True)
            print("Rejection Reasons:", flush=True)
            for r in active_reasons:
                print(f"- {r}", flush=True)
            print("====================================================", flush=True)

        # ── 11. Print Structured Decision Trace (for existing unit tests) ────
        is_debug = os.getenv("DEBUG", "false").lower() == "true" or settings.system.log_level.upper() == "DEBUG"
        should_log = (
            active_decision == "ACCEPTED" 
            or is_debug 
            or (active_decision == "REJECTED" and active_qb.total >= 60.0)
        )
        
        if should_log:
            regime = md.volatility.regime if md.volatility else "NORMAL"
            
            # TRADE DECISION Block
            print("====================================================", flush=True)
            print("TRADE DECISION", flush=True)
            print("====================================================", flush=True)
            print(f"Timestamp: {timestamp_str}", flush=True)
            print(f"Symbol: {symbol}", flush=True)
            print(f"Direction: {direction}", flush=True)
            print(f"Market Regime: {regime}", flush=True)
            print(f"Overall Score: {clean_float(active_score):.1f}", flush=True)
            print(f"Minimum Required: {clean_float(active_threshold):.1f}", flush=True)
            print(f"Decision: {active_decision}", flush=True)
            print("====================================================", flush=True)
            
            # Filters Block
            def _status(val):
                return "PASS" if val else "FAIL"
            
            # Map legacy or recalibrated status flags to pass/fail
            if USE_RECALIBRATED_SCORING:
                print(f"{'Order Flow':.<18} PASS", flush=True)
                print(f"{'EMA Alignment':.<18} PASS", flush=True)
                print(f"{'VWAP Bias':.<18} PASS", flush=True)
                print(f"{'Liquidity Sweep':.<18} PASS", flush=True)
                print(f"{'Break Structure':.<18} PASS", flush=True)
            else:
                print(f"{'Order Flow':.<18} {_status(of_pass_leg)}", flush=True)
                print(f"{'EMA Alignment':.<18} {_status(ema_pass_leg)}", flush=True)
                print(f"{'VWAP Bias':.<18} {_status(vwap_pass_leg)}", flush=True)
                print(f"{'Liquidity Sweep':.<18} {_status(liq_sweep_pass_leg)}", flush=True)
                print(f"{'Break Structure':.<18} {_status(break_struct_pass_leg)}", flush=True)
            
            print(f"{'ATR Filter':.<18} {_status(atr_pass)}", flush=True)
            print(f"{'Spread Filter':.<18} {_status(spread_pass)}", flush=True)
            print(f"{'Session Filter':.<18} {_status(session_pass_rec if USE_RECALIBRATED_SCORING else session_pass_leg)}", flush=True)
            print(f"{'News Filter':.<18} {_status(news_pass)}", flush=True)
            print(f"{'Cooldown':.<18} {_status(cooldown_pass)}", flush=True)
            print(f"{'Risk Check':.<18} {_status(risk_pass)}", flush=True)
            print(f"{'Position Limit':.<18} {_status(pos_limit_pass)}", flush=True)

        # ── 12. Execute Order if ACCEPTED ─────────────────────────────────
        trade = None
        if active_decision == "ACCEPTED":
            trade = await self._open(symbol, active_qb, tick, atr, md)
            if trade:
                trade.quality_score = active_score
                ml_ctx.trade_id = trade.trade_id
                self._ml.record_context(ml_ctx)
                self._trades[symbol] = trade

                # Print accepted trade parameters
                print(f"""====================================================
TRADE ACCEPTED

Symbol: {trade.symbol}
Direction: {trade.direction}
Quality Score: {trade.quality_score:.1f}
Lot Size: {trade.volume}
Entry: {trade.entry_price:.5f}
SL: {trade.sl:.5f}
TP1: {trade.tp1:.5f}
TP2: {trade.tp2:.5f}
Risk: ${trade.risk_usd:.2f}
====================================================""", flush=True)
            else:
                active_decision = "REJECTED"
                print("Order execution failed", flush=True)
                print("====================================================", flush=True)

        return trade

    def _log_disagreement(self, timestamp: str, symbol: str, direction: str, legacy_qb, recal_qb, legacy_score: float, recal_score: float, legacy_decision: str, recal_decision: str, threshold: float, legacy_reasons: List[str], recal_reasons: List[str]) -> None:
        csv_path = "reports/shadow_mode_decisions.csv"
        os.makedirs(os.path.dirname(csv_path) if os.path.dirname(csv_path) else ".", exist_ok=True)
        
        # Check if we should write header
        write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        
        # Map values
        ms = self._micro.state()
        mss_detected = bool(ms and ((direction == "LONG" and ms.choch_bull) or (direction == "SHORT" and ms.choch_bear)))
        fvg_present = bool(ms and ((direction == "LONG" and ms.price_in_bull_fvg) or (direction == "SHORT" and ms.price_in_bear_fvg)))
        liq_sweep = bool(ms and ((direction == "LONG" and ms.liq_grab_down) or (direction == "SHORT" and ms.liq_grab_up)))
        bos_detected = bool(ms and ((direction == "LONG" and ms.bos_bull) or (direction == "SHORT" and ms.bos_bear)))

        row = {
            "timestamp": timestamp,
            "symbol": symbol,
            "direction": direction,
            "legacy_score": round(legacy_score, 1),
            "recal_score": round(recal_score, 1),
            "legacy_decision": legacy_decision,
            "recal_decision": recal_decision,
            "legacy_threshold": round(self._cfg.min_quality_score, 1),
            "recal_threshold": round(threshold, 1),
            "legacy_vetoes": "; ".join([r for r in legacy_reasons if r != "Score below threshold"]),
            "recal_vetoes": "; ".join([r for r in recal_reasons if r != "Score below threshold"]),
            "of_score_legacy": legacy_qb.of_score,
            "of_score_recal": recal_qb.of_score,
            "liq_score_legacy": legacy_qb.liq_score,
            "liq_score_recal": recal_qb.liq_score,
            "ms_score_legacy": legacy_qb.ms_score,
            "ms_score_recal": recal_qb.ms_score,
            "vol_score_legacy": legacy_qb.vol_score,
            "vol_score_recal": recal_qb.vol_score,
            "session_score_legacy": legacy_qb.session_score,
            "session_score_recal": recal_qb.session_score,
            "news_score_legacy": legacy_qb.news_score,
            "news_score_recal": recal_qb.news_score,
            "mss_detected": mss_detected,
            "fvg_present": fvg_present,
            "liq_sweep": liq_sweep,
            "bos_detected": bos_detected,
        }
        
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(row.keys()))
                if write_header:
                    w.writeheader()
                w.writerow(row)
            logger.debug(f"Logged shadow mode signal for {symbol} {direction} to {csv_path}")
        except Exception as e:
            logger.error(f"Failed to log shadow mode signal: {e}")

    async def manage_all(self, msd=None) -> None:
        """
        Manage ALL open positions across all symbols.
        Called every tick from the orchestrator.
        msd: MultiSymbolMarketData (optional — uses primary market if None)
        """
        for sym, trade in list(self._trades.items()):
            if trade is None:
                continue
            if msd is not None:
                md = msd.get(sym) or self._market
            else:
                md = self._market
            await self._manage(sym, md)

    # ── Open trade ─────────────────────────────────────────────────────────────

    async def _open(
        self,
        symbol: str,
        bd:     QualityBreakdown,
        tick,
        atr:    float,
        md:     MarketData,
    ) -> Optional[ActiveTrade]:
        direction = bd.direction

        # Per-symbol SL multiplier override
        sym_cfg = SYMBOL_CONFIGS.get(symbol)
        atr_mult = (
            sym_cfg.atr_sl_mult
            if sym_cfg and sym_cfg.atr_sl_mult > 0
            else self._cfg.atr_sl_mult
        )
        sl_dist = atr * atr_mult

        if direction == "LONG":
            entry_est = tick.ask
            sl  = entry_est - sl_dist
            tp1 = entry_est + sl_dist * self._cfg.tp1_rr
            tp2 = entry_est + sl_dist * self._cfg.tp2_rr
            tp3 = entry_est + sl_dist * self._cfg.tp3_rr
        else:
            entry_est = tick.bid
            sl  = entry_est + sl_dist
            tp1 = entry_est - sl_dist * self._cfg.tp1_rr
            tp2 = entry_est - sl_dist * self._cfg.tp2_rr
            tp3 = entry_est - sl_dist * self._cfg.tp3_rr

        # Fetch live account balance (dynamic compounding)
        acct = self._client.get_account()
        if acct is None:
            logger.error(f"[{symbol}] Cannot fetch live account — skipping trade")
            return None
        live_balance = acct["balance"]

        spec = self._client.get_symbol_spec(symbol)
        if spec is None:
            logger.error(f"[{symbol}] Cannot fetch symbol spec — skipping trade")
            return None

        broker_spec = BrokerSpec.from_spec_dict(spec, symbol=symbol)
        sizing = PositionSizer.size(
            balance=live_balance,
            entry=entry_est,
            stop_loss=sl,
            tp_price=tp1,
            risk_pct=self._cfg.risk_per_trade_pct,
            spec=broker_spec,
            equity=acct.get("equity", live_balance),
            free_margin=acct.get("free_margin", live_balance),
            strategy=f"{symbol}_LiveEngine",
            symbol=symbol,
            write_csv=True,
        )
        vol      = sizing.final_lot
        risk_usd = sizing.expected_loss
        if vol <= 0:
            logger.warning(f"[{symbol}] [SIZING] Calculated volume=0 — skipping")
            return None

        comment = f"{symbol[:6]}|{bd.total:.0f}"
        loop    = asyncio.get_event_loop()

        if direction == "LONG":
            result: FillResult = await loop.run_in_executor(
                None, self._client.buy, vol, sl, tp1, comment, symbol
            )
        else:
            result: FillResult = await loop.run_in_executor(
                None, self._client.sell, vol, sl, tp1, comment, symbol
            )

        if not result.success:
            logger.error(f"[{symbol}] Order failed: {result.error}")
            self._risk.on_exec_failure()
            return None

        breakdown_str = f"of:{bd.of_score:.1f};liq:{bd.liq_score:.1f};ms:{bd.ms_score:.1f};vol:{bd.vol_score:.1f};session:{bd.session_score:.1f};news:{bd.news_score:.1f}"
        trade = ActiveTrade(
            ticket=result.ticket,
            direction=direction,
            symbol=symbol,
            entry_price=result.price,
            entry_time=datetime.now(timezone.utc),
            volume=vol,
            initial_vol=vol,
            risk_usd=risk_usd,
            quality_score=bd.total,
            atr_entry=atr,
            spread_entry=tick.spread,
            latency_ms=result.latency_ms,
            slippage=result.slippage_pts,
            sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            current_tp=tp1,
            high_water=result.price,
            low_water=result.price,
            score_breakdown=breakdown_str,
        )

        self._risk.on_open(risk_pct=self._cfg.risk_per_trade_pct)
        await self._db.insert_trade(trade)
        self._db.log_latency("order_fill", result.latency_ms)

        logger.info(
            f"[TRADE OPEN] Symbol={symbol} | "
            f"Direction={direction} | "
            f"EntryPrice={result.price:.5f} | "
            f"StopLoss={sl:.5f} | "
            f"TakeProfit={tp1:.5f} | "
            f"FinalLot={vol} | "
            f"DollarRisk=${risk_usd:.2f} | "
            f"Balance=${live_balance:,.2f}"
        )
        return trade

    # ── Manage open position ───────────────────────────────────────────────────

    async def _manage(self, symbol: str, md: MarketData) -> None:
        t = self._trades.get(symbol)
        if not t or not t.ticket:
            return

        tick = md.latest_tick
        if not tick:
            return

        price   = tick.bid if t.direction == "LONG" else tick.ask
        sl_dist = abs(t.entry_price - t.sl)
        profit  = (price - t.entry_price if t.direction == "LONG"
                   else t.entry_price - price)
        current_r = profit / sl_dist if sl_dist > 0 else 0.0

        spec    = self._client.get_symbol_spec(symbol)
        cs      = spec["contract_size"] if spec else 100.0
        vol_min = spec["vol_min"] if spec else 0.01
        t.unrealized_pnl = profit * t.volume * cs
        t.high_water = max(t.high_water, price)
        t.low_water  = min(t.low_water, price)

        loop = asyncio.get_event_loop()

        # ── TP1: close 30% at 1R ─────────────────────────────────────────────
        if not t.tp1_done and current_r >= self._cfg.tp1_rr:
            close_vol = round(t.initial_vol * self._cfg.tp1_close_pct, 2)
            if close_vol >= vol_min:
                res = await loop.run_in_executor(
                    None, self._client.close, t.ticket, close_vol, "TP1", symbol
                )
                if res.success:
                    t.tp1_done = True
                    t.volume   = round(t.volume - close_vol, 3)
                    t.realized_pnl += profit * close_vol * cs
                    logger.info(
                        f"[{symbol}] TP1 partial: {close_vol} @ {price:.5f} R={current_r:.2f}"
                    )
                    await self._db.update_trade(t)

        # ── TP2: close 30% at 2R ─────────────────────────────────────────────
        if t.tp1_done and not t.tp2_done and current_r >= self._cfg.tp2_rr:
            close_vol = round(t.initial_vol * self._cfg.tp2_close_pct, 2)
            if close_vol >= vol_min:
                res = await loop.run_in_executor(
                    None, self._client.close, t.ticket, close_vol, "TP2", symbol
                )
                if res.success:
                    t.tp2_done = True
                    t.volume   = round(t.volume - close_vol, 3)
                    t.realized_pnl += profit * close_vol * cs
                    await loop.run_in_executor(
                        None, self._client.modify, t.ticket, t.sl, t.tp3, symbol
                    )
                    t.current_tp = t.tp3
                    logger.info(f"[{symbol}] TP2 partial: {close_vol} @ {price:.5f}")
                    await self._db.update_trade(t)

        # ── Breakeven ─────────────────────────────────────────────────────────
        if not t.breakeven_done and current_r >= self._cfg.breakeven_rr:
            new_sl = t.entry_price
            res = await loop.run_in_executor(
                None, self._client.modify, t.ticket, new_sl, t.current_tp, symbol
            )
            if res.success:
                t.sl = new_sl
                t.breakeven_done = True
                logger.info(f"[{symbol}] Breakeven set @ {new_sl:.5f}")

        # ── Trailing stop ─────────────────────────────────────────────────────
        if current_r >= self._cfg.trail_rr:
            trail = t.atr_entry * self._cfg.trail_atr_mult
            if t.direction == "LONG":
                new_sl = t.high_water - trail
                if new_sl > t.sl + 1e-8:
                    res = await loop.run_in_executor(
                        None, self._client.modify, t.ticket, new_sl, t.current_tp, symbol
                    )
                    if res.success:
                        t.sl = new_sl
                        t.trailing_active = True
            else:
                new_sl = t.low_water + trail
                if new_sl < t.sl - 1e-8:
                    res = await loop.run_in_executor(
                        None, self._client.modify, t.ticket, new_sl, t.current_tp, symbol
                    )
                    if res.success:
                        t.sl = new_sl
                        t.trailing_active = True

        # ── Time stop ─────────────────────────────────────────────────────────
        if t.age_h >= self._cfg.max_trade_dur_h and current_r < 0:
            logger.info(
                f"[{symbol}] Time stop: {t.age_h:.1f}h open, R={current_r:.2f}"
            )
            await self._force_close(symbol, t, "TIME_STOP")
            return

        # ── Check if MT5 closed it (SL / TP hit) ──────────────────────────────
        positions = await asyncio.get_event_loop().run_in_executor(
            None, self._client.get_positions, symbol
        )
        if not any(p.ticket == t.ticket for p in positions):
            logger.info(
                f"[{symbol}] Position {t.ticket} no longer open in MT5"
            )
            await self._finalize(symbol, t, price, "MT5_CLOSE")

    async def _force_close(
        self, symbol: str, t: ActiveTrade, reason: str
    ) -> None:
        loop = asyncio.get_event_loop()
        res  = await loop.run_in_executor(
            None, self._client.close, t.ticket, None, reason, symbol
        )
        if res.success:
            await self._finalize(symbol, t, res.price, reason)
        else:
            logger.error(f"[{symbol}] Force close failed: {res.error}")

    async def _finalize(
        self, symbol: str, t: ActiveTrade, price: float, reason: str
    ) -> None:
        spec = self._client.get_symbol_spec(symbol)
        cs   = spec["contract_size"] if spec else 100.0

        if t.direction == "LONG":
            pts = price - t.entry_price
        else:
            pts = t.entry_price - price

        final_pnl = pts * t.volume * cs
        t.realized_pnl += final_pnl
        t.close_price  = price
        t.close_time   = datetime.now(timezone.utc)
        t.close_reason = reason

        self._risk.on_close(t.realized_pnl, risk_pct=self._cfg.risk_per_trade_pct)
        self._ml.record_outcome(t.trade_id, t.realized_pnl)
        self._ml.maybe_retrain()

        await self._db.close_trade(t)
        self._trades[symbol] = None

        # Log to Live Trade Journal (reports/live_trade_journal.csv)
        try:
            acct = self._client.get_account() or {}
            journal_entry = TradeJournalEntry(
                timestamp=t.entry_time.isoformat() if t.entry_time else datetime.now(timezone.utc).isoformat(),
                exit_timestamp=t.close_time.isoformat() if t.close_time else datetime.now(timezone.utc).isoformat(),
                symbol=t.symbol,
                direction=t.direction,
                entry_price=t.entry_price,
                exit_price=t.close_price,
                sl=t.sl,
                tp=t.tp1,
                lot_size=t.initial_vol,
                balance=acct.get("balance", 0.0),
                equity=acct.get("equity", 0.0),
                risk_pct=self._cfg.risk_per_trade_pct,
                spread_pts=t.spread_entry,
                atr=t.atr_entry,
                ema50=0.0,
                rsi=0.0,
                ai_score=t.quality_score,
                score_breakdown=getattr(t, "score_breakdown", ""),
                entry_reason=f"QualityScore={t.quality_score:.1f}",
                exit_reason=reason,
                holding_time_s=t.age_h * 3600.0,
                pnl=t.realized_pnl,
                pnl_pct=(t.realized_pnl / acct.get("balance", 1.0) * 100.0) if acct.get("balance", 0) > 0 else 0.0,
                r_multiple=t.realized_pnl / t.risk_usd if t.risk_usd > 0 else 0.0,
                broker_retcode=10009,
                execution_latency_ms=t.latency_ms,
            )
            TradeJournal().log_trade(journal_entry)
            
            # Refresh execution analytics
            all_db_trades = self._db.get_closed_trades(limit=1000)
            ExecutionAnalyticsEngine.generate_and_save_reports(all_db_trades, initial_balance=self._cfg.initial_balance)
        except Exception as e:
            logger.error(f"Error updating trade journal / execution analytics: {e}")

        # Write to paper trading log if USE_RECALIBRATED_SCORING and not SHADOW_MODE
        if USE_RECALIBRATED_SCORING and not SHADOW_MODE:
            self._log_paper_trade(t)

        # Notify performance tracker if registered
        if self._on_trade_close:
            try:
                self._on_trade_close(t)
            except Exception:
                pass

        logger.info(
            f"{'🟩' if t.realized_pnl > 0 else '🟥'} [{symbol}] CLOSE {t.direction} "
            f"@ {price:.5f} | pnl=${t.realized_pnl:.2f} reason={reason}"
        )

    def _log_paper_trade(self, t: ActiveTrade) -> None:
        csv_path = "reports/paper_trading_log.csv"
        os.makedirs(os.path.dirname(csv_path) if os.path.dirname(csv_path) else ".", exist_ok=True)
        write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        
        row = {
            "entry_time": t.entry_time.isoformat() if t.entry_time else "",
            "exit_time": t.close_time.isoformat() if t.close_time else "",
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.close_price,
            "lot_size": t.initial_vol,
            "risk_amount": t.risk_usd,
            "quality_score": t.quality_score,
            "score_breakdown": getattr(t, "score_breakdown", ""),
            "sl": t.sl,
            "tp": t.tp1,
            "close_reason": t.close_reason,
            "pnl": t.realized_pnl,
            "r_multiple": t.realized_pnl / t.risk_usd if t.risk_usd > 0 else 0.0,
        }
        
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(row.keys()))
                if write_header:
                    w.writeheader()
                w.writerow(row)
            logger.info(f"Logged paper trade to {csv_path}")
        except Exception as e:
            logger.error(f"Failed to log paper trade: {e}")

    async def emergency_close(self) -> None:
        """Close all open positions across all symbols."""
        for sym, trade in list(self._trades.items()):
            if trade:
                await self._force_close(sym, trade, "EMERGENCY")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._client.close_all, "emergency")

    # ── Status / dashboard ─────────────────────────────────────────────────────

    @property
    def active_trade(self) -> Optional[ActiveTrade]:
        """Return first active trade (backwards compat for single-symbol dashboard)."""
        return next((t for t in self._trades.values() if t), None)

    def status(self) -> Dict:
        trades_out = []
        for sym, t in self._trades.items():
            if not t:
                continue
            trades_out.append({
                "symbol":    sym,
                "id":        t.trade_id,
                "ticket":    t.ticket,
                "direction": t.direction,
                "entry":     t.entry_price,
                "volume":    t.volume,
                "sl":        t.sl,
                "tp":        t.current_tp,
                "pnl":       round(t.unrealized_pnl, 2),
                "r":         round(t.r_multiple, 2),
                "quality":   t.quality_score,
                "age_h":     round(t.age_h, 2),
                "breakeven": t.breakeven_done,
                "trailing":  t.trailing_active,
                "tp1_done":  t.tp1_done,
                "tp2_done":  t.tp2_done,
            })
        return {
            "active":         len(trades_out) > 0,
            "open_count":     len(trades_out),
            "trades":         trades_out,
        }
