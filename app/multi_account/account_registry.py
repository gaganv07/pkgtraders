"""
app/multi_account/account_registry.py — Account Configuration & Registry

Defines:
- AccountConfig: Strongly typed account configuration model.
- AccountRegistry: Discovery, validation, loading, and management of accounts.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.config import settings

logger = logging.getLogger(__name__)


def mask_credential(val: Any) -> str:
    """Mask sensitive string values (e.g. passwords) for safe logging."""
    if not val:
        return ""
    s = str(val)
    if len(s) <= 4:
        return "****"
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


@dataclass
class AccountConfig:
    """
    Configuration model for a single MetaTrader 5 account.
    Passwords are never logged or committed to source control.
    """
    account_id: str
    enabled: bool = True
    trading_enabled: bool = True
    login: int = 0
    server: str = ""
    password: str = ""
    password_env_var: str = ""
    terminal_path: str = ""
    data_directory: str = ""
    portable_terminal_directory: str = ""
    company: str = ""
    magic_number: int = 20250701
    symbols: List[str] = field(default_factory=list)  # Empty list = all bot symbols permitted
    risk_per_trade_pct: float = 1.0
    risk_multiplier: float = 1.0                      # Multiplier applied to standard lot/risk
    daily_drawdown_limit_pct: float = 3.0
    weekly_drawdown_limit_pct: float = 6.0
    account_drawdown_limit_pct: float = 10.0
    max_open_trades: int = 3
    max_risk_exposure_pct: float = 3.0
    initial_balance: float = 10000.0
    dry_run: bool = False                             # If True, simulate execution without placing real orders
    execution_status: str = "INITIALIZING"

    def __post_init__(self):
        if not self.portable_terminal_directory and self.data_directory:
            self.portable_terminal_directory = self.data_directory
        elif not self.data_directory and self.portable_terminal_directory:
            self.data_directory = self.portable_terminal_directory

    def resolve_password(self) -> str:
        """
        Resolve the MT5 password securely:
        1. Check environment variable named by `password_env_var`
        2. Fall back to `password` if explicitly provided
        3. Fall back to global `MT5_PASSWORD` from environment
        """
        if self.password_env_var:
            val = os.getenv(self.password_env_var, "").strip()
            if val:
                return val
        if self.password:
            return self.password.strip()
        # Fallback to standard MT5_PASSWORD from .env
        return os.getenv("MT5_PASSWORD", "").strip() or settings.mt5.password

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return dict representation with sensitive credentials strictly masked."""
        return {
            "account_id": self.account_id,
            "enabled": self.enabled,
            "trading_enabled": self.trading_enabled,
            "login": self.login,
            "server": self.server,
            "password": mask_credential(self.resolve_password()),
            "password_env_var": self.password_env_var,
            "terminal_path": self.terminal_path,
            "data_directory": self.data_directory,
            "portable_terminal_directory": self.portable_terminal_directory,
            "company": self.company,
            "execution_status": self.execution_status,
            "magic_number": self.magic_number,
            "symbols": list(self.symbols),
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "risk_multiplier": self.risk_multiplier,
            "daily_drawdown_limit_pct": self.daily_drawdown_limit_pct,
            "weekly_drawdown_limit_pct": self.weekly_drawdown_limit_pct,
            "account_drawdown_limit_pct": self.account_drawdown_limit_pct,
            "max_open_trades": self.max_open_trades,
            "max_risk_exposure_pct": self.max_risk_exposure_pct,
            "dry_run": self.dry_run,
        }

    def __repr__(self) -> str:
        return (
            f"AccountConfig(account_id='{self.account_id}', login={self.login}, "
            f"server='{self.server}', magic={self.magic_number}, "
            f"enabled={self.enabled}, dry_run={self.dry_run}, "
            f"password='{mask_credential(self.resolve_password())}')"
        )


