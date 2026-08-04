"""
app/broker_adapter.py — Universal Broker Abstraction Engine

Provides dynamic, zero-hardcode detection of MT5 broker profiles, account capabilities,
execution modes, contract specifications, stop/freeze levels, and symbol naming conventions.
Supports any MT5-compatible broker (BlackBull, Vantage, IC Markets, Pepperstone, Eightcap,
FTMO, Fusion, Exness, RoboForex, XM, Tickmill, etc.).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class BrokerProfile:
    """
    Standardized, broker-agnostic profile detected dynamically from live MT5 connection.
    """
    company: str = "Unknown Broker"
    server: str = "Unknown Server"
    login: int = 0
    account_mode: str = "DEMO"  # DEMO, REAL, CONTEST
    currency: str = "USD"
    leverage: int = 100
    balance: float = 0.0
    equity: float = 0.0
    free_margin: float = 0.0
    margin_mode: int = 0
    trade_allowed: bool = False
    trade_expert: bool = False
    fifo_close: bool = False
    symbols_count: int = 0
    detected_suffixes: List[str] = field(default_factory=list)
    detected_prefixes: List[str] = field(default_factory=list)
    execution_modes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "server": self.server,
            "login": self.login,
            "account_mode": self.account_mode,
            "currency": self.currency,
            "leverage": self.leverage,
            "balance": self.balance,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "margin_mode": self.margin_mode,
            "trade_allowed": self.trade_allowed,
            "trade_expert": self.trade_expert,
            "fifo_close": self.fifo_close,
            "symbols_count": self.symbols_count,
            "detected_suffixes": self.detected_suffixes,
            "detected_prefixes": self.detected_prefixes,
        }


@dataclass
class BrokerSymbolSpec:
    """Broker-agnostic specification for a single symbol."""
    canonical_symbol: str
    broker_symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int
    freeze_level: int
    trade_mode: int
    execution_mode: str
    margin_initial: float
    margin_maintenance: float
    is_tradeable: bool
    path: str


class BrokerAdapter:
    """
    Universal MT5 Broker Abstraction Adapter.
    Inspects live MT5 environment to construct generic broker profiles.
    """

    EXECUTION_MODE_MAP = {
        0: "REQUEST",
        1: "INSTANT",
        2: "MARKET",
        3: "EXCHANGE",
    } if MT5_AVAILABLE else {}

    def __init__(self):
        self._profile: Optional[BrokerProfile] = None
        self._specs_cache: Dict[str, BrokerSymbolSpec] = {}

    @property
    def profile(self) -> BrokerProfile:
        if self._profile is None:
            self.refresh_profile()
        return self._profile or BrokerProfile()

    def refresh_profile(self) -> BrokerProfile:
        """Dynamically detect active broker parameters."""
        if not MT5_AVAILABLE:
            logger.warning("[BROKER_ADAPTER] MT5 package unavailable.")
            self._profile = BrokerProfile()
            return self._profile

        acct = mt5.account_info()
        term = mt5.terminal_info()

        if acct is None:
            logger.warning("[BROKER_ADAPTER] Unable to fetch account info from MT5.")
            self._profile = BrokerProfile()
            return self._profile

        mode_val = getattr(acct, "trade_mode", 0)
        mode_str = "DEMO" if mode_val == 0 else ("REAL" if mode_val == 2 else "CONTEST")

        all_symbols = mt5.symbols_get() or []
        suffixes, prefixes = self._detect_naming_conventions(all_symbols)

        self._profile = BrokerProfile(
            company=acct.company,
            server=acct.server,
            login=acct.login,
            account_mode=mode_str,
            currency=acct.currency,
            leverage=acct.leverage,
            balance=acct.balance,
            equity=acct.equity,
            free_margin=acct.margin_free,
            margin_mode=getattr(acct, "margin_mode", 0),
            trade_allowed=acct.trade_allowed,
            trade_expert=acct.trade_expert,
            fifo_close=getattr(acct, "fifo_close", False),
            symbols_count=len(all_symbols),
            detected_suffixes=list(suffixes),
            detected_prefixes=list(prefixes),
        )

        logger.info(
            f"[BROKER_ADAPTER] Profile loaded: {self._profile.company} | "
            f"Server={self._profile.server} | Mode={self._profile.account_mode} | "
            f"Balance=${self._profile.balance:,.2f}"
        )
        return self._profile

    def _detect_naming_conventions(self, symbols: List[Any]) -> Tuple[Set[str], Set[str]]:
        """Extract symbol suffixes (e.g. .a, m, +, .r, .cash) and prefixes dynamically."""
        suffixes: Set[str] = set()
        prefixes: Set[str] = set()

        known_bases = {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "US30", "NAS100", "GOLD", "USTEC", "DJ30"}

        for sym in symbols:
            name = sym.name
            for base in known_bases:
                if name.startswith(base) and len(name) > len(base):
                    suf = name[len(base):]
                    suffixes.add(suf)
                elif name.endswith(base) and len(name) > len(base):
                    pref = name[:-len(base)]
                    prefixes.add(pref)

        return suffixes, prefixes

    def inspect_symbol(self, canonical: str, broker_symbol: str) -> Optional[BrokerSymbolSpec]:
        """Fetch complete broker-agnostic symbol specifications."""
        if not MT5_AVAILABLE:
            return None

        info = mt5.symbol_info(broker_symbol)
        if info is None:
            return None

        tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
        tick_val = info.trade_tick_value if info.trade_tick_value > 0 else info.point
        exec_mode_int = getattr(info, "execution_mode", 2)
        exec_mode_str = self.EXECUTION_MODE_MAP.get(exec_mode_int, "MARKET")

        is_tradeable = (info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED) and info.visible

        spec = BrokerSymbolSpec(
            canonical_symbol=canonical,
            broker_symbol=broker_symbol,
            digits=info.digits,
            point=info.point,
            tick_size=tick_size,
            tick_value=tick_val,
            contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            stops_level=info.trade_stops_level,
            freeze_level=getattr(info, "trade_freeze_level", 0),
            trade_mode=info.trade_mode,
            execution_mode=exec_mode_str,
            margin_initial=getattr(info, "margin_initial", 0.0),
            margin_maintenance=getattr(info, "margin_maintenance", 0.0),
            is_tradeable=is_tradeable,
            path=info.path,
        )

        self._specs_cache[canonical] = spec
        return spec
