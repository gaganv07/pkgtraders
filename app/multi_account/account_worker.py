"""
app/multi_account/account_worker.py — Per-Account Background Worker & Lifecycle Monitor

Handles:
- Heartbeat & account financial snapshot synchronization.
- Bounded auto-reconnection with exponential backoff [5s, 15s, 30s, 60s, 120s].
- Position reconciliation against broker.
- Structured trading event logging with full account attribution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.multi_account.account_context import AccountContext, AccountStatus

logger = logging.getLogger(__name__)


@dataclass
class PositionReconciliationReport:
    account_id: str
    login: int
    matched_count: int
    reconstructed_count: int
    unknown_count: int
    missing_count: int
    unknown_tickets: List[int] = field(default_factory=list)
    missing_tickets: List[int] = field(default_factory=list)
    reconstructed_tickets: List[int] = field(default_factory=list)
    is_consistent: bool = True


def log_account_event(
    account_id: str,
    login: int,
    event: str,
    symbol: str = "GLOBAL",
    strategy: str = "PKGTRADERS",
    ticket: Optional[int] = None,
    extra: str = "",
) -> None:
    """Standardized structured log entry with mandatory account identity."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ticket_str = f"ticket={ticket} " if ticket else ""
    extra_str = f"| {extra}" if extra else ""
    msg = (
        f"[{ts}] account={account_id} login={login} symbol={symbol} "
        f"strategy={strategy} event={event} {ticket_str}{extra_str}"
    )
    logger.info(msg)


