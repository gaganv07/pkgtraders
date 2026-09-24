"""
app/multi_account/account_manager.py — Multi-Account Orchestration & Signal Coordinator

Central coordinator managing:
- AccountContext lifecycle (add, remove, connect, disconnect, reconnect).
- Global safety controls (BOT_ENABLED, GLOBAL_EMERGENCY_STOP, MAX_ACCOUNTS).
- Independent per-account position sizing.
- Concurrent signal fan-out with complete failure isolation.
- Internal telemetry and resource monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import os
import psutil
import time
from typing import Any, Dict, List, Optional, Tuple

from app.multi_account.account_context import (
    AccountContext,
    AccountStatus,
    NormalizedSignal,
    TradeExecutionReport,
)
from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_worker import (
    AccountWorker,
    PositionReconciliationReport,
    log_account_event,
    log_execution_event,
)
from app.multi_account.mt5_session import create_session
from app.position_sizer import BrokerSpec, PositionSizer

logger = logging.getLogger(__name__)


class MT5AccountManager:
    """
    Production-grade multi-account orchestrator managing isolated MT5 account sessions,
    per-account risk guards, and concurrent execution.
    """

    def __init__(
        self,
        registry: Optional[AccountRegistry] = None,
        database: Optional[Any] = None,
        max_accounts: int = 10,
    ):
        self.registry = registry or AccountRegistry()
        self.db = database
        self.max_accounts = max_accounts

        self._contexts: Dict[str, AccountContext] = {}
        self._workers: Dict[str, AccountWorker] = {}

        # Global safety controls
        self.bot_enabled: bool = True
        self.global_emergency_stop: bool = False
        self.global_max_daily_loss_pct: float = 20.0

    # ── Account Lifecycle Management ──────────────────────────────────────────

    def add_account(
        self, config: AccountConfig, session_mode: str = "auto"
    ) -> AccountContext:
        """
        Add an account to the manager:
        - Validates capacity (MAX_ACCOUNTS)
        - Creates isolated IMT5Session
        - Creates isolated AccountContext
        - Instantiates dedicated AccountWorker
        """
        if config.account_id in self._contexts:
            raise ValueError(f"Account '{config.account_id}' is already active in account manager")

        if len(self._contexts) >= self.max_accounts:
            raise RuntimeError(
                f"Cannot add account '{config.account_id}': MAX_ACCOUNTS limit ({self.max_accounts}) reached"
            )

        # Register in registry (validates uniqueness)
        if not self.registry.get(config.account_id):
            self.registry.register(config)

        session = create_session(config, mode=session_mode)
        ctx = AccountContext(config=config, mt5_session=session)
        worker = AccountWorker(context=ctx)

        self._contexts[config.account_id] = ctx
        self._workers[config.account_id] = worker

        logger.info(
            f"[ACCOUNT_MGR] Added account '{config.account_id}' "
            f"(login=#{config.login}, magic={config.magic_number})"
        )
        return ctx

    def remove_account(self, account_id: str) -> Optional[AccountContext]:
        """Stop worker and remove account from manager."""
        if account_id in self._workers:
            # Stop worker in background
            worker = self._workers.pop(account_id)
            asyncio.create_task(worker.stop())

        ctx = self._contexts.pop(account_id, None)
        self.registry.unregister(account_id)
        if ctx:
            logger.info(f"[ACCOUNT_MGR] Removed account '{account_id}'")
        return ctx

    async def connect_account(self, account_id: str) -> bool:
        """Connect an individual account."""
        worker = self._workers.get(account_id)
        if not worker:
            return False
        return await worker.start()

    async def disconnect_account(self, account_id: str) -> None:
        """Disconnect an individual account."""
        worker = self._workers.get(account_id)
        if worker:
            await worker.stop()

    async def reconnect_account(self, account_id: str) -> bool:
        """Manually trigger reconnect for an account."""
        worker = self._workers.get(account_id)
        if not worker:
            return False
        return await worker.reconnect()

    async def connect_all(self) -> Dict[str, bool]:
        """Connect all registered accounts concurrently."""
        tasks = [self.connect_account(acc_id) for acc_id in list(self._contexts.keys())]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            acc_id: (res is True)
            for acc_id, res in zip(self._contexts.keys(), results)
        }

    async def disconnect_all(self) -> None:
        """Gracefully disconnect all accounts."""
        tasks = [worker.stop() for worker in list(self._workers.values())]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[ACCOUNT_MGR] Disconnected all account sessions")

    async def reconcile_all_accounts(self) -> Dict[str, PositionReconciliationReport]:
        """Trigger startup position reconciliation across all accounts concurrently."""
        tasks = [worker.reconcile_positions() for worker in self._workers.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        reports = {}
        for acc_id, res in zip(self._workers.keys(), results):
            if isinstance(res, Exception):
                logger.error(f"[{acc_id}] Reconciliation failed: {res}")
            else:
                reports[acc_id] = res
        return reports

    def get_account(self, account_id: str) -> Optional[AccountContext]:
        """Retrieve AccountContext by account_id."""
        return self._contexts.get(account_id)

    def get_status(self, account_id: str) -> AccountStatus:
        """Get status of an individual account."""
        ctx = self._contexts.get(account_id)
        return ctx.status if ctx else AccountStatus.DISABLED

    def get_all_statuses(self) -> Dict[str, AccountStatus]:
        """Get mapping of all account statuses."""
        return {acc_id: ctx.status for acc_id, ctx in self._contexts.items()}

    def get_all_contexts(self) -> List[AccountContext]:
        """Get all active AccountContext instances."""
        return list(self._contexts.values())

    # ── Independent Position Sizing ──────────────────────────────────────────

    def calculate_position_size(
        self, account_id: str, signal: NormalizedSignal
    ) -> Tuple[float, float]:
        """
        Calculate account-specific lot size:
        - Reads live balance and equity of this specific account
        - Uses account's configured risk % and risk multiplier
        - Reads broker tick specifications from this account's session
        - Returns (volume, expected_loss_usd)
        """
        ctx = self._contexts.get(account_id)
        if not ctx or not ctx.session:
            return 0.0, 0.0

        balance = ctx.risk_state.current_balance
        if balance <= 0:
            balance = 1000.0  # Fallback baseline

        spec_dict = ctx.session.get_symbol_spec(signal.symbol)
        if not spec_dict:
            spec_dict = {
                "digits": 2, "point": 0.01, "spread": 15, "contract_size": 100.0,
                "vol_min": 0.01, "vol_max": 50.0, "vol_step": 0.01,
                "tick_size": 0.01, "tick_value": 0.01,
            }

        broker_spec = BrokerSpec.from_spec_dict(spec_dict, symbol=signal.symbol)
        effective_risk_pct = ctx.config.risk_per_trade_pct * ctx.config.risk_multiplier

        sizing = PositionSizer.size(
            balance=balance,
            entry=signal.entry_reference,
            stop_loss=signal.stop_loss,
            tp_price=signal.take_profit_1,
            risk_pct=effective_risk_pct,
            spec=broker_spec,
            equity=ctx.risk_state.current_equity or balance,
            free_margin=ctx.risk_state.free_margin or balance,
            strategy=signal.strategy_name,
            symbol=signal.symbol,
            write_csv=False,
        )
        return sizing.final_lot, sizing.expected_loss

    # ── Concurrent Signal Distribution & Execution ────────────────────────────

    async def distribute_signal(
        self, signal: NormalizedSignal
    ) -> Dict[str, TradeExecutionReport]:
        """
        Fan-out signal execution concurrently to all enabled accounts.
        Guarantees failure isolation: failure on Account A never affects Account B.
        """
        if not self.bot_enabled or self.global_emergency_stop:
            logger.warning("[ACCOUNT_MGR] Signal execution blocked by global safety switch")
            return {}

        enabled_accounts = [
            acc_id for acc_id, ctx in self._contexts.items() if ctx.config.enabled
        ]
        if not enabled_accounts:
            logger.info("[ACCOUNT_MGR] No enabled accounts available for signal distribution")
            return {}

        log_account_event(
            account_id="ALL",
            login=0,
            event="SIGNAL_FAN_OUT",
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            extra=f"id={signal.signal_id} dir={signal.direction} target_accounts={enabled_accounts}",
        )

        tasks = [
            self._execute_for_account(acc_id, signal) for acc_id in enabled_accounts
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        reports = {}
        for acc_id, res in zip(enabled_accounts, results):
            if isinstance(res, Exception):
                logger.error(
                    f"[{acc_id}] Unhandled execution exception: {res}", exc_info=True
                )
                reports[acc_id] = TradeExecutionReport(
                    account_id=acc_id,
                    login=self._contexts[acc_id].login,
                    signal_id=signal.signal_id,
                    symbol=signal.symbol,
                    direction=signal.direction,
                    status="ERROR",
                    rejection_reason=f"Exception: {res}",
                )
            else:
                reports[acc_id] = res

        return reports

    async def _execute_for_account(
        self, account_id: str, signal: NormalizedSignal
    ) -> TradeExecutionReport:
        """
        Execute signal independently for a single account:
        1. Pre-trade permissions & risk checks
        2. Account-specific position sizing
        3. Submission to MT5 session with unique magic number
        4. Result recording & database persistence
        """
        ctx = self._contexts[account_id]

        # 1. Pre-trade check
        allowed, reason = ctx.is_trading_allowed(signal.symbol, signal_id=signal.signal_id)
        if not allowed:
            ctx.record_rejection(reason)
            log_account_event(
                account_id,
                ctx.login,
                "ORDER_REJECTED",
                symbol=signal.symbol,
                extra=f"reason='{reason}'",
            )
            log_execution_event(
                account_id=account_id,
                mt5_login=ctx.login,
                server=ctx.config.server,
                worker_id=f"worker_{account_id}",
                terminal_id=f"terminal_{account_id}",
                signal_id=signal.signal_id,
                magic_number=ctx.magic_number,
                symbol=signal.symbol,
                action=signal.direction,
                risk=ctx.config.risk_per_trade_pct * ctx.config.risk_multiplier,
                execution_status="REJECTED",
                error_code=0,
            )
            return TradeExecutionReport(
                account_id=account_id,
                login=ctx.login,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                status="REJECTED",
                rejection_reason=reason,
                magic_number=ctx.magic_number,
            )

        # 2. Position sizing
        volume, risk_usd = self.calculate_position_size(account_id, signal)
        if volume <= 0:
            reason = "Calculated volume is 0.0"
            ctx.record_rejection(reason)
            log_execution_event(
                account_id=account_id,
                mt5_login=ctx.login,
                server=ctx.config.server,
                worker_id=f"worker_{account_id}",
                terminal_id=f"terminal_{account_id}",
                signal_id=signal.signal_id,
                magic_number=ctx.magic_number,
                symbol=signal.symbol,
                action=signal.direction,
                risk=ctx.config.risk_per_trade_pct * ctx.config.risk_multiplier,
                execution_status="REJECTED",
                error_code=0,
            )
            return TradeExecutionReport(
                account_id=account_id,
                login=ctx.login,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                status="REJECTED",
                requested_volume=0.0,
                rejection_reason=reason,
                magic_number=ctx.magic_number,
            )

        # 3. Order submission
        comment = f"{signal.symbol[:6]}|{ctx.account_id[:6]}"
        loop = asyncio.get_event_loop()
        t0 = time.time()

        if signal.direction.upper() == "LONG":
            fill = await loop.run_in_executor(
                None,
                ctx.session.buy,
                volume,
                signal.stop_loss,
                signal.take_profit_1,
                comment,
                signal.symbol,
            )
        else:
            fill = await loop.run_in_executor(
                None,
                ctx.session.sell,
                volume,
                signal.stop_loss,
                signal.take_profit_1,
                comment,
                signal.symbol,
            )

        lat = (time.time() - t0) * 1000.0

        # 4. Handle result
        if fill.success:
            report = TradeExecutionReport(
                account_id=account_id,
                login=ctx.login,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                status="SUCCESS",
                requested_volume=volume,
                executed_volume=fill.volume or volume,
                requested_price=signal.entry_reference,
                executed_price=fill.price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1,
                ticket=fill.ticket,
                position_ticket=fill.ticket,
                magic_number=ctx.magic_number,
                latency_ms=lat,
            )
            ctx.record_fill(report)
            log_account_event(
                account_id,
                ctx.login,
                "ORDER_FILLED",
                symbol=signal.symbol,
                ticket=fill.ticket,
                extra=f"vol={report.executed_volume} price={report.executed_price:.5f} lat={lat:.1f}ms",
            )
            log_execution_event(
                account_id=account_id,
                mt5_login=ctx.login,
                server=ctx.config.server,
                worker_id=f"worker_{account_id}",
                terminal_id=f"terminal_{account_id}",
                signal_id=signal.signal_id,
                magic_number=ctx.magic_number,
                symbol=signal.symbol,
                action=signal.direction,
                risk=ctx.config.risk_per_trade_pct * ctx.config.risk_multiplier,
                execution_status="SUCCESS",
                error_code=0,
            )
            # Database persistence
            await self._persist_trade_ledger(report, signal)
            return report
        else:
            reason = fill.error or f"Broker retcode {fill.retcode}"
            ctx.record_rejection(reason, error_code=fill.retcode)
            log_account_event(
                account_id,
                ctx.login,
                "ORDER_REJECTED",
                symbol=signal.symbol,
                extra=f"error='{reason}'",
            )
            log_execution_event(
                account_id=account_id,
                mt5_login=ctx.login,
                server=ctx.config.server,
                worker_id=f"worker_{account_id}",
                terminal_id=f"terminal_{account_id}",
                signal_id=signal.signal_id,
                magic_number=ctx.magic_number,
                symbol=signal.symbol,
                action=signal.direction,
                risk=ctx.config.risk_per_trade_pct * ctx.config.risk_multiplier,
                execution_status="REJECTED",
                error_code=fill.retcode if fill.retcode else -1,
            )
            return TradeExecutionReport(
                account_id=account_id,
                login=ctx.login,
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                status="REJECTED",
                requested_volume=volume,
                rejection_reason=reason,
                error_code=fill.retcode,
                magic_number=ctx.magic_number,
                latency_ms=lat,
            )

    async def _persist_trade_ledger(
        self, report: TradeExecutionReport, signal: NormalizedSignal
    ) -> None:
        """Persist trade execution report to database ledger."""
        if not self.db:
            return

        try:
            # Check if database has insert_account_trade method
            if hasattr(self.db, "insert_account_trade"):
                await self.db.insert_account_trade(report, signal)
            else:
                # Use raw SQL insert or standard insert_trade adapter
                sql = """
                INSERT OR REPLACE INTO trades (
                    id, ticket, symbol, direction, status,
                    entry_price, entry_time, volume, initial_vol,
                    risk_usd, quality_score, atr_entry,
                    sl, tp1, tp2, tp3,
                    account_id, magic, signal_id
                ) VALUES (
                    :id, :ticket, :symbol, :direction, 'OPEN',
                    :entry, :entry_time, :vol, :init_vol,
                    :risk_usd, :quality, :atr,
                    :sl, :tp1, :tp2, :tp3,
                    :account_id, :magic, :signal_id
                )
                """
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self.db.execute_write,
                    sql,
                    {
                        "id": f"{report.account_id}_{report.ticket or signal.signal_id}",
                        "ticket": report.ticket or 0,
                        "symbol": report.symbol,
                        "direction": report.direction,
                        "entry": report.executed_price,
                        "entry_time": report.timestamp.isoformat(),
                        "vol": report.executed_volume,
                        "init_vol": report.requested_volume,
                        "risk_usd": 0.0,
                        "quality": signal.quality_score,
                        "atr": signal.atr,
                        "sl": report.stop_loss,
                        "tp1": report.take_profit,
                        "tp2": signal.take_profit_2,
                        "tp3": signal.take_profit_3,
                        "account_id": report.account_id,
                        "magic": report.magic_number,
                        "signal_id": report.signal_id,
                    },
                )
        except Exception as e:
            logger.error(
                f"[{report.account_id}] Failed to persist trade to database: {e}"
            )

    # ── Observability & Telemetry ─────────────────────────────────────────────

    def get_telemetry(self) -> Dict[str, Any]:
        """Aggregate real-time metrics across all accounts."""
        total_accounts = len(self._contexts)
        connected_count = sum(
            1 for c in self._contexts.values() if c.status == AccountStatus.CONNECTED
        )
        trading_count = sum(
            1 for c in self._contexts.values() if c.status == AccountStatus.TRADING
        )
        disconnected_count = sum(
            1 for c in self._contexts.values() if c.status == AccountStatus.DISCONNECTED
        )
        error_count = sum(
            1
            for c in self._contexts.values()
            if c.status in (AccountStatus.ERROR, AccountStatus.AUTH_ERROR)
        )

        total_equity = sum(c.risk_state.current_equity for c in self._contexts.values())
        total_pnl = sum(c.risk_state.daily_pnl for c in self._contexts.values())
        total_positions = sum(
            len(c.exec_state.open_positions) for c in self._contexts.values()
        )

        per_account = {acc_id: ctx.summary() for acc_id, ctx in self._contexts.items()}

        # System resource usage
        mem_mb = 0.0
        cpu_pct = 0.0
        try:
            p = psutil.Process()
            mem_mb = p.memory_info().rss / (1024 * 1024)
            cpu_pct = psutil.cpu_percent(interval=None)
        except Exception:
            pass

        return {
            "total_accounts": total_accounts,
            "connected_accounts": connected_count,
            "trading_accounts": trading_count,
            "disconnected_accounts": disconnected_count,
            "error_accounts": error_count,
            "total_equity": round(total_equity, 2),
            "today_pnl": round(total_pnl, 2),
            "open_positions": total_positions,
            "bot_enabled": self.bot_enabled,
            "emergency_stop": self.global_emergency_stop,
            "per_account": per_account,
            "resources": {
                "memory_mb": round(mem_mb, 1),
                "cpu_percent": round(cpu_pct, 1),
                "active_workers": len(self._workers),
            },
        }

    async def emergency_close_all(
        self, reason: str = "GLOBAL_EMERGENCY_STOP"
    ) -> Dict[str, int]:
        """Close all open positions across every managed account."""
        self.global_emergency_stop = True
        logger.critical(
            f"[ACCOUNT_MGR] EMERGENCY CLOSE ALL TRIGGERED across {len(self._contexts)} accounts: {reason}"
        )
        results = {}
        loop = asyncio.get_event_loop()
        for acc_id, ctx in self._contexts.items():
            if ctx.session:
                count = await loop.run_in_executor(
                    None, ctx.session.close_all, reason
                )
                results[acc_id] = count
                log_account_event(
                    acc_id,
                    ctx.login,
                    "EMERGENCY_CLOSE",
                    extra=f"closed={count} reason='{reason}'",
                )
        return results