class AccountRegistry:
    """
    Registry and validator for multi-account configurations.
    Enforces uniqueness of account_id and magic_number.
    """

    def __init__(self):
        self._accounts: Dict[str, AccountConfig] = {}
        self._magic_to_account: Dict[int, str] = {}

    def register(self, config: AccountConfig) -> None:
        """Register an account configuration after strict validation."""
        self.validate(config)
        self._accounts[config.account_id] = config
        self._magic_to_account[config.magic_number] = config.account_id
        logger.info(
            f"[REGISTRY] Registered account '{config.account_id}' "
            f"(login=#{config.login}, server='{config.server}', magic={config.magic_number})"
        )

    def validate(self, config: AccountConfig) -> None:
        """
        Validate account configuration:
        - account_id must be non-empty and unique
        - magic_number must be unique across all accounts
        - login must be a positive integer
        - credentials must be resolvable
        """
        if not config.account_id or not config.account_id.strip():
            raise ValueError("account_id cannot be empty")

        clean_id = config.account_id.strip()
        if clean_id in self._accounts and self._accounts[clean_id] is not config:
            raise ValueError(f"Duplicate account_id: '{clean_id}' is already registered")

        if config.magic_number in self._magic_to_account:
            existing_id = self._magic_to_account[config.magic_number]
            if existing_id != clean_id:
                raise ValueError(
                    f"Duplicate magic_number {config.magic_number}: already assigned to '{existing_id}'"
                )

        if config.login <= 0:
            raise ValueError(f"Invalid MT5 login #{config.login} for account '{clean_id}'")

        pwd = config.resolve_password()
        if not pwd and not config.dry_run:
            raise ValueError(
                f"No password found for account '{clean_id}'. "
                f"Set 'password', specify a valid 'password_env_var', or set MT5_PASSWORD in .env"
            )

        if config.risk_per_trade_pct <= 0 or config.risk_per_trade_pct > 100.0:
            raise ValueError(
                f"Invalid risk_per_trade_pct ({config.risk_per_trade_pct}) for account '{clean_id}'"
            )

    def unregister(self, account_id: str) -> Optional[AccountConfig]:
        """Remove an account from the registry."""
        if account_id in self._accounts:
            cfg = self._accounts.pop(account_id)
            self._magic_to_account.pop(cfg.magic_number, None)
            logger.info(f"[REGISTRY] Unregistered account '{account_id}'")
            return cfg
        return None

    def get(self, account_id: str) -> Optional[AccountConfig]:
        """Retrieve account configuration by ID."""
        return self._accounts.get(account_id)

    def get_by_magic(self, magic: int) -> Optional[AccountConfig]:
        """Retrieve account configuration by unique magic number."""
        acct_id = self._magic_to_account.get(magic)
        return self._accounts.get(acct_id) if acct_id else None

    def get_all(self) -> List[AccountConfig]:
        """Return all registered accounts."""
        return list(self._accounts.values())

    def get_enabled(self) -> List[AccountConfig]:
        """Return only enabled accounts."""
        return [acc for acc in self._accounts.values() if acc.enabled]

    def clear(self) -> None:
        """Clear all accounts from registry."""
        self._accounts.clear()
        self._magic_to_account.clear()

    # ── Loading Mechanisms ───────────────────────────────────────────────────

    def load_from_dict_list(self, items: List[Dict[str, Any]]) -> int:
        """Load multiple account configurations from a list of dictionaries."""
        count = 0
        for item in items:
            # Handle nested mt5 / trading blocks if formatted that way
            acct_id = item.get("account_id") or item.get("id") or f"account_{count+1:03d}"
            mt5_block = item.get("mt5", {})
            trading_block = item.get("trading", {})

            cfg = AccountConfig(
                account_id=acct_id,
                enabled=item.get("enabled", True),
                trading_enabled=trading_block.get("enabled", item.get("trading_enabled", True)),
                login=int(mt5_block.get("login") or item.get("login") or 0),
                server=str(mt5_block.get("server") or item.get("server") or ""),
                password=str(mt5_block.get("password") or item.get("password") or ""),
                password_env_var=str(mt5_block.get("password_env_var") or item.get("password_env_var") or ""),
                terminal_path=str(mt5_block.get("terminal_path") or item.get("terminal_path") or settings.mt5.path),
                data_directory=str(mt5_block.get("data_directory") or item.get("data_directory") or ""),
                portable_terminal_directory=str(mt5_block.get("portable_terminal_directory") or item.get("portable_terminal_directory") or ""),
                company=str(mt5_block.get("company") or item.get("company") or ""),
                execution_status=str(item.get("execution_status") or "INITIALIZING"),
                magic_number=int(item.get("magic_number") or item.get("magic") or (20250701 + count)),
                symbols=list(item.get("symbols") or []),
                risk_per_trade_pct=float(trading_block.get("risk_per_trade_pct") or item.get("risk_per_trade_pct") or settings.risk.risk_per_trade_pct),
                risk_multiplier=float(trading_block.get("risk_multiplier") or item.get("risk_multiplier") or 1.0),
                daily_drawdown_limit_pct=float(trading_block.get("max_daily_loss") or item.get("daily_drawdown_limit_pct") or settings.risk.daily_dd_limit),
                weekly_drawdown_limit_pct=float(item.get("weekly_drawdown_limit_pct") or settings.risk.weekly_dd_limit),
                account_drawdown_limit_pct=float(item.get("account_drawdown_limit_pct") or settings.risk.account_dd_limit),
                max_open_trades=int(trading_block.get("max_positions") or item.get("max_open_trades") or settings.risk.max_open_trades),
                max_risk_exposure_pct=float(item.get("max_risk_exposure_pct") or settings.risk.max_risk_exposure),
                dry_run=bool(item.get("dry_run", os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes"))),
            )
            self.register(cfg)
            count += 1
        return count

    def load_from_file(self, file_path: Union[str, Path]) -> int:
        """
        Load accounts from a JSON file.
        Accepts list of accounts or object with an 'accounts' list key.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"[REGISTRY] Account configuration file not found at: {path}")
            return 0

        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)

        if isinstance(content, list):
            return self.load_from_dict_list(content)
        elif isinstance(content, dict) and "accounts" in content:
            return self.load_from_dict_list(content["accounts"])
        else:
            raise ValueError(f"Unrecognized configuration format in {path}")

    def load_default_from_env(self) -> AccountConfig:
        """
        Backward-compatibility loader:
        Constructs and registers a single default AccountConfig from current .env settings.
        Ensures existing `python main.py` runs with zero additional setup.
        """
        login = settings.mt5.login
        server = settings.mt5.server
        password = settings.mt5.password
        terminal_path = settings.mt5.path
        magic = settings.mt5.magic
        dry_run = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

        default_cfg = AccountConfig(
            account_id="account_default",
            enabled=True,
            trading_enabled=True,
            login=login,
            server=server,
            password=password,
            password_env_var="MT5_PASSWORD",
            terminal_path=terminal_path,
            magic_number=magic,
            symbols=[],
            risk_per_trade_pct=settings.risk.risk_per_trade_pct,
            daily_drawdown_limit_pct=settings.risk.daily_dd_limit,
            weekly_drawdown_limit_pct=settings.risk.weekly_dd_limit,
            account_drawdown_limit_pct=settings.risk.account_dd_limit,
            max_open_trades=settings.risk.max_open_trades,
            max_risk_exposure_pct=settings.risk.max_risk_exposure,
            dry_run=dry_run,
        )
        self.register(default_cfg)
        logger.info("[REGISTRY] Loaded single-account backward compatibility configuration from .env")
        return default_cfg
