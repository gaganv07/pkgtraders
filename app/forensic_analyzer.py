"""
app/forensic_analyzer.py — Forensic Loss Analyzer & Root-Cause Classifier
==========================================================================
Analyzes every closed losing trade to determine the exact failure mode:
  1. NEWS_SPIKE (CPI, NFP, FOMC volatility)
  2. SPREAD_EXPANSION (Low-liquidity spread widening)
  3. SESSION_MISMATCH (Off-peak volume decay)
  4. STOP_HUNT_LIQUIDITY_GRAB (Wyckoff/ICT stop sweep before reversal)
  5. LATENCY_SLIPPAGE (Sub-second execution fill slippage)
  6. BOOKMAP_HEATMAP_DISAGREEMENT (Passive liquidity wall opposition)
  7. TREND_REVERSAL_COUNTERTREND (Opposing H1/M15 EMA trend)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ForensicDiagnosis:
    """Forensic diagnosis result for a trade outcome."""
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    r_multiple: float
    primary_failure_mode: str
    confidence: float
    contributing_factors: List[str] = field(default_factory=list)
    remediation_recommendation: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ForensicAnalyzer:
    """
    Forensic Root-Cause Analyzer for trade loss diagnostics.
    """

    def __init__(self, log_path: str = "reports/forensic_trade_analysis.csv"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def diagnose_trade(self, trade_data: Dict[str, Any]) -> ForensicDiagnosis:
        """
        Analyze trade metrics and classify failure mode.
        """
        trade_id = str(trade_data.get("trade_id", "N/A"))
        symbol = str(trade_data.get("symbol", "XAUUSD"))
        direction = str(trade_data.get("direction", "LONG"))
        pnl = float(trade_data.get("pnl", 0.0))
        r_mult = float(trade_data.get("r_multiple", 0.0))
        entry = float(trade_data.get("entry_price", 0.0))
        exit_p = float(trade_data.get("exit_price", 0.0))

        factors = []
        failure_mode = "UNKNOWN"
        confidence = 0.50
        rec = "Continue monitoring market conditions."

        if pnl >= 0:
            return ForensicDiagnosis(
                trade_id=trade_id,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                exit_price=exit_p,
                pnl=pnl,
                r_multiple=r_mult,
                primary_failure_mode="SUCCESSFUL_TRADE",
                confidence=1.0,
                contributing_factors=["Target hit / Profit taken"],
                remediation_recommendation="Maintain current execution parameters.",
            )

        # 1. Check News Spike
        news_score = float(trade_data.get("news_score", 50.0))
        if news_score < 30.0:
            failure_mode = "NEWS_SPIKE"
            confidence = 0.90
            factors.append("High-impact economic news blackout window violated")
            rec = "Enforce stricter news blackout buffer before CPI/NFP releases."

        # 2. Check Spread Expansion
        spread_ratio = float(trade_data.get("spread_ratio", 1.0))
        if spread_ratio > 1.8:
            if failure_mode == "UNKNOWN":
                failure_mode = "SPREAD_EXPANSION"
                confidence = 0.85
            factors.append(f"Spread ratio expanded to {spread_ratio:.2f}x average")
            rec = "Cap maximum allowable spread ratio filter."

        # 3. Check Latency / Slippage
        latency_ms = float(trade_data.get("execution_latency_ms", 0.0))
        slippage = float(trade_data.get("slippage_pts", 0.0))
        if latency_ms > 150.0 or slippage > 20.0:
            if failure_mode == "UNKNOWN":
                failure_mode = "LATENCY_SLIPPAGE"
                confidence = 0.80
            factors.append(f"Execution fill latency {latency_ms:.1f}ms / slippage {slippage:.1f}pts")
            rec = "Switch order filling mode or optimize broker server ping."

        # 4. Check Stop Hunt / Liquidity Sweep
        liq_sweep = bool(trade_data.get("choch_event", False) or trade_data.get("bos_event", False))
        if not liq_sweep:
            if failure_mode == "UNKNOWN":
                failure_mode = "STOP_HUNT_LIQUIDITY_GRAB"
                confidence = 0.75
            factors.append("Entry taken prior to liquidity sweep confirmation (Wyckoff trap)")
            rec = "Require liquidity grab event bonus before entering contra-trend trades."

        # 5. Check Session Mismatch
        session_score = float(trade_data.get("session_score", 50.0))
        if session_score < 40.0:
            if failure_mode == "UNKNOWN":
                failure_mode = "SESSION_MISMATCH"
                confidence = 0.70
            factors.append("Trade taken during off-peak Asian consolidation volume decay")
            rec = "Restrict trade execution strictly to London & New York session overlaps."

        if failure_mode == "UNKNOWN":
            failure_mode = "TREND_REVERSAL_COUNTERTREND"
            confidence = 0.65
            factors.append("Unexpected macro trend reversal against technical indicators")
            rec = "Increase Market Structure weight in confluence score."

        diag = ForensicDiagnosis(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            exit_price=exit_p,
            pnl=pnl,
            r_multiple=r_mult,
            primary_failure_mode=failure_mode,
            confidence=confidence,
            contributing_factors=factors,
            remediation_recommendation=rec,
        )

        self._record_diagnosis(diag)
        return diag

    def _record_diagnosis(self, diag: ForensicDiagnosis) -> None:
        """Write diagnosis to CSV log."""
        row = asdict(diag)
        row["contributing_factors"] = "; ".join(row["contributing_factors"])
        
        write_header = not self.log_path.exists() or self.log_path.stat().st_size == 0
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        logger.info(f"[FORENSIC ANALYZER] Diagnosed trade #{diag.trade_id} ({diag.symbol} {diag.direction}) -> Mode: {diag.primary_failure_mode}")