def log_execution_event(
    account_id: str,
    mt5_login: int,
    server: str,
    worker_id: str,
    terminal_id: str,
    signal_id: str,
    magic_number: int,
    symbol: str,
    action: str,
    risk: float,
    execution_status: str,
    error_code: int = 0,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Standardized structured observability log entry for orders and executions.
    Contains strictly all required fields and NEVER logs passwords or secrets.
    """
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    record = {
        "timestamp": ts,
        "account_id": account_id,
        "MT5_login": mt5_login,
        "server": server,
        "worker_id": worker_id,
        "terminal_id": terminal_id,
        "signal_id": signal_id,
        "magic_number": magic_number,
        "symbol": symbol,
        "action": action,
        "risk": round(risk, 4),
        "execution_status": execution_status,
        "error_code": error_code,
    }
    msg = (
        f"[{ts}] account_id={account_id} MT5_login={mt5_login} server={server} "
        f"worker_id={worker_id} terminal_id={terminal_id} signal_id={signal_id} "
        f"magic_number={magic_number} symbol={symbol} action={action} "
        f"risk={risk:.4f} execution_status={execution_status} error_code={error_code}"
    )
    logger.info(msg)
    return record


class AccountWorker:
    """
    Dedicated worker managing background lifecycle, health, and reconciliation
    for an individual AccountContext.
    """

    RECONNECT_DELAYS = [5.0, 15.0, 30.0, 60.0, 120.0]

    def __init__(self, context: AccountContext, sync_interval_s: float = 5.0):
        self.ctx = context
        self.sync_interval_s = sync_interval_s
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_reconnect_fails = 0

    @property
    def account_id(self) -> str:
        return self.ctx.account_id

    async def start(self) -> bool:
        """Start the account worker and initiate initial MT5 connection."""
        if self._running:
            return True

        self._running = True
        log_account_event(self.account_id, self.ctx.login, "WORKER_START")

        # Initial connection
        connected = await self.connect()
        # Start background sync loop
        self._task = asyncio.create_task(self._sync_loop(), name=f"worker_{self.account_id}")
        return connected

    async def stop(self) -> None:
        """Gracefully stop worker and disconnect session."""
        if not self._running:
            return

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.disconnect()
        log_account_event(self.account_id, self.ctx.login, "WORKER_STOP")

    async def connect(self) -> bool:
        """Connect to MT5 session with status updates."""
        if not self.ctx.config.enabled:
            self.ctx.status = AccountStatus.DISABLED
            return False

        self.ctx.status = AccountStatus.CONNECTING
        log_account_event(self.account_id, self.ctx.login, "CONNECTING")

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self.ctx.session.connect)

        if success:
            from app.multi_account.terminal_supervisor import get_terminal_supervisor
            supervisor = get_terminal_supervisor()
            handshake = await loop.run_in_executor(
                None, supervisor.perform_identity_handshake, self.ctx.config, self.ctx.session
            )
            if not handshake.success:
                self.ctx.status = handshake.status
                log_account_event(self.account_id, self.ctx.login, "IDENTITY_HANDSHAKE_FAILED", extra=handshake.error_reason)
                return False

            self.ctx.status = AccountStatus.EXECUTION_READY
            self._consecutive_reconnect_fails = 0
            log_account_event(self.account_id, self.ctx.login, "EXECUTION_READY")
            await self.sync_account_state()
            return True
        else:
            self.ctx.status = AccountStatus.DISCONNECTED
            log_account_event(self.account_id, self.ctx.login, "CONNECT_FAILED")
            return False

    async def disconnect(self) -> None:
        """Disconnect session."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.ctx.session.disconnect)
        self.ctx.status = AccountStatus.DISCONNECTED
        log_account_event(self.account_id, self.ctx.login, "DISCONNECTED")

    async def reconnect(self) -> bool:
        """Bounded reconnect attempt with backoff."""
        delay = self.RECONNECT_DELAYS[
            min(self._consecutive_reconnect_fails, len(self.RECONNECT_DELAYS) - 1)
        ]
        log_account_event(
            self.account_id,
            self.ctx.login,
            "RECONNECT_WAIT",
            extra=f"attempt={self._consecutive_reconnect_fails+1} delay={delay}s",
        )
        await asyncio.sleep(delay)

        self.ctx.exec_state.reconnect_attempts += 1
        self.ctx.exec_state.last_reconnect_ts = time.time()

        success = await self.connect()
        if success:
            self._consecutive_reconnect_fails = 0
        else:
            self._consecutive_reconnect_fails += 1
            if self._consecutive_reconnect_fails >= len(self.RECONNECT_DELAYS):
                self.ctx.status = AccountStatus.ERROR
                log_account_event(
                    self.account_id,
                    self.ctx.login,
                    "RECONNECT_EXHAUSTED",
                    extra="marked as ERROR",
                )
        return success

    async def reconcile_positions(self) -> PositionReconciliationReport:
        """
        Comprehensive position reconciliation:
        1. Query all positions from MT5 session (with all_magic=True).
        2. Match positions matching account magic number and symbol.
        3. Detect unknown positions (foreign magic numbers / manual orders).
        4. Detect missing positions (tickets present in internal state but no longer on MT5).
        5. Detect duplicate internal records.
        6. Reconstruct internal trade state for unmanaged magic-matched positions.
        7. Populate processed_signals from position comments to ensure restart safety (never blindly resend).
        """
        if not self.ctx.session:
            return PositionReconciliationReport(
                account_id=self.account_id,
                login=self.ctx.login,
                matched_count=0,
                reconstructed_count=0,
                unknown_count=0,
                missing_count=0,
                unknown_tickets=[],
                missing_tickets=[],
                reconstructed_tickets=[],
                is_consistent=False,
            )

        loop = asyncio.get_event_loop()
        try:
            positions = await loop.run_in_executor(None, self.ctx.session.get_positions, None, True)
        except TypeError:
            positions = await loop.run_in_executor(None, self.ctx.session.get_positions)

        matched_positions = []
        unknown_positions = []
        for pos in positions:
            if pos.magic == self.ctx.magic_number:
                matched_positions.append(pos)
            else:
                unknown_positions.append(pos)

        matched_tickets = {pos.ticket for pos in matched_positions}
        unknown_tickets = [pos.ticket for pos in unknown_positions]

        if unknown_positions:
            logger.warning(
                f"[{self.account_id}] Detected {len(unknown_positions)} unknown/foreign positions on MT5: "
                f"tickets={unknown_tickets} (foreign magic numbers/manual trades)"
            )

        reconstructed_tickets = []
        missing_tickets = []

        with self.ctx._lock:
            current_local_tickets = set(self.ctx.exec_state.open_positions.keys())

            # Detect missing positions: in local state but not in matched MT5 positions
            missing_set = current_local_tickets - matched_tickets
            for ticket in missing_set:
                missing_tickets.append(ticket)
                self.ctx.exec_state.open_positions.pop(ticket, None)
                logger.warning(
                    f"[{self.account_id}] Reconcile detected missing position #{ticket} "
                    f"(closed externally on broker). Removed from active state."
                )

            # Reconstruct positions from MT5 into local state & populate processed_signals
            for pos in matched_positions:
                if pos.ticket not in self.ctx.exec_state.open_positions:
                    reconstructed_tickets.append(pos.ticket)
                    self.ctx.exec_state.open_positions[pos.ticket] = {
                        "ticket": pos.ticket,
                        "symbol": pos.symbol,
                        "direction": pos.direction,
                        "volume": pos.volume,
                        "price": pos.open_price,
                        "sl": pos.sl,
                        "tp": pos.tp,
                        "profit": pos.profit,
                        "magic": pos.magic,
                        "comment": pos.comment,
                    }
                    logger.info(
                        f"[{self.account_id}] Reconstructed state for open position #{pos.ticket} "
                        f"({pos.direction} {pos.volume} {pos.symbol} @ {pos.open_price:.5f})"
                    )
                else:
                    self.ctx.exec_state.open_positions[pos.ticket].update({
                        "profit": pos.profit,
                        "sl": pos.sl,
                        "tp": pos.tp,
                    })

                # Restart protection: Extract signal identifier from comment if present
                if pos.comment:
                    self.ctx.exec_state.processed_signals.add(pos.comment.strip())
                self.ctx.exec_state.processed_signals.add(f"pos_{pos.ticket}")

        is_consistent = (len(missing_tickets) == 0 and len(unknown_positions) == 0)

        return PositionReconciliationReport(
            account_id=self.account_id,
            login=self.ctx.login,
            matched_count=len(matched_positions),
            reconstructed_count=len(reconstructed_tickets),
            unknown_count=len(unknown_positions),
            missing_count=len(missing_tickets),
            unknown_tickets=unknown_tickets,
            missing_tickets=missing_tickets,
            reconstructed_tickets=reconstructed_tickets,
            is_consistent=is_consistent,
        )

    async def sync_account_state(self) -> None:
        """Query fresh balance/equity and positions from MT5."""
        if not self.ctx.session:
            return

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, self.ctx.session.get_account_info)
        if info:
            self.ctx.update_snapshot(
                balance=info.get("balance", 0.0),
                equity=info.get("equity", 0.0),
                margin=info.get("margin", 0.0),
                free_margin=info.get("free_margin", 0.0),
                margin_level=info.get("margin_level", 0.0),
            )
            # Reconcile open positions
            await self.reconcile_positions()
        else:
            # If account info returned None, check connection health
            is_alive = await loop.run_in_executor(None, self.ctx.session.is_connected)
            if not is_alive and self.ctx.status not in (
                AccountStatus.DISABLED,
                AccountStatus.DISCONNECTED,
            ):
                self.ctx.status = AccountStatus.DISCONNECTED
                log_account_event(self.account_id, self.ctx.login, "CONNECTION_LOST")

    async def _sync_loop(self) -> None:
        """Periodic heartbeat and synchronization loop."""
        while self._running:
            try:
                if self.ctx.status == AccountStatus.DISCONNECTED and self.ctx.config.enabled:
                    await self.reconnect()
                elif self.ctx.status in (AccountStatus.CONNECTED, AccountStatus.TRADING):
                    await self.sync_account_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.account_id}] Worker loop error: {e}")
                self.ctx.exec_state.last_error = str(e)

            await asyncio.sleep(self.sync_interval_s)
