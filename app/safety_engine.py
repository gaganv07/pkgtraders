"""
app/safety_engine.py — Consolidated Safety Engine

Enforces global pre-trade and in-flight safety checks:
- Daily drawdown & account drawdown limits
- Consecutive loss streak circuit breaker
- Maximum simultaneous open trades limit
- Symbol risk exposure & total account risk exposure limits
- Spread spike filter
- News blackout filter
- Weekend & market closed protection
- Emergency stop safety override
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SafetyCheckResult:
    passed: bool
    reason: str = "Passed"
    code: str = "OK"


class SafetyEngine:
    """
    Central safety validator for order execution and system operational limits.
    """

    def __init__(self, risk_manager: Any, session_filter: Any, symbol_manager: Any):
        self.risk = risk_manager
        self.session = session_filter
        self.symbol_manager = symbol_manager

    def evaluate_pre_trade_safety(
        self,
        symbol: str,
        requested_risk_pct: float = 1.0,
        current_spread_pts: float = 0.0,
        max_spread_pts: float = 100.0,
        open_trade_count: int = 0,
        max_open_trades: int = 3,
    ) -> SafetyCheckResult:
        """
        Run comprehensive safety checks prior to executing a new trade.
        """

        # 1. Emergency stop / circuit breaker
        if hasattr(self.risk, "circuit_broken") and self.risk.circuit_broken:
            return SafetyCheckResult(
                passed=False,
                reason="Circuit breaker activated due to consecutive losses or execution failures",
                code="CIRCUIT_BREAKER",
            )

        # 2. Drawdown limits
        if hasattr(self.risk, "drawdown"):
            dd = self.risk.drawdown
            if getattr(dd, "daily_hit", False):
                return SafetyCheckResult(
                    passed=False,
                    reason=f"Daily drawdown limit breached ({dd.daily_dd_pct:.2f}%)",
                    code="DAILY_DD_LIMIT",
                )
            if getattr(dd, "account_hit", False):
                return SafetyCheckResult(
                    passed=False,
                    reason=f"Account drawdown limit breached ({dd.account_dd_pct:.2f}%)",
                    code="ACCOUNT_DD_LIMIT",
                )

        # 3. Maximum simultaneous open trades
        if open_trade_count >= max_open_trades:
            return SafetyCheckResult(
                passed=False,
                reason=f"Maximum simultaneous open trades reached ({open_trade_count}/{max_open_trades})",
                code="MAX_OPEN_TRADES",
            )

        # 4. Total Risk Exposure Check
        risk_ok, risk_msg = self.risk.approve_with_exposure(requested_risk_pct)
        if not risk_ok:
            return SafetyCheckResult(
                passed=False,
                reason=f"Total risk exposure limit exceeded: {risk_msg}",
                code="RISK_EXPOSURE_LIMIT",
            )

        # 5. Symbol Tradeable & Market Open Check
        is_open, open_msg = self.symbol_manager.verify_symbol_tradeable(symbol)
        if not is_open:
            return SafetyCheckResult(
                passed=False,
                reason=f"Market closed or disabled for {symbol}: {open_msg}",
                code="MARKET_CLOSED",
            )

        # 6. Spread Spike Filter
        if max_spread_pts > 0 and current_spread_pts > max_spread_pts:
            return SafetyCheckResult(
                passed=False,
                reason=f"Spread spike detected for {symbol}: Current={current_spread_pts:.1f} pts, Max={max_spread_pts:.1f} pts",
                code="SPREAD_SPIKE",
            )

        # 7. News Blackout Filter
        if hasattr(self.session, "state") and self.session.state:
            if getattr(self.session.state, "news_blackout", False):
                return SafetyCheckResult(
                    passed=False,
                    reason="High-impact news blackout period active",
                    code="NEWS_BLACKOUT",
                )

        # 8. Weekend Protection (Friday 21:00 UTC onwards)
        now_utc = datetime.now(timezone.utc)
        if now_utc.weekday() == 4 and now_utc.hour >= 21:
            return SafetyCheckResult(
                passed=False,
                reason="Weekend protection active — no new trades before market close",
                code="WEEKEND_PROTECTION",
            )

        return SafetyCheckResult(passed=True, reason="Passed all pre-trade safety checks", code="OK")
