"""
app/multi_account/account_context.py — Isolated Account Context & Execution State

Encapsulates complete account execution state:
- AccountStatus: Lifecycle state machine enum.
- AccountRiskState: Account-scoped balance, equity, and drawdown metrics.
- AccountExecutionState: Active positions, error state, and fill counters.
- NormalizedSignal: Standardized strategy signal representation.
- TradeExecutionReport: Structured outcome of a trade execution attempt.
- AccountContext: Fully isolated runtime context per MT5 account.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.multi_account.account_registry import AccountConfig, mask_credential
from app.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class AccountStatus(str, Enum):
    """Lifecycle status states for an MT5 account."""
    DISABLED                 = "DISABLED"                   # Account is administratively disabled
    CONNECTING               = "CONNECTING"                 # Connection/handshake in progress
    CONNECTED                = "CONNECTED"                  # Authenticated and verified
    EXECUTION_READY          = "EXECUTION_READY"            # Fully validated and ready to trade
    TRADING                  = "TRADING"                    # Active trading enabled
    PAUSED                   = "PAUSED"                     # Temporarily paused (e.g. news or cooldown)
    DISCONNECTED             = "DISCONNECTED"               # Lost connection to terminal or broker
    ERROR                    = "ERROR"                      # Encountered unexpected operational error
    RISK_LOCKED              = "RISK_LOCKED"                # Drawdown limit or circuit breaker tripped
    AUTH_ERROR               = "AUTH_ERROR"                 # Invalid credentials or read-only password
    ACCOUNT_IDENTITY_MISMATCH = "ACCOUNT_IDENTITY_MISMATCH" # Broker identity does not match config


@dataclass
class NormalizedSignal:
    """
    Normalized signal generated ONCE by the strategy engine,
    then distributed to independent account contexts.
    """
    signal_id: str
    timestamp: datetime
    symbol: str
    direction: str                     # "LONG" | "SHORT"
    entry_reference: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    quality_score: float = 0.0
    atr: float = 0.0
    spread: float = 0.0
    strategy_name: str = "PKGTRADERS"
    strategy_version: str = "2.0.0"
    score_breakdown: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeExecutionReport:
    """Structured result of an account-specific execution attempt."""
    account_id: str
    login: int
    signal_id: str
    symbol: str
    direction: str
    status: str                        # "SUCCESS", "REJECTED", "DISCONNECTED", "INSUFFICIENT_MARGIN", "RISK_LOCKED", "ERROR"
    requested_volume: float = 0.0
    executed_volume: float = 0.0
    requested_price: float = 0.0
    executed_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    ticket: Optional[int] = None
    position_ticket: Optional[int] = None
    magic_number: int = 0
    rejection_reason: str = ""
    error_code: int = 0
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_success(self) -> bool:
        return self.status == "SUCCESS"


@dataclass
class AccountRiskState:
    """Account-specific balance, equity, and drawdown tracker."""
    account_start_balance: float = 0.0
    daily_start_balance:   float = 0.0
    weekly_start_balance:  float = 0.0
    peak_equity:           float = 0.0
    current_balance:       float = 0.0
    current_equity:        float = 0.0
    current_margin:        float = 0.0
    free_margin:           float = 0.0
    margin_level:          float = 0.0
    daily_dd_pct:          float = 0.0
    weekly_dd_pct:         float = 0.0
    account_dd_pct:        float = 0.0
    daily_pnl:             float = 0.0
    consecutive_losses:    int   = 0
    open_risk_pct:         float = 0.0
    circuit_broken:        bool  = False
    cooldown_until:        Optional[datetime] = None


@dataclass
class AccountExecutionState:
    """Account-scoped execution history and positions."""
    open_positions: Dict[int, Any] = field(default_factory=dict)
    processed_signals: set = field(default_factory=set)
    total_trades_count: int = 0
    successful_trades:  int = 0
    rejected_trades:    int = 0
    last_order_time:    Optional[datetime] = None
    last_error:         str = ""
    last_rejection_reason: str = ""
    reconnect_attempts: int = 0
    last_reconnect_ts:  float = 0.0


class AccountContext:
    """
    Isolated execution container for one MT5 account.
    Maintains independent risk manager, connection session, and execution history.
    """

    def __init__(self, config: AccountConfig, mt5_session: Optional[Any] = None):
        self.config = config
        self.session = mt5_session
        self.status = AccountStatus.DISABLED if not config.enabled else AccountStatus.DISCONNECTED
        self.risk_state = AccountRiskState()
        self.exec_state = AccountExecutionState()
        
        # Dedicated, isolated RiskManager instance configured with account-specific limits
        from dataclasses import replace
        self.risk_manager = RiskManager()
        self.risk_manager._cfg = replace(
            self.risk_manager._cfg,
            daily_dd_limit=config.daily_drawdown_limit_pct,
            weekly_dd_limit=config.weekly_drawdown_limit_pct,
            account_dd_limit=config.account_drawdown_limit_pct,
            max_open_trades=config.max_open_trades,
            max_risk_exposure=config.max_risk_exposure_pct,
            risk_per_trade_pct=config.risk_per_trade_pct,
        )
        
        self._lock = threading.RLock()
        self._initialized = False

    @property
    def account_id(self) -> str:
        return self.config.account_id

    @property
    def login(self) -> int:
        return self.config.login

    @property
    def magic_number(self) -> int:
        return self.config.magic_number

    @property
    def dry_run(self) -> bool:
        return self.config.dry_run

    def initialize_risk(self, balance: float) -> None:
        """Initialize the account's isolated RiskManager with its starting capital."""
        with self._lock:
            self.risk_state.account_start_balance = balance
            self.risk_state.daily_start_balance = balance
            self.risk_state.weekly_start_balance = balance
            self.risk_state.peak_equity = balance
            self.risk_state.current_balance = balance
            self.risk_state.current_equity = balance
            self.risk_manager.initialize(balance)
            self._initialized = True
            logger.info(
                f"[{self.account_id}] Initialized risk state with balance=${balance:,.2f}"
            )

    def update_snapshot(
        self,
        balance: float,
        equity: float,
        margin: float = 0.0,
        free_margin: float = 0.0,
        margin_level: float = 0.0,
    ) -> None:
        """Update live account financial metrics."""
        with self._lock:
            if not self._initialized and balance > 0:
                self.initialize_risk(balance)

            self.risk_state.current_balance = balance
            self.risk_state.current_equity = equity
            self.risk_state.current_margin = margin
            self.risk_state.free_margin = free_margin
            self.risk_state.margin_level = margin_level
            self.risk_state.peak_equity = max(self.risk_state.peak_equity, equity)

            # Update the account's isolated RiskManager
            dd_state = self.risk_manager.update_equity(balance, equity)
            self.risk_state.daily_dd_pct = dd_state.daily_dd_pct
            self.risk_state.weekly_dd_pct = dd_state.weekly_dd_pct
            self.risk_state.account_dd_pct = dd_state.account_dd_pct
            self.risk_state.open_risk_pct = dd_state.open_risk_pct

            # Auto-lock if drawdown limit hit
            daily_hit = self.risk_state.daily_dd_pct >= self.config.daily_drawdown_limit_pct
            weekly_hit = self.risk_state.weekly_dd_pct >= self.config.weekly_drawdown_limit_pct
            account_hit = self.risk_state.account_dd_pct >= self.config.account_drawdown_limit_pct

            if dd_state.any_hit or daily_hit or weekly_hit or account_hit:
                if self.status not in (AccountStatus.DISABLED, AccountStatus.ERROR):
                    self.status = AccountStatus.RISK_LOCKED
                    logger.warning(
                        f"[{self.account_id}] Risk limits breached (daily={self.risk_state.daily_dd_pct:.2f}%, limit={self.config.daily_drawdown_limit_pct:.2f}%) — status locked to RISK_LOCKED"
                    )

    def is_trading_allowed(self, symbol: str = "", signal_id: str = "") -> Tuple[bool, str]:
        """
        Evaluate all account-level preconditions before placing a trade:
        1. Master account switch enabled
        2. Account trading enabled
        3. Session mismatch check
        4. Duplicate signal check
        5. Account status active
        6. Symbol restrictions
        7. Open trades limit
        8. Drawdown & circuit breaker checks
        """
        with self._lock:
            if not self.config.enabled:
                return False, f"Account '{self.account_id}' is disabled in configuration"

            if not self.config.trading_enabled:
                return False, f"Trading is administratively disabled for '{self.account_id}'"

            # MT5 session mismatch protection
            if self.session is not None and hasattr(self.session, "config"):
                sess_cfg = getattr(self.session, "config", None)
                if sess_cfg:
                    if sess_cfg.account_id != self.account_id or sess_cfg.login != self.config.login:
                        return False, (
                            f"MT5 account mismatch: context '{self.account_id}' (login {self.config.login}) "
                            f"does not match session '{sess_cfg.account_id}' (login {sess_cfg.login})"
                        )

            # Duplicate signal protection
            if signal_id and signal_id in self.exec_state.processed_signals:
                return False, f"Duplicate signal '{signal_id}' already processed for '{self.account_id}'"

            if self.status == AccountStatus.RISK_LOCKED:
                return False, f"Account '{self.account_id}' is locked due to risk/drawdown limits"

            if self.status == AccountStatus.AUTH_ERROR:
                return False, f"Account '{self.account_id}' has authentication errors"

            if self.status == AccountStatus.ACCOUNT_IDENTITY_MISMATCH:
                return False, f"Account '{self.account_id}' identity verification failed (ACCOUNT_IDENTITY_MISMATCH)"

            if self.status not in (AccountStatus.CONNECTED, AccountStatus.TRADING, AccountStatus.EXECUTION_READY):
                return False, f"Account '{self.account_id}' is not ready for trading (current status: {self.status.value})"

            # Symbol restriction check
            if symbol and self.config.symbols:
                allowed = [s.upper() for s in self.config.symbols]
                clean_sym = symbol.rstrip('m+.a').upper()
                if not any(clean_sym.startswith(s) or s.startswith(clean_sym) for s in allowed):
                    return False, f"Symbol '{symbol}' is not in permitted list for '{self.account_id}'"

            # Check open trades count against account limit
            open_count = len(self.exec_state.open_positions)
            if open_count >= self.config.max_open_trades:
                return False, (
                    f"Max open trades ({self.config.max_open_trades}) reached for '{self.account_id}' "
                    f"(currently {open_count})"
                )

            # Check isolated risk manager gate
            risk_ok, risk_reason = self.risk_manager.approve_with_exposure(
                self.config.risk_per_trade_pct * self.config.risk_multiplier
            )
            if not risk_ok:
                return False, f"Risk gate blocked for '{self.account_id}': {risk_reason}"

            return True, "ALLOWED"

    def record_fill(self, report: TradeExecutionReport) -> None:
        """Update execution state on successful order fill."""
        with self._lock:
            self.exec_state.total_trades_count += 1
            self.exec_state.successful_trades += 1
            self.exec_state.last_order_time = report.timestamp
            if report.signal_id:
                self.exec_state.processed_signals.add(report.signal_id)
            if report.ticket:
                self.exec_state.open_positions[report.ticket] = {
                    "ticket": report.ticket,
                    "symbol": report.symbol,
                    "direction": report.direction,
                    "volume": report.executed_volume,
                    "price": report.executed_price,
                    "sl": report.stop_loss,
                    "tp": report.take_profit,
                    "open_time": report.timestamp,
                    "signal_id": report.signal_id,
                }
            self.risk_manager.on_open(
                risk_pct=self.config.risk_per_trade_pct * self.config.risk_multiplier,
                symbol=report.symbol
            )
            logger.info(
                f"[{self.account_id}] Recorded fill: ticket={report.ticket}, "
                f"vol={report.executed_volume}, price={report.executed_price:.5f}"
            )

    def record_rejection(self, reason: str, error_code: int = 0) -> None:
        """Update execution state on rejected order."""
        with self._lock:
            self.exec_state.total_trades_count += 1
            self.exec_state.rejected_trades += 1
            self.exec_state.last_rejection_reason = reason
            self.exec_state.last_error = f"[{error_code}] {reason}" if error_code else reason
            self.risk_manager.on_exec_failure()
            logger.warning(f"[{self.account_id}] Recorded rejection: {reason}")

    def record_close(self, ticket: int, pnl: float) -> None:
        """Update position and risk state on position close."""
        with self._lock:
            pos = self.exec_state.open_positions.pop(ticket, None)
            symbol = pos.get("symbol", "") if pos else ""
            self.risk_manager.on_close(
                pnl=pnl,
                risk_pct=self.config.risk_per_trade_pct * self.config.risk_multiplier,
                symbol=symbol
            )
            self.risk_state.daily_pnl += pnl
            logger.info(f"[{self.account_id}] Recorded position close: ticket={ticket}, P&L=${pnl:+.2f}")

    def summary(self) -> Dict[str, Any]:
        """Generate a complete diagnostic snapshot of the account."""
        with self._lock:
            return {
                "account_id": self.account_id,
                "login": self.login,
                "server": self.config.server,
                "status": self.status.value,
                "enabled": self.config.enabled,
                "dry_run": self.config.dry_run,
                "magic_number": self.magic_number,
                "balance": round(self.risk_state.current_balance, 2),
                "equity": round(self.risk_state.current_equity, 2),
                "margin": round(self.risk_state.current_margin, 2),
                "free_margin": round(self.risk_state.free_margin, 2),
                "daily_dd_pct": round(self.risk_state.daily_dd_pct, 2),
                "weekly_dd_pct": round(self.risk_state.weekly_dd_pct, 2),
                "account_dd_pct": round(self.risk_state.account_dd_pct, 2),
                "open_trades_count": len(self.exec_state.open_positions),
                "total_trades": self.exec_state.total_trades_count,
                "successful_trades": self.exec_state.successful_trades,
                "rejected_trades": self.exec_state.rejected_trades,
                "last_error": self.exec_state.last_error,
                "last_rejection": self.exec_state.last_rejection_reason,
            }
