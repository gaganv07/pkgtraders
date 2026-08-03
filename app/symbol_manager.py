"""
app/symbol_manager.py — Multi-Symbol Management & Discovery

Handles automatic detection, suffix resolution, market watch subscription,
specification caching, and market status verification for required symbols:
BTCUSD, XAUUSD, EURUSD, GBPUSD, USDJPY, US30, NAS100.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

#: Required symbols as specified in system requirements
REQUIRED_SYMBOLS = [
    "BTCUSD",
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "US30",
    "NAS100",
]

#: Multi-asset broker variant search patterns
_SYMBOL_VARIANTS: Dict[str, List[str]] = {
    "XAUUSD": ["XAUUSD", "XAUUSDm", "XAUUSD.a", "XAUUSD+", "XAUUSDp", "Gold", "GOLD", "XAU/USD", "XAUUSD.r"],
    "EURUSD": ["EURUSD", "EURUSDm", "EURUSD.a", "EURUSD+", "EURUSDp", "EUR/USD"],
    "GBPUSD": ["GBPUSD", "GBPUSDm", "GBPUSD.a", "GBPUSD+", "GBPUSDp", "GBP/USD"],
    "USDJPY": ["USDJPY", "USDJPYm", "USDJPY.a", "USDJPY+", "USDJPYp", "USD/JPY"],
    "NAS100": ["NAS100", "NAS100m", "NASDAQm", "NASDAQ", "US100", "US100m", "USTEC", "NAS100+", "USTECm"],
    "US30":   ["US30", "US30m", "DJ30", "DJIA", "DOW30", "WS30", "US30+", "US30.a", "USA30"],
    "BTCUSD": ["BTCUSD", "BTCUSDm", "BTCUSD+", "BTC/USD", "BITCOIN", "BTCUSDp"],
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
    Manages symbol discovery, Market Watch selection, and broker specs.
    """

    def __init__(self, symbols: Optional[List[str]] = None):
        self.target_symbols = symbols or REQUIRED_SYMBOLS
        self._symbol_map: Dict[str, str] = {}           # Canonical → Broker symbol
        self._reverse_map: Dict[str, str] = {}          # Broker symbol → Canonical
        self._specs_cache: Dict[str, SymbolSpec] = {}   # Canonical → SymbolSpec

    @property
    def symbol_map(self) -> Dict[str, str]:
        """Map of canonical symbol names to broker-specific symbols."""
        return dict(self._symbol_map)

    @property
    def active_canonical_symbols(self) -> List[str]:
        """List of canonical symbols successfully resolved on broker."""
        return list(self._symbol_map.keys())

    def resolve_broker_symbol(self, canonical: str) -> str:
        """Translate canonical name (e.g. XAUUSD) to broker name (e.g. XAUUSDm)."""
        return self._symbol_map.get(canonical, canonical)

    def resolve_canonical_symbol(self, broker_symbol: str) -> str:
        """Translate broker symbol (e.g. XAUUSDm) to canonical name (e.g. XAUUSD)."""
        return self._reverse_map.get(broker_symbol, broker_symbol)

    def initialize_symbols(self) -> Dict[str, str]:
        """
        Discover, verify, and enable all required symbols in MT5 Market Watch.
        Returns a mapping of canonical symbol names to discovered broker symbol names.
        """
        if not MT5_AVAILABLE:
            logger.warning("MT5 library unavailable — skipping live symbol discovery")
            for sym in self.target_symbols:
                self._symbol_map[sym] = sym
                self._reverse_map[sym] = sym
            return self._symbol_map

        logger.info(f"Discovering and initializing symbols: {self.target_symbols}")

        for canonical in self.target_symbols:
            broker_sym = self._discover_single_symbol(canonical)
            if broker_sym:
                # Enable in MT5 Market Watch
                select_ok = mt5.symbol_select(broker_sym, True)
                if not select_ok:
                    code, msg = mt5.last_error()
                    logger.warning(f"Failed to add {broker_sym} to Market Watch: [{code}] {msg}")

                self._symbol_map[canonical] = broker_sym
                self._reverse_map[broker_sym] = canonical

                # Cache symbol specifications
                spec = self._fetch_spec(canonical, broker_sym)
                if spec:
                    self._specs_cache[canonical] = spec

                logger.info(f"[OK] Symbol resolved: {canonical} -> {broker_sym}")
            else:
                logger.warning(
                    f"[WARN] Symbol '{canonical}' unavailable on current broker — skipping without crash"
                )

        logger.info(f"Symbol discovery complete. Total active: {len(self._symbol_map)}")
        return self._symbol_map

    def _discover_single_symbol(self, canonical: str) -> Optional[str]:
        """Find the broker-specific name for a given canonical symbol."""
        candidates = _SYMBOL_VARIANTS.get(canonical, [canonical])

        for candidate in candidates:
            info = mt5.symbol_info(candidate)
            if info is not None:
                return candidate

        # Fallback to fuzzy search among all available MT5 symbols
        all_symbols = mt5.symbols_get()
        if all_symbols:
            base_key = canonical[:3].upper()
            for s in all_symbols:
                if base_key in s.name.upper() and s.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED:
                    logger.info(f"Fuzzy matched {canonical} → {s.name}")
                    return s.name

        return None

    def _fetch_spec(self, canonical: str, broker_sym: str) -> Optional[SymbolSpec]:
        """Fetch and structure contract specs for a symbol."""
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
        """Get cached or refreshed symbol specification."""
        if canonical in self._specs_cache:
            return self._specs_cache[canonical]

        broker_sym = self.resolve_broker_symbol(canonical)
        spec = self._fetch_spec(canonical, broker_sym)
        if spec:
            self._specs_cache[canonical] = spec
        return spec

    def verify_symbol_tradeable(self, canonical: str) -> Tuple[bool, str]:
        """
        Verify safety constraint for trade placement:
          - Symbol exists on broker
          - Market is open / symbol trade_mode allows trading
        """
        if not MT5_AVAILABLE:
            return False, "MT5 library unavailable"

        broker_sym = self.resolve_broker_symbol(canonical)
        info = mt5.symbol_info(broker_sym)
        if info is None:
            return False, f"Symbol '{canonical}' ({broker_sym}) does not exist on broker"

        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Symbol '{canonical}' market is currently CLOSED or DISABLED for trading"

        return True, f"Symbol '{canonical}' is tradeable"
