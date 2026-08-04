"""
app/terminal_supervisor.py — MT5 Terminal Lifecycle & Supervisor Engine

Provides production-grade lifecycle monitoring for MT5:
- Connection Manager: Process launch & API login
- Heartbeat: Continuous responsiveness checks
- Reconnect Manager: Smart exponential backoff reconnects
- Watchdog: Background monitoring loop
- Terminal Supervisor: Prevents redundant MT5 process restarts
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class TerminalHealthState:
    is_process_running: bool = False
    is_api_initialized: bool = False
    is_connected_to_broker: bool = False
    ping_ms: float = 0.0
    last_heartbeat: Optional[datetime] = None
    reconnect_count: int = 0
    last_error: str = ""


class TerminalSupervisor:
    """
    Supervises MT5 terminal health, maintains heartbeats, and manages smart reconnects.
    """

    def __init__(
        self,
        connection_manager: Any,
        heartbeat_interval_s: float = 5.0,
        max_reconnect_attempts: int = 10,
    ):
        self.connection_manager = connection_manager
        self.heartbeat_interval_s = heartbeat_interval_s
        self.max_reconnect_attempts = max_reconnect_attempts
        self.state = TerminalHealthState()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_reconnect_callbacks: list[Callable[[], None]] = []

    def register_reconnect_callback(self, cb: Callable[[], None]) -> None:
        """Register callback triggered upon successful reconnect."""
        self._on_reconnect_callbacks.append(cb)

    def check_heartbeat(self) -> TerminalHealthState:
        """Perform immediate heartbeat check on MT5 terminal and server connection."""
        now = datetime.now(timezone.utc)
        self.state.last_heartbeat = now

        if not MT5_AVAILABLE:
            self.state.is_process_running = False
            self.state.is_api_initialized = False
            self.state.is_connected_to_broker = False
            self.state.last_error = "MetaTrader5 Python package unavailable"
            return self.state

        term = mt5.terminal_info()
        acct = mt5.account_info()

        if term is None:
            self.state.is_process_running = False
            self.state.is_api_initialized = False
            self.state.is_connected_to_broker = False
            code, msg = mt5.last_error()
            self.state.last_error = f"Terminal unreachable: [{code}] {msg}"
            return self.state

        self.state.is_process_running = True
        self.state.is_api_initialized = True
        self.state.is_connected_to_broker = getattr(term, "connected", False) and (acct is not None)
        self.state.ping_ms = getattr(term, "ping_last", 0.0) / 1000.0 if hasattr(term, "ping_last") else 0.0

        if not self.state.is_connected_to_broker:
            self.state.last_error = "Disconnected from MT5 broker server"

        return self.state

    async def start_watchdog(self) -> None:
        """Start asynchronous watchdog loop monitoring terminal health."""
        if self._monitoring:
            return

        self._monitoring = True
        logger.info(f"[SUPERVISOR] Watchdog loop started (interval={self.heartbeat_interval_s}s).")

        while self._monitoring:
            try:
                state = self.check_heartbeat()
                if not state.is_connected_to_broker:
                    logger.warning(f"[SUPERVISOR] Heartbeat failed: {state.last_error}. Initiating reconnect...")
                    reconnect_ok = await self.reconnect()
                    if reconnect_ok:
                        for cb in self._on_reconnect_callbacks:
                            try:
                                cb()
                            except Exception as cbe:
                                logger.error(f"[SUPERVISOR] Exception in reconnect callback: {cbe}")
            except Exception as e:
                logger.error(f"[SUPERVISOR] Watchdog exception: {e}")

            await asyncio.sleep(self.heartbeat_interval_s)

    def stop_watchdog(self) -> None:
        """Stop background watchdog loop."""
        self._monitoring = False
        logger.info("[SUPERVISOR] Watchdog loop stopped.")

    async def reconnect(self, base_delay_s: float = 2.0, max_delay_s: float = 30.0) -> bool:
        """
        Execute smart exponential backoff reconnect sequence.
        Only restarts MT5 process if API re-initialization fails.
        """
        logger.info(f"[SUPERVISOR] Reconnect sequence initiated (Max attempts={self.max_reconnect_attempts})...")

        for attempt in range(1, self.max_reconnect_attempts + 1):
            self.state.reconnect_count += 1
            delay = min(base_delay_s * (2 ** min(attempt - 1, 4)), max_delay_s)
            logger.info(f"[SUPERVISOR] Reconnect attempt {attempt}/{self.max_reconnect_attempts} in {delay:.1f}s...")

            await asyncio.sleep(delay)

            try:
                # Attempt connection via manager
                res = self.connection_manager.connect_mt5()
                if res.success:
                    logger.info("✅ [SUPERVISOR] MT5 reconnection successful!")
                    self.check_heartbeat()
                    return True
                else:
                    self.state.last_error = res.message
                    logger.warning(f"[SUPERVISOR] Attempt {attempt} failed: {res.message}")
            except Exception as e:
                self.state.last_error = str(e)
                logger.error(f"[SUPERVISOR] Exception during reconnect attempt {attempt}: {e}")

        logger.critical("❌ [SUPERVISOR] All reconnect attempts failed.")
        return False
