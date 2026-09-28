"""
app/multi_account — PKGTRADERS Multi-Account Architecture Package

Provides:
- AccountConfig, AccountRegistry
- AccountContext, AccountStatus, NormalizedSignal
- IMT5Session, MT5DirectSession, MT5ProcessSession
- AccountWorker
- MT5AccountManager
"""

from __future__ import annotations

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import (
    AccountContext,
    AccountStatus,
    AccountRiskState,
    AccountExecutionState,
    NormalizedSignal,
    TradeExecutionReport,
)
from app.multi_account.mt5_session import (
    IMT5Session,
    MT5DirectSession,
    MT5ProcessSession,
    create_session,
)
from app.multi_account.account_worker import AccountWorker
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.multi_account_api import (
    router as multi_account_router,
    set_api_account_manager,
    get_account_manager,
)

from app.multi_account.terminal_supervisor import (
    TerminalSupervisor,
    IdentityHandshakeResult,
    get_terminal_supervisor,
)

__all__ = [
    "AccountConfig",
    "AccountRegistry",
    "AccountContext",
    "AccountStatus",
    "AccountRiskState",
    "AccountExecutionState",
    "NormalizedSignal",
    "TradeExecutionReport",
    "IMT5Session",
    "MT5DirectSession",
    "MT5ProcessSession",
    "create_session",
    "AccountWorker",
    "MT5AccountManager",
    "multi_account_router",
    "set_api_account_manager",
    "get_account_manager",
    "TerminalSupervisor",
    "IdentityHandshakeResult",
    "get_terminal_supervisor",
]

