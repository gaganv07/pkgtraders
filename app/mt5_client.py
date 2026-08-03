"""
app/mt5_client.py — MetaTrader 5 Client

Full MT5 integration:
  - Auto-login, auto-reconnect, multi-symbol discovery
  - DOM subscription via market_book_add/get/release
  - BUY / SELL / Modify / Close / Partial close (all symbol-aware)
  - Retry logic with slippage control
  - Position reconciliation
  - Execution latency measurement

Multi-asset upgrade: all execution/data methods accept an optional
`symbol` parameter. Omitting it falls back to self._symbol (XAUUSD
or whatever primary symbol was discovered at connect time).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import settings, SYMBOL_CONFIGS, enabled_symbols
from app.mt5_connector import MT5Connector
from app.account_manager import AccountManager
from app.symbol_manager import SymbolManager
from app.market_feed import MarketFeed
from app.order_executor import OrderExecutor

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 not installed — simulation mode active")

# ── Primary symbol variants (XAUUSD discovery fallback) ──────────────────────
_XAUUSD_VARIANTS = [
    "XAUUSD", "XAUUSDm", "XAUUSD.a", "XAUUSD+", "XAUUSDp",
    "XAUUSD_", "XAUUSD.", "Gold", "GOLD", "XAU/USD", "XAUUSD.r",
]

# ── Multi-asset discovery variants (suffix permutations per base) ─────────────
_SYM_VARIANTS: Dict[str, List[str]] = {
    "XAUUSD":  ["XAUUSD", "XAUUSDm", "XAUUSD.a", "XAUUSD+", "XAUUSDp",
                 "Gold", "GOLD", "XAU/USD"],
    "EURUSD":  ["EURUSD", "EURUSDm", "EURUSD.a", "EURUSD+", "EURUSDp"],
    "GBPUSD":  ["GBPUSD", "GBPUSDm", "GBPUSD.a", "GBPUSD+", "GBPUSDp"],
    "USDJPY":  ["USDJPY", "USDJPYm", "USDJPY.a", "USDJPY+", "USDJPYp"],
    "NAS100":  ["NAS100", "NAS100m", "NASDAQm", "NASDAQ", "US100",
                 "US100m", "USTEC", "NAS100+"],
    "US30":    ["US30", "US30m", "DJ30", "DJIA", "DOW30", "WS30",
                 "US30+", "US30.a"],
    "BTCUSD":  ["BTCUSD", "BTCUSDm", "BTCUSD+", "BTC/USD",
                 "BITCOIN", "BTCUSDp"],
    "ETHUSD":  ["ETHUSD", "ETHUSDm", "ETHUSD+", "ETH/USD",
                 "ETHEREUM", "ETHUSDp"],
}

_RETCODE_DONE = 10009 if MT5_AVAILABLE else 0
_RETRYABLE_CODES = {10004, 10006, 10007, 10014, 10018, 10019, 10032}

# Simulated base prices for each symbol (used in no-MT5 simulation mode)
_SIM_PRICES: Dict[str, float] = {
    "XAUUSD": 1950.0,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2700,
    "USDJPY": 149.50,
    "NAS100": 18500.0,
    "US30":   39000.0,
    "BTCUSD": 67000.0,
    "ETHUSD": 3500.0,
}
_SIM_SPREADS: Dict[str, float] = {
    "XAUUSD": 0.15,
    "EURUSD": 0.00010,
    "GBPUSD": 0.00015,
    "USDJPY": 0.020,
    "NAS100": 5.0,
    "US30":   8.0,
    "BTCUSD": 50.0,
    "ETHUSD": 2.0,
}
_SIM_CONTRACT: Dict[str, float] = {
    "XAUUSD": 100.0,
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "USDJPY": 100_000.0,
    "NAS100": 1.0,
    "US30":   1.0,
    "BTCUSD": 1.0,
    "ETHUSD": 1.0,
}

# Full broker spec for each symbol in simulation mode
_SIM_TICK_SPECS: Dict[str, Dict] = {
    "XAUUSD": dict(digits=2,  point=0.01,   tick_size=0.01,   tick_value=1.00,   vol_min=0.01, vol_max=50.0,  vol_step=0.01),
    "EURUSD": dict(digits=5,  point=0.00001,tick_size=0.0001, tick_value=1.00,   vol_min=0.01, vol_max=150.0, vol_step=0.01),
    "GBPUSD": dict(digits=5,  point=0.00001,tick_size=0.0001, tick_value=1.00,   vol_min=0.01, vol_max=150.0, vol_step=0.01),
    "USDJPY": dict(digits=3,  point=0.001,  tick_size=0.001,  tick_value=0.0067, vol_min=0.01, vol_max=150.0, vol_step=0.01),
    "NAS100": dict(digits=2,  point=0.01,   tick_size=0.01,   tick_value=0.01,   vol_min=0.01, vol_max=50.0,  vol_step=0.01),
    "US30":   dict(digits=2,  point=0.01,   tick_size=0.01,   tick_value=0.01,   vol_min=0.01, vol_max=50.0,  vol_step=0.01),
    "BTCUSD": dict(digits=2,  point=0.01,   tick_size=0.01,   tick_value=0.01,   vol_min=0.01, vol_max=50.0,  vol_step=0.01),
    "ETHUSD": dict(digits=2,  point=0.01,   tick_size=0.01,   tick_value=0.01,   vol_min=0.01, vol_max=50.0,  vol_step=0.01),
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class FillResult:
    success:       bool
    ticket:        Optional[int] = None
    price:         float = 0.0
    volume:        float = 0.0
    retcode:       int = 0
    comment:       str = ""
    latency_ms:    float = 0.0
    slippage_pts:  float = 0.0
    error:         str = ""


@dataclass
class DOMLevel:
    price:  float
    volume: float
    side:   str   # "bid" | "ask"


@dataclass
class DOMSnapshot:
    timestamp: datetime
    bids: List[DOMLevel] = field(default_factory=list)
    asks: List[DOMLevel] = field(default_factory=list)
    available: bool = False


@dataclass
class PositionSnapshot:
    ticket:       int
    symbol:       str
    direction:    str
    volume:       float
    open_price:   float
    current_price: float
    sl:           float
    tp:           float
    profit:       float
    swap:         float
    magic:        int
    comment:      str
    open_time:    datetime


# ── MT5Client ─────────────────────────────────────────────────────────────────

class MT5Client:
    """
    Full MetaTrader 5 client — multi-asset capable.

    All execution and data methods now accept an optional `symbol`
    parameter. When omitted they fall back to self._symbol (the primary
    symbol discovered at connect time — usually XAUUSD).

    Backwards-compatible: existing callers that don't pass `symbol` work
    exactly as before.
    """

    def __init__(self):
        self._cfg        = settings.mt5
        self._connected  = False
        self._sim_mode   = True           # True until a successful live MT5 connect
        self._symbol:    Optional[str] = None
        self._sym_info:  Optional[Any] = None
        self._dom_active = False
        self._reconnects = 0
        self._exec_fails = 0
        self._sym_map:   Dict[str, str] = {}
        self._sym_info_cache: Dict[str, Any] = {}

        # ── Modular Integration Components ─────────────────────────────────
        self.connector = MT5Connector(
            login=self._cfg.login,
            password=self._cfg.password,
            server=self._cfg.server,
            path=self._cfg.path,
            timeout_ms=self._cfg.timeout_ms,
        )
        self.account_mgr = AccountManager()
        self.symbol_mgr = SymbolManager()
        self.market_feed = MarketFeed(symbol_resolver=self.symbol_mgr)
        self.order_exec = OrderExecutor(
            symbol_manager=self.symbol_mgr,
            account_manager=self.account_mgr,
            magic=self._cfg.magic,
            deviation_pts=self._cfg.deviation_pts,
        )

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def symbol(self) -> Optional[str]:
        return self._symbol

    @property
    def dom_active(self) -> bool:
        return self._dom_active

    @property
    def active_symbols(self) -> List[str]:
        """Returns canonical symbol names that were successfully discovered."""
        return list(self._sym_map.keys())

    def resolve(self, symbol: str) -> str:
        """Translate canonical name (e.g. XAUUSD) → broker name (e.g. XAUUSDm)."""
        return self._sym_map.get(symbol, symbol)

    # ── Connection ───────────────────────────────────────────────────────────

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            self._connected = True
            self._sim_mode  = True
            primary = self._cfg.symbol_override or "XAUUSD"
            self._symbol = primary
            for sym in enabled_symbols():
                self._sym_map[sym] = sym
            logger.info(f"MT5 simulation mode (no library) — symbols={list(self._sym_map)}")
            return True

        # Use MT5Connector for robust connection and safety verification
        res = self.connector.connect()
        if not res.success or not res.safety_passed:
            err_msg = f"ERROR: Connected to the wrong account. Status: success={res.success}, safety={res.safety_passed} ({res.safety_reason or res.error_message})"
            logger.critical(err_msg)
            print("\nERROR: Connected to the wrong account.\n")
            raise RuntimeError("ERROR: Connected to the wrong account.")

        # Fully live connection
        self._sim_mode = False
        self._connected = True
        self._reconnects += 1

        # Use SymbolManager for multi-symbol discovery
        discovered = self.symbol_mgr.initialize_symbols()
        self._sym_map = discovered

        primary = self._sym_map.get("XAUUSD") or self._discover_primary() or "XAUUSD"
        self._symbol = primary

        # Subscribe to DOM on primary
        if self._cfg.dom_subscribe:
            self._subscribe_dom(self._symbol)

        return True

    def disconnect(self) -> None:
        if self._dom_active and MT5_AVAILABLE and not self._sim_mode and self._symbol:
            try:
                mt5.market_book_release(self._symbol)
            except Exception:
                pass
        if MT5_AVAILABLE and self._connected and not self._sim_mode:
            mt5.shutdown()
        self._connected = False
        self._dom_active = False

    def reconnect(self) -> bool:
        for attempt in range(self._cfg.reconnect_attempts):
            delay = min(self._cfg.reconnect_delay_s * (2 ** min(attempt, 6)), 120)
            logger.info(f"Reconnect attempt {attempt + 1} in {delay:.0f}s")
            time.sleep(delay)
            self.disconnect()
            if self.connect():
                logger.info("MT5 reconnected")
                return True
        logger.critical("MT5 reconnect exhausted")
        return False

    def heartbeat(self) -> bool:
        if not MT5_AVAILABLE:
            return True
        return mt5.terminal_info() is not None

    # ── Symbol discovery ─────────────────────────────────────────────────────

    def _discover_primary(self) -> Optional[str]:
        """Discover the primary XAUUSD symbol."""
        if self._cfg.symbol_override:
            info = mt5.symbol_info(self._cfg.symbol_override)
            if info and info.trade_mode != 0:
                mt5.symbol_select(self._cfg.symbol_override, True)
                return self._cfg.symbol_override

        for candidate in _XAUUSD_VARIANTS:
            info = mt5.symbol_info(candidate)
            if info and info.trade_mode != 0:
                mt5.symbol_select(candidate, True)
                return candidate

        # Fuzzy search
        all_syms = mt5.symbols_get()
        if all_syms:
            for s in all_syms:
                if ("XAU" in s.name.upper() or "GOLD" in s.name.upper()) and s.trade_mode != 0:
                    mt5.symbol_select(s.name, True)
                    logger.info(f"Fuzzy matched primary: {s.name}")
                    return s.name
        return None

    def _discover_all_symbols(self) -> None:
        """
        Discover all enabled symbols from config, resolving broker-specific names.
        Populates self._sym_map: canonical → broker name.
        """
        if not MT5_AVAILABLE:
            return

        for canonical, cfg in SYMBOL_CONFIGS.items():
            if not cfg.enabled:
                continue
            if canonical in self._sym_map:
                continue  # already mapped (primary XAUUSD)

            variants = _SYM_VARIANTS.get(canonical, [canonical])
            found = False
            for candidate in variants:
                info = mt5.symbol_info(candidate)
                if info and info.trade_mode != 0:
                    mt5.symbol_select(candidate, True)
                    self._sym_map[canonical] = candidate
                    self._sym_info_cache[candidate] = info
                    logger.info(f"Discovered {canonical} → {candidate}")
                    found = True
                    break

            if not found:
                # Fuzzy fallback
                all_syms = mt5.symbols_get()
                if all_syms:
                    base = canonical[:3].upper()
                    for s in all_syms:
                        if base in s.name.upper() and s.trade_mode != 0:
                            mt5.symbol_select(s.name, True)
                            self._sym_map[canonical] = s.name
                            self._sym_info_cache[s.name] = mt5.symbol_info(s.name)
                            logger.info(f"Fuzzy matched {canonical} → {s.name}")
                            found = True
                            break

            if not found:
                logger.warning(f"Symbol {canonical} not found on broker — skipping")

        logger.info(f"Symbol map: {self._sym_map}")

    def _subscribe_dom(self, broker_sym: str) -> None:
        if not MT5_AVAILABLE:
            return
        try:
            if mt5.market_book_add(broker_sym):
                self._dom_active = True
                logger.info(f"DOM subscription active for {broker_sym}")
            else:
                logger.info("DOM not available for this broker — using tick fallback")
        except Exception as e:
            logger.debug(f"DOM subscribe error: {e}")

    # ── Market data ──────────────────────────────────────────────────────────

    def get_tick(self, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch latest tick for symbol (defaults to primary symbol)."""
        broker_sym = self._get_broker_sym(symbol)

        if self._sim_mode:
            import random
            base = _SIM_PRICES.get(symbol or "XAUUSD", 1950.0)
            spread = _SIM_SPREADS.get(symbol or "XAUUSD", 0.15)
            p = base + random.uniform(-base * 0.001, base * 0.001)
            return {
                "bid": p, "ask": p + spread, "last": p,
                "volume": random.randint(1, 50),
                "time": datetime.now(timezone.utc), "flags": 134,
            }

        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return None
        return {
            "bid": tick.bid, "ask": tick.ask, "last": tick.last,
            "volume": tick.volume,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
            "flags": tick.flags,
        }

    def get_dom(self, symbol: Optional[str] = None) -> DOMSnapshot:
        """Fetch DOM snapshot (primary symbol only for DOM subscription)."""
        snap = DOMSnapshot(timestamp=datetime.now(timezone.utc))
        if self._sim_mode or not self._dom_active:
            return snap

        broker_sym = self._get_broker_sym(symbol)
        try:
            book = mt5.market_book_get(broker_sym)
        except Exception:
            book = None

        if book is None:
            return snap

        snap.available = True
        for entry in book:
            level = DOMLevel(
                price=entry.price, volume=entry.volume,
                side="bid" if entry.type == mt5.BOOK_TYPE_BUY else "ask",
            )
            if level.side == "bid":
                snap.bids.append(level)
            else:
                snap.asks.append(level)

        snap.bids.sort(key=lambda x: -x.price)
        snap.asks.sort(key=lambda x:  x.price)
        return snap

    def get_rates(
        self,
        tf_mt5: int,
        count: int = 300,
        symbol: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch OHLCV bars for symbol."""
        broker_sym = self._get_broker_sym(symbol)

        if self._sim_mode:
            import random
            base = _SIM_PRICES.get(symbol or "XAUUSD", 1950.0)
            bars = []
            p = base
            for _ in range(count):
                o = p + random.uniform(-base * 0.0005, base * 0.0005)
                h = o + random.uniform(0, base * 0.001)
                lo = o - random.uniform(0, base * 0.001)
                c = random.uniform(lo, h)
                bars.append({
                    "time": datetime.now(timezone.utc),
                    "open": o, "high": h, "low": lo, "close": c,
                    "tick_volume": random.randint(100, 1000),
                    "spread": int(_SIM_SPREADS.get(symbol or "XAUUSD", 0.15) * 100),
                    "real_volume": 0,
                })
                p = c
            return bars

        rates = mt5.copy_rates_from_pos(broker_sym, tf_mt5, 0, count)
        if rates is None:
            return []
        return [
            {
                "time": datetime.fromtimestamp(r[0], tz=timezone.utc),
                "open": r[1], "high": r[2], "low": r[3], "close": r[4],
                "tick_volume": r[5], "spread": r[6], "real_volume": r[7],
            }
            for r in rates
        ]

    def get_account(self) -> Optional[Dict[str, Any]]:
        if self._sim_mode:
            return {
                "login": self._cfg.login,
                "broker": "Simulated Broker",
                "server": self._cfg.server or "Simulated Server",
                "trade_mode": 0,
                "leverage": 100,
                "name": "Simulation User",
                "balance": 500.0, "equity": 500.0, "margin": 0.0,
                "free_margin": 500.0, "margin_level": 0.0,
                "profit": 0.0, "currency": "USD",
            }
        info = mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "broker": info.company,
            "server": info.server,
            "trade_mode": getattr(info, "trade_mode", 0),
            "leverage": getattr(info, "leverage", 1),
            "name": getattr(info, "name", ""),
            "balance": info.balance, "equity": info.equity,
            "margin": info.margin, "free_margin": info.margin_free,
            "margin_level": info.margin_level, "profit": info.profit,
            "currency": info.currency,
        }

    def get_symbol_spec(self, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch broker contract spec for symbol."""
        broker_sym = self._get_broker_sym(symbol)
        canonical  = symbol or "XAUUSD"

        if self._sim_mode:
            canonical = symbol or "XAUUSD"
            spec = _SIM_TICK_SPECS.get(canonical, _SIM_TICK_SPECS["XAUUSD"])
            return {
                "digits":        spec["digits"],
                "point":         spec["point"],
                "spread":        int(_SIM_SPREADS.get(canonical, 0.15) / spec["tick_size"]),
                "contract_size": _SIM_CONTRACT.get(canonical, 100.0),
                "vol_min":       spec["vol_min"],
                "vol_max":       spec["vol_max"],
                "vol_step":      spec["vol_step"],
                "bid":           _SIM_PRICES.get(canonical, 1950.0),
                "ask":           _SIM_PRICES.get(canonical, 1950.0) + _SIM_SPREADS.get(canonical, 0.15),
                "tick_size":     spec["tick_size"],
                "tick_value":    spec["tick_value"],
            }

        # Use cached info, refresh if stale
        info = self._sym_info_cache.get(broker_sym) or mt5.symbol_info(broker_sym)
        if info is None:
            return None
        return {
            "digits": info.digits,
            "point": info.point,
            "spread": info.spread,
            "contract_size": info.trade_contract_size,
            "vol_min": info.volume_min,
            "vol_max": info.volume_max,
            "vol_step": info.volume_step,
            "bid": info.bid,
            "ask": info.ask,
            "tick_size": info.trade_tick_size if info.trade_tick_size > 0 else info.point,
            "tick_value": info.trade_tick_value if info.trade_tick_value > 0 else info.point,
        }

    # ── Order execution ──────────────────────────────────────────────────────

    def buy(
        self,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "",
        symbol: Optional[str] = None,
    ) -> FillResult:
        broker_sym = self._get_broker_sym(symbol)

        if self._sim_mode:
            return self._sim_fill(volume, symbol)

        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return FillResult(success=False, error="No tick")
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       broker_sym,
            "volume":       float(volume),
            "type":         mt5.ORDER_TYPE_BUY,
            "price":        tick.ask,
            "sl":           float(sl),
            "tp":           float(tp),
            "deviation":    self._cfg.deviation_pts,
            "magic":        self._cfg.magic,
            "comment":      comment[:31],
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_type(broker_sym),
        }
        result = self._send(req, broker_sym)
        if result.success:
            result.slippage_pts = abs(result.price - tick.ask)
        return result

    def sell(
        self,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "",
        symbol: Optional[str] = None,
    ) -> FillResult:
        broker_sym = self._get_broker_sym(symbol)

        if self._sim_mode:
            return self._sim_fill(volume, symbol)

        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            return FillResult(success=False, error="No tick")
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       broker_sym,
            "volume":       float(volume),
            "type":         mt5.ORDER_TYPE_SELL,
            "price":        tick.bid,
            "sl":           float(sl),
            "tp":           float(tp),
            "deviation":    self._cfg.deviation_pts,
            "magic":        self._cfg.magic,
            "comment":      comment[:31],
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_type(broker_sym),
        }
        result = self._send(req, broker_sym)
        if result.success:
            result.slippage_pts = abs(result.price - tick.bid)
        return result

    def modify(
        self,
        ticket: int,
        sl: float,
        tp: float,
        symbol: Optional[str] = None,
    ) -> FillResult:
        broker_sym = self._get_broker_sym(symbol)

        if self._sim_mode:
            return FillResult(success=True, ticket=ticket)
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   broker_sym,
            "position": ticket,
            "sl":       float(sl),
            "tp":       float(tp),
        }
        result = mt5.order_send(req)
        if result and result.retcode == _RETCODE_DONE:
            return FillResult(success=True, ticket=ticket)
        err = result.comment if result else "None"
        return FillResult(success=False, ticket=ticket, error=err)

    def close(
        self,
        ticket: int,
        volume: Optional[float] = None,
        reason: str = "manual",
        symbol: Optional[str] = None,
    ) -> FillResult:
        if self._sim_mode:
            return FillResult(success=True, ticket=ticket,
                              price=_SIM_PRICES.get(symbol or "XAUUSD", 1950.0))

        broker_sym = self._get_broker_sym(symbol)
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return FillResult(success=False, error=f"Ticket {ticket} not found")

        pos = positions[0]
        vol = volume or pos.volume
        close_type = (mt5.ORDER_TYPE_SELL
                      if pos.type == mt5.POSITION_TYPE_BUY
                      else mt5.ORDER_TYPE_BUY)
        tick = mt5.symbol_info_tick(broker_sym)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       broker_sym,
            "volume":       float(vol),
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    self._cfg.deviation_pts,
            "magic":        self._cfg.magic,
            "comment":      f"close:{reason}"[:31],
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        return self._send(req, broker_sym)

    def close_all(self, reason: str = "emergency") -> int:
        """Close all magic-matched positions across all symbols."""
        positions = self.get_positions()
        closed = 0
        for pos in positions:
            # Determine canonical symbol for close method
            canonical = pos.symbol
            result = self.close(pos.ticket, reason=reason, symbol=canonical)
            if result.success:
                closed += 1
        return closed

    # ── Positions ────────────────────────────────────────────────────────────

    def get_positions(self, symbol: Optional[str] = None) -> List[PositionSnapshot]:
        """
        Get all open positions.
        If symbol is None, returns positions across ALL symbols (magic-matched).
        If symbol is given, filters to that symbol only.
        """
        if self._sim_mode:
            return []

        if symbol is not None:
            broker_sym = self._get_broker_sym(symbol)
            positions_raw = mt5.positions_get(symbol=broker_sym)
        else:
            positions_raw = mt5.positions_get()

        if positions_raw is None:
            return []

        out = []
        for p in positions_raw:
            if p.magic != self._cfg.magic:
                continue
            out.append(PositionSnapshot(
                ticket=p.ticket, symbol=p.symbol,
                direction="BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                volume=p.volume, open_price=p.price_open,
                current_price=p.price_current, sl=p.sl, tp=p.tp,
                profit=p.profit, swap=p.swap, magic=p.magic,
                comment=p.comment,
                open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
            ))
        return out

    def get_history(self, from_dt: datetime, to_dt: datetime) -> List[Dict]:
        if self._sim_mode:
            return []
        deals = mt5.history_deals_get(from_dt, to_dt)
        if deals is None:
            return []
        return [
            {
                "ticket": d.ticket, "order": d.order,
                "time": datetime.fromtimestamp(d.time, tz=timezone.utc),
                "type": d.type, "volume": d.volume, "price": d.price,
                "commission": d.commission, "swap": d.swap,
                "profit": d.profit, "comment": d.comment,
                "symbol": getattr(d, "symbol", ""),
            }
            for d in deals if d.magic == self._cfg.magic
        ]

    # ── Internals ────────────────────────────────────────────────────────────

    def _get_broker_sym(self, symbol: Optional[str]) -> str:
        """Resolve canonical symbol name to broker-specific name."""
        if symbol is None:
            return self._symbol or "XAUUSD"
        return self._sym_map.get(symbol, symbol)

    def _send(self, req: Dict[str, Any], broker_sym: str, retries: int = 3) -> FillResult:
        if self._sim_mode:
            return self._sim_fill(req.get("volume", 0.01), broker_sym)

        for attempt in range(retries):
            t0 = time.perf_counter()
            result = mt5.order_send(req)
            lat = (time.perf_counter() - t0) * 1000

            if result is None:
                logger.warning(f"order_send None: {mt5.last_error()} (attempt {attempt+1})")
                time.sleep(0.3 * (attempt + 1))
                continue

            if result.retcode == _RETCODE_DONE:
                self._exec_fails = 0
                return FillResult(
                    success=True, ticket=result.order, price=result.price,
                    volume=result.volume, retcode=result.retcode,
                    comment=result.comment, latency_ms=lat,
                )

            if result.retcode in _RETRYABLE_CODES and attempt < retries - 1:
                logger.warning(f"Retryable {result.retcode} {result.comment}")
                tick = mt5.symbol_info_tick(broker_sym)
                if tick and req.get("type") == mt5.ORDER_TYPE_BUY:
                    req["price"] = tick.ask
                elif tick and req.get("type") == mt5.ORDER_TYPE_SELL:
                    req["price"] = tick.bid
                time.sleep(0.2 * (attempt + 1))
                continue

            self._exec_fails += 1
            return FillResult(
                success=False, retcode=result.retcode,
                comment=result.comment, latency_ms=lat,
                error=f"retcode={result.retcode} {result.comment}",
            )

        self._exec_fails += 1
        return FillResult(success=False, error="Max retries exceeded")

    def _sim_fill(self, volume: float, symbol: Optional[str]) -> FillResult:
        """Simulation mode fill with realistic price."""
        import random
        canonical = symbol or "XAUUSD"
        price = _SIM_PRICES.get(canonical, 1950.0) + random.uniform(-0.5, 0.5)
        return FillResult(
            success=True,
            ticket=random.randint(100_000, 999_999),
            price=price,
            volume=float(volume),
            retcode=10009,
            latency_ms=random.uniform(10, 60),
        )

    def _filling_type(self, broker_sym: str) -> int:
        if not MT5_AVAILABLE:
            return 0
        info = mt5.symbol_info(broker_sym)
        if info and (info.filling_mode & mt5.ORDER_FILLING_FOK):
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_IOC

    @property
    def exec_failures(self) -> int:
        return self._exec_fails
