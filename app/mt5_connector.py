"""
app/mt5_connector.py — MetaTrader 5 Connection & Safety Module

Handles direct connection to the local MetaTrader 5 terminal using the
official MetaTrader5 Python package. Includes terminal auto-launch,
login verification, detailed logging, and strict account safety checks.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not installed in environment.")


@dataclass
class AccountDetails:
    login: int
    broker: str
    server: str
    balance: float
    equity: float
    margin: float
    leverage: int
    currency: str


@dataclass
class ConnectionResult:
    success: bool
    account_details: Optional[AccountDetails] = None
    error_code: int = 0
    error_message: str = ""
    safety_passed: bool = False
    safety_reason: str = ""


class MT5Connector:
    """
    Manages connection lifecycle with local MetaTrader 5 terminal.
    """

    def __init__(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
        timeout_ms: int = 60000,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.timeout_ms = timeout_ms
        self._connected = False
        self._terminal_launched = False

    @property
    def is_connected(self) -> bool:
        """Return true if terminal is initialized and responsive."""
        if not MT5_AVAILABLE or not self._connected:
            return False
        return mt5.terminal_info() is not None

    def connect(self) -> ConnectionResult:
        """
        Connect to MT5 terminal using MT5ConnectionManager, verify login, and check safety.
        """
        from app.mt5_connection import MT5ConnectionManager

        manager = MT5ConnectionManager(
            login=self.login or 0,
            password=self.password or "",
            server=self.server or "",
            path=self.path or "",
            timeout_ms=self.timeout_ms,
        )

        res = manager.connect_mt5()
        if not res.success:
            return ConnectionResult(success=False, error_code=res.error_code, error_message=res.message)

        acct_dict = manager.get_account_info()
        details = AccountDetails(
            login=acct_dict.get("login", 0),
            broker=acct_dict.get("broker", ""),
            server=acct_dict.get("server", ""),
            balance=acct_dict.get("balance", 0.0),
            equity=acct_dict.get("equity", 0.0),
            margin=acct_dict.get("margin", 0.0),
            leverage=acct_dict.get("leverage", 1),
            currency=acct_dict.get("currency", "USD"),
        )

        self._connected = True

        perms = manager.verify_trading_permissions()
        all_ok = all(pok for pok, _ in perms.values())

        if not all_ok:
            reason = "; ".join([f"{k}: {msg}" for k, (pok, msg) in perms.items() if not pok])
            return ConnectionResult(
                success=True,
                account_details=details,
                safety_passed=False,
                safety_reason=reason,
            )

        return ConnectionResult(
            success=True,
            account_details=details,
            safety_passed=True,
            safety_reason="Passed all safety checks",
        )

    def _ensure_terminal_running(self) -> None:
        """Check if terminal is running, launch executable if not."""
        if not self.path or not os.path.exists(self.path):
            return
        
        # Quick check if MT5 is already responsive
        if MT5_AVAILABLE and mt5.terminal_info() is not None:
            return

        logger.info(f"Launching MT5 terminal executable from: {self.path}")
        try:
            subprocess.Popen([self.path], creationflags=subprocess.DETACHED_PROCESS)
            self._terminal_launched = True
            time.sleep(3.0)  # Allow terminal process time to initialize
        except Exception as e:
            logger.warning(f"Failed to launch MT5 process automatically: {e}")

    def verify_account_safety(self) -> Tuple[bool, str]:
        """
        Verify safety constraints:
          - Terminal AutoTrading / Algo Trading enabled
          - Account trading permission enabled
        """
        if not MT5_AVAILABLE or not self._connected:
            return False, "MT5 not connected"

        term_info = mt5.terminal_info()
        if term_info is None:
            return False, "Unable to fetch MT5 terminal_info()"

        if not term_info.trade_allowed:
            return False, "AutoTrading / Algo Trading is DISABLED in MT5 terminal settings"

        acct_info = mt5.account_info()
        if acct_info is None:
            return False, "Unable to fetch MT5 account_info()"

        if not acct_info.trade_allowed:
            return False, "Account trading is DISABLED by broker or account settings"

        if acct_info.trade_expert is False:
            return False, "Automated Expert Advisor trading disabled for account"

        return True, "All account safety checks passed"

    def disconnect(self) -> None:
        """Gracefully shutdown MT5 connection."""
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 connection shutdown successfully.")
