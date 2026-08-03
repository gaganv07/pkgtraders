"""
app/account_manager.py — Account Manager & Health Module

Provides account state retrieval, real-time margin tracking, equity monitoring,
and account health verification against risk thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class AccountSnapshot:
    login: int
    company: str
    server: str
    currency: str
    leverage: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    profit: float
    trade_allowed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "login": self.login,
            "company": self.company,
            "server": self.server,
            "currency": self.currency,
            "leverage": self.leverage,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "margin": round(self.margin, 2),
            "free_margin": round(self.free_margin, 2),
            "margin_level": round(self.margin_level, 1),
            "profit": round(self.profit, 2),
            "trade_allowed": self.trade_allowed,
        }


class AccountManager:
    """
    Manages account state retrieval, margin safety, and health validation.
    """

    def __init__(self):
        self._initial_balance: Optional[float] = None
        self._peak_equity: float = 0.0

    def get_account_snapshot(self) -> Optional[AccountSnapshot]:
        """Fetch current account snapshot directly from MT5."""
        if not MT5_AVAILABLE:
            return None

        info = mt5.account_info()
        if info is None:
            code, msg = mt5.last_error()
            logger.error(f"Failed to fetch account_info: [{code}] {msg}")
            return None

        if self._initial_balance is None:
            self._initial_balance = info.balance

        self._peak_equity = max(self._peak_equity, info.equity)

        return AccountSnapshot(
            login=info.login,
            company=info.company,
            server=info.server,
            currency=info.currency,
            leverage=info.leverage,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            margin_level=info.margin_level,
            profit=info.profit,
            trade_allowed=info.trade_allowed,
        )

    def verify_margin_available(self, required_margin: float) -> Tuple[bool, str]:
        """Verify if free margin is sufficient for order placement."""
        snap = self.get_account_snapshot()
        if snap is None:
            return False, "Could not retrieve account info for margin check"

        if snap.free_margin < required_margin:
            return (
                False,
                f"Insufficient free margin: Required={required_margin:.2f}, Available={snap.free_margin:.2f}",
            )

        return True, "Margin check passed"

    def is_account_healthy(
        self,
        min_margin_level: float = 200.0,
        max_equity_drawdown_pct: float = 15.0,
    ) -> Tuple[bool, str]:
        """
        Evaluate overall account health:
        - Check margin level %
        - Check peak equity drawdown %
        - Check trade permission
        """
        snap = self.get_account_snapshot()
        if snap is None:
            return False, "Unable to verify account health (MT5 disconnected)"

        if not snap.trade_allowed:
            return False, "Account trading disabled by broker"

        # Check margin level (if margin > 0)
        if snap.margin > 0 and snap.margin_level < min_margin_level:
            return (
                False,
                f"Margin level critically low: {snap.margin_level:.1f}% (Minimum: {min_margin_level:.1f}%)",
            )

        # Check peak drawdown
        if self._peak_equity > 0:
            dd_pct = ((self._peak_equity - snap.equity) / self._peak_equity) * 100.0
            if dd_pct > max_equity_drawdown_pct:
                return (
                    False,
                    f"Account drawdown limits breached: {dd_pct:.2f}% (Limit: {max_equity_drawdown_pct:.2f}%)",
                )

        return True, "Account health checks passed"
