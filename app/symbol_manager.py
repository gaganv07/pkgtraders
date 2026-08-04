"""
app/symbol_manager.py — Multi-Symbol Management & Automatic Discovery Engine

Provides dynamic, broker-agnostic symbol resolution for standard canonical assets:
XAUUSD, BTCUSD, EURUSD, GBPUSD, USDJPY, US30, NAS100 across ANY MT5 broker naming scheme
(e.g., XAUUSD.a, XAUUSDm, GOLD, GOLD.cash, USTEC, US100, DJ30, US30.cash, BTCUSD.r).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

REQUIRED_SYMBOLS = [
    "BTCUSD",
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "US30",
    "NAS100",
]

#: Expanded fallbacks and aliases dictionary for multi-broker matching
CANONICAL_ALIASES: Dict[str, List[str]] = {
    "XAUUSD": ["XAUUSD", "GOLD", "XAU/USD", "XAUUSD.a", "XAUUSDm", "XAUUSD+", "XAUUSDp", "XAUUSD.r", "GOLD.cash", "XAUUSD_M"],
    "EURUSD": ["EURUSD", "EUR/USD", "EURUSDm", "EURUSD.a", "EURUSD+", "EURUSDp", "EURUSD.r", "EURUSD_M"],
    "GBPUSD": ["GBPUSD", "GBP/USD", "GBPUSDm", "GBPUSD.a", "GBPUSD+", "GBPUSDp", "GBPUSD.r", "GBPUSD_M"],
    "USDJPY": ["USDJPY", "USD/JPY", "USDJPYm", "USDJPY.a", "USDJPY+", "USDJPYp", "USDJPY.r", "USDJPY_M"],
    "NAS100": ["NAS100", "NASDAQ", "US100", "USTEC", "NAS100m", "NASDAQm", "US100m", "USTECm", "NAS100.r", "NAS100.cash", "US100.cash"],
    "US30":   ["US30", "DJ30", "DJIA", "DOW30", "WS30", "US30m", "USA30", "US30.a", "US30.r", "US30.cash", "WALLSTREET"],
    "BTCUSD": ["BTCUSD", "BITCOIN", "BTC/USD", "BTCUSDm", "BTCUSD+", "BTCUSDp", "BTCUSD.r", "BTCUSD.cash"],
}


@dataclass
class SymbolSpec:
    canonical: str
    broker_symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    vol_min: float
    vol_max: float
    vol_step: float
    trade_mode: int
    path: str

    @property
    def is_tradeable(self) -> bool:
        """Check if trading is permitted on this symbol."""
        if not MT5_AVAILABLE or mt5 is None:
            return False
        return self.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED


class SymbolManager:
    """
    Manages dynamic symbol discovery, Market Watch auto-selection, and broker specs caching.
    Supports any MT5 broker without manual configuration.
    """

    def __init__(self, symbols: Optional[List[str]] = None):
        self.target_symbols = symbols or REQUIRED_SYMBOLS
        self._symbol_map: Dict[str, str] = {}           # Canonical -> Broker symbol
        self._reverse_map: Dict[str, str] = {}          # Broker symbol -> Canonical
        self._specs_cache: Dict[str, SymbolSpec] = {}   # Canonical -> SymbolSpec

    @property
    def symbol_map(self) -> Dict[str, str]:
        return dict(self._symbol_map)

    @property
    def active_canonical_symbols(self) -> List[str]:
        return list(self._symbol_map.keys())

    def resolve_broker_symbol(self, canonical: str) -> str:
        return self._symbol_map.get(canonical, canonical)

    def resolve_canonical_symbol(self, broker_symbol: str) -> str:
        return self._reverse_map.get(broker_symbol, broker_symbol)

    def initialize_symbols(self) -> Dict[str, str]:
        """
        Discover, verify, and enable all required symbols in MT5 Market Watch.
        Performs dynamic catalog discovery to match any broker's symbol naming.
        """
        if not MT5_AVAILABLE:
            logger.warning("[SYMBOL_MGR] MT5 library unavailable — setting standard defaults")
            for sym in self.target_symbols:
                self._symbol_map[sym] = sym
                self._reverse_map[sym] = sym
            return self._symbol_map

        logger.info(f"[SYMBOL_MGR] Initializing symbol discovery for {self.target_symbols}...")

        all_broker_symbols = mt5.symbols_get() or []
        catalog = {s.name: s for s in all_broker_symbols}

        for canonical in self.target_symbols:
            broker_sym = self._discover_symbol_dynamic(canonical, catalog)
            if broker_sym:
                select_ok = mt5.symbol_select(broker_sym, True)
                if not select_ok:
                    code, msg = mt5.last_error()
                    logger.warning(f"[SYMBOL_MGR] Could not enable {broker_sym} in Market Watch: [{code}] {msg}")

                self._symbol_map[canonical] = broker_sym
                self._reverse_map[broker_sym] = canonical

                spec = self._fetch_spec(canonical, broker_sym)
                if spec:
                    self._specs_cache[canonical] = spec

                logger.info(f"[SYMBOL_MGR] Resolved: {canonical} -> {broker_sym}")
            else:
                logger.warning(f"[SYMBOL_MGR] Could not resolve symbol '{canonical}' on current broker.")

        logger.info(f"[SYMBOL_MGR] Symbol discovery complete. Active: {len(self._symbol_map)}/{len(self.target_symbols)}")
        return self._symbol_map

    def _discover_symbol_dynamic(self, canonical: str, catalog: Dict[str, Any]) -> Optional[str]:
        """
        Dynamic multi-pass discovery algorithm:
        Pass 1: Direct match in alias list
        Pass 2: Match canonical base + auto-detected broker suffix/prefix
        Pass 3: Regex pattern match against catalog names
        Pass 4: Fuzzy substring matching in broker catalog
        """
        aliases = CANONICAL_ALIASES.get(canonical, [canonical])

        # Pass 1: Direct exact match in catalog
        for alias in aliases:
            if alias in catalog:
                info = catalog[alias]
                if info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED:
                    return alias

        # Pass 2: Search with prefixes and suffixes across catalog
        base_name = canonical.replace("/", "")
        for sname, sinfo in catalog.items():
            if sinfo.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                continue
            # Check if canonical base is contained inside sname (e.g. XAUUSD in XAUUSD.a, GOLD in GOLD.cash)
            clean_sname = re.sub(r'[^A-Z0-9]', '', sname.upper())
            for alias in aliases:
                clean_alias = re.sub(r'[^A-Z0-9]', '', alias.upper())
                if clean_alias in clean_sname or clean_sname in clean_alias:
                    logger.info(f"[SYMBOL_MGR] Dynamic match for {canonical}: {sname}")
                    return sname

        # Pass 3: Fuzzy keyword match in catalog names/paths
        key_term = canonical[:3] if len(canonical) >= 6 else canonical
        for sname, sinfo in catalog.items():
            if key_term in sname.upper() and sinfo.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED:
                logger.info(f"[SYMBOL_MGR] Fuzzy fallback match for {canonical}: {sname}")
                return sname

        return None

    def _fetch_spec(self, canonical: str, broker_sym: str) -> Optional[SymbolSpec]:
        if not MT5_AVAILABLE:
            return None

        info = mt5.symbol_info(broker_sym)
        if info is None:
            return None

        tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
        tick_val = info.trade_tick_value if info.trade_tick_value > 0 else info.point

        return SymbolSpec(
            canonical=canonical,
            broker_symbol=broker_sym,
            digits=info.digits,
            point=info.point,
            tick_size=tick_size,
            tick_value=tick_val,
            contract_size=info.trade_contract_size,
            vol_min=info.volume_min,
            vol_max=info.volume_max,
            vol_step=info.volume_step,
            trade_mode=info.trade_mode,
            path=info.path,
        )

    def get_symbol_spec(self, canonical: str) -> Optional[SymbolSpec]:
        if canonical in self._specs_cache:
            return self._specs_cache[canonical]

        broker_sym = self.resolve_broker_symbol(canonical)
        spec = self._fetch_spec(canonical, broker_sym)
        if spec:
            self._specs_cache[canonical] = spec
        return spec

    def verify_symbol_tradeable(self, canonical: str) -> Tuple[bool, str]:
        if not MT5_AVAILABLE:
            return False, "MT5 library unavailable"

        broker_sym = self.resolve_broker_symbol(canonical)
        info = mt5.symbol_info(broker_sym)
        if info is None:
            return False, f"Symbol '{canonical}' ({broker_sym}) does not exist on broker"

        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Symbol '{canonical}' is CLOSED or DISABLED for trading"

        return True, f"Symbol '{canonical}' is tradeable"
