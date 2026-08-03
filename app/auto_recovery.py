"""
app/auto_recovery.py — Auto-Recovery & Position Reconciliation Engine

Monitors connectivity heartbeats, MT5 process health, and broker server status.
Handles automatic reconnects with exponential backoff and performs position reconciliation
on startup or recovery to ensure unmanaged MT5 positions are seamlessly re-adopted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class ReconnectStatus:
    attempts: int = 0
    connected: bool = False
    last_attempt_time: float = 0.0
    last_error: str = ""


class AutoRecoveryEngine:
    """
    Manages automated recovery loops, heartbeat checks, and position reconciliation.
    """

    def __init__(self, mt5_connector: Any, trade_engine: Any, symbol_manager: Any):
        self.connector = mt5_connector
        self.engine = trade_engine
        self.symbol_manager = symbol_manager
        self._reconnect_status = ReconnectStatus()

    def check_heartbeat(self) -> Tuple[bool, str]:
        """Verify terminal responsiveness and connection."""
        if not MT5_AVAILABLE:
            return False, "MetaTrader5 library unavailable"

        term_info = mt5.terminal_info()
        if term_info is None:
            code, msg = mt5.last_error()
            return False, f"Terminal unreachable: [{code}] {msg}"

        if not term_info.connected:
            return False, "Terminal process running but disconnected from broker server"

        return True, "Heartbeat healthy"

    async def auto_reconnect_loop(
        self,
        max_attempts: int = 15,
        base_delay_s: float = 3.0,
        max_delay_s: float = 60.0,
    ) -> bool:
        """
        Attempt exponential backoff reconnects to MT5 terminal and broker server.
        """
        logger.warning("[AUTO-RECOVERY] Initiating automatic reconnect sequence...")
        self._reconnect_status.attempts = 0
        self._reconnect_status.connected = False

        for attempt in range(1, max_attempts + 1):
            self._reconnect_status.attempts = attempt
            self._reconnect_status.last_attempt_time = time.time()
            delay = min(base_delay_s * (2 ** min(attempt - 1, 5)), max_delay_s)

            logger.info(f"[AUTO-RECOVERY] Reconnect attempt {attempt}/{max_attempts} in {delay:.1f}s...")
            await asyncio.sleep(delay)

            try:
                # Attempt connector initialization & login
                result = self.connector.connect()
                if result.success and result.safety_passed:
                    logger.info("✅ [AUTO-RECOVERY] MT5 connection restored successfully!")
                    self._reconnect_status.connected = True
                    
                    # Re-initialize symbol watch
                    self.symbol_manager.initialize_symbols()

                    # Reconcile open positions
                    await self.reconcile_positions()
                    return True
                else:
                    self._reconnect_status.last_error = result.safety_reason or result.error_message
                    logger.warning(f"[AUTO-RECOVERY] Attempt {attempt} failed: {self._reconnect_status.last_error}")
            except Exception as e:
                self._reconnect_status.last_error = str(e)
                logger.error(f"[AUTO-RECOVERY] Exception during reconnect attempt {attempt}: {e}")

        logger.critical("❌ [AUTO-RECOVERY] All reconnect attempts exhausted. Manual intervention required.")
        return False

    async def reconcile_positions(self) -> int:
        """
        Query MT5 for active positions matching magic number and restore internal trade state.
        Ensures unmanaged trades after reboot/disconnect are tracked properly.
        """
        if not MT5_AVAILABLE:
            return 0

        logger.info("[RECONCILIATION] Reconciling MT5 active positions with TradeEngine state...")
        
        magic = getattr(self.engine, "_cfg", None).magic if hasattr(self.engine, "_cfg") else 20250701
        mt5_positions = mt5.positions_get()
        if mt5_positions is None:
            logger.warning("[RECONCILIATION] Unable to fetch positions from MT5")
            return 0

        magic_positions = [p for p in mt5_positions if p.magic == magic]
        logger.info(f"[RECONCILIATION] Found {len(magic_positions)} magic-matched positions on MT5.")

        reconciled_count = 0
        from app.trade_engine import ActiveTrade

        for pos in magic_positions:
            canonical_sym = self.symbol_manager.resolve_canonical_symbol(pos.symbol)
            existing_trade = self.engine.get_trade(canonical_sym)

            if existing_trade is None or existing_trade.ticket != pos.ticket:
                logger.info(f"[RECONCILIATION] Restoring tracking for position #{pos.ticket} on {canonical_sym}")
                direction = "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT"
                
                restored_trade = ActiveTrade(
                    ticket=pos.ticket,
                    direction=direction,
                    symbol=canonical_sym,
                    entry_price=pos.price_open,
                    entry_time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
                    volume=pos.volume,
                    initial_vol=pos.volume,
                    risk_usd=0.0,
                    quality_score=80.0,
                    sl=pos.sl,
                    tp1=pos.tp,
                    current_tp=pos.tp,
                    high_water=pos.price_current,
                    low_water=pos.price_current,
                )

                self.engine._trades[canonical_sym] = restored_trade
                reconciled_count += 1

        logger.info(f"[RECONCILIATION] Reconciliation complete. Restored {reconciled_count} positions.")
        return reconciled_count
