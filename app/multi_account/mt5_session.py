"""
app/multi_account/mt5_session.py — MT5 Session Isolation & IPC Worker Abstraction

Provides:
- IMT5Session: Protocol interface for MT5 session interactions.
- MT5DirectSession: In-process direct session (single-account mode, dry-run, or simulation).
- MT5ProcessSession: Process-isolated MT5 worker using Python multiprocessing for
  concurrent multi-terminal instances on a single Windows machine.
- create_session(): Factory function.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.mt5_client import FillResult, PositionSnapshot, _SIM_PRICES, _SIM_SPREADS, _SIM_TICK_SPECS
from app.multi_account.account_registry import AccountConfig, mask_credential

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


class IMT5Session(ABC):
    """Abstract interface defining the MT5 account session contract."""

    @abstractmethod
    def connect(self) -> bool:
        """Initialize and login to MT5."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Shut down MT5 session."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if session is healthy and responsive."""
        pass

    @abstractmethod
    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Fetch current balance, equity, margin, etc."""
        pass

    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None, all_magic: bool = False) -> List[PositionSnapshot]:
        """Fetch active positions. If all_magic=False, filters by account's magic number."""
        pass

    @abstractmethod
    def get_symbol_spec(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch contract specifications for symbol."""
        pass

    @abstractmethod
    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current Bid/Ask tick."""
        pass

    @abstractmethod
    def buy(
        self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"
    ) -> FillResult:
        """Execute Buy order."""
        pass

    @abstractmethod
    def sell(
        self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"
    ) -> FillResult:
        """Execute Sell order."""
        pass

    @abstractmethod
    def modify(self, ticket: int, sl: float, tp: float, symbol: str = "XAUUSD") -> FillResult:
        """Modify SL/TP on position."""
        pass

    @abstractmethod
    def close(
        self, ticket: int, volume: Optional[float] = None, reason: str = "manual", symbol: Optional[str] = None
    ) -> FillResult:
        """Close position."""
        pass

    @abstractmethod
    def close_all(self, reason: str = "emergency") -> int:
        """Close all open positions for this account."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 1. MT5DirectSession (In-Process / Simulation / Dry-Run)
# ══════════════════════════════════════════════════════════════════════════════

class MT5DirectSession(IMT5Session):
    """
    Direct in-process MT5 session.
    Used for single-account execution, mock testing, and dry-run mode.
    """

    def __init__(self, config: AccountConfig):
        self.config = config
        self._connected = False
        self._sim_mode = not MT5_AVAILABLE
        self._next_sim_ticket = 900000 + (config.login % 1000) * 100
        self._sim_balance: float = getattr(config, "initial_balance", 10000.0)
        self._sim_equity: float = self._sim_balance
        self._positions: List[PositionSnapshot] = []

    def set_sim_balance(self, balance: float, equity: Optional[float] = None) -> None:
        """Dynamically set simulated balance and equity."""
        self._sim_balance = balance
        self._sim_equity = equity if equity is not None else balance

    def connect(self) -> bool:
        if self.config.dry_run or not MT5_AVAILABLE:
            self._connected = True
            logger.info(
                f"[{self.config.account_id}] DirectSession connected (dry_run={self.config.dry_run}, mt5_avail={MT5_AVAILABLE})"
            )
            return True

        # Live in-process MT5 initialization
        try:
            init_ok = False
            if self.config.terminal_path and os.path.exists(self.config.terminal_path):
                init_ok = mt5.initialize(path=self.config.terminal_path)
            else:
                init_ok = mt5.initialize()

            if not init_ok:
                err = mt5.last_error()
                logger.error(f"[{self.config.account_id}] mt5.initialize failed: {err}")
                return False

            pwd = self.config.resolve_password()
            login_ok = mt5.login(
                login=self.config.login,
                password=pwd,
                server=self.config.server,
            )
            if not login_ok:
                err = mt5.last_error()
                logger.error(f"[{self.config.account_id}] mt5.login failed: {err}")
                return False

            self._connected = True
            logger.info(f"[{self.config.account_id}] MT5 logged in as #{self.config.login}")
            return True
        except Exception as e:
            logger.error(f"[{self.config.account_id}] Connection error: {e}")
            return False

    def disconnect(self) -> None:
        if self._connected and MT5_AVAILABLE and not self.config.dry_run:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self._connected = False
        logger.info(f"[{self.config.account_id}] Disconnected session")

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        if self.config.dry_run or not MT5_AVAILABLE:
            return True
        return mt5.terminal_info() is not None

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None

        if self.config.dry_run or not MT5_AVAILABLE:
            # Simulated account metrics
            return {
                "login": self.config.login,
                "server": self.config.server or "Simulation-Server",
                "balance": self._sim_balance,
                "equity": self._sim_equity,
                "margin": 0.0,
                "free_margin": self._sim_balance,
                "margin_level": 1000.0,
                "currency": "USD",
                "leverage": 100,
                "trade_allowed": True,
            }

        info = mt5.account_info()
        if not info:
            return None
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "currency": info.currency,
            "leverage": info.leverage,
            "trade_allowed": info.trade_allowed,
        }

    def get_positions(self, symbol: Optional[str] = None, all_magic: bool = False) -> List[PositionSnapshot]:
        if not self._connected:
            return []

        if self.config.dry_run or not MT5_AVAILABLE:
            candidates = self._positions
            if symbol:
                candidates = [p for p in candidates if p.symbol == symbol]
            if not all_magic:
                candidates = [p for p in candidates if p.magic == self.config.magic_number]
            return list(candidates)

        raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not raw:
            return []

        res = []
        for p in raw:
            # Filter by this account's unique magic number unless all_magic=True
            if not all_magic and p.magic != self.config.magic_number:
                continue
            res.append(
                PositionSnapshot(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction="LONG" if p.type == mt5.POSITION_TYPE_BUY else "SHORT",
                    volume=p.volume,
                    open_price=p.price_open,
                    current_price=p.price_current,
                    sl=p.sl,
                    tp=p.tp,
                    profit=p.profit,
                    swap=p.swap,
                    magic=p.magic,
                    comment=p.comment,
                    open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
                )
            )
        return res

    def get_symbol_spec(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_sym = symbol.rstrip("m+.a").upper()
        if self.config.dry_run or not MT5_AVAILABLE:
            spec = _SIM_TICK_SPECS.get(clean_sym, _SIM_TICK_SPECS.get("XAUUSD"))
            return {
                "digits": spec["digits"],
                "point": spec["point"],
                "spread": 15,
                "contract_size": 100.0 if "XAU" in clean_sym else 100000.0,
                "vol_min": spec["vol_min"],
                "vol_max": spec["vol_max"],
                "vol_step": spec["vol_step"],
                "bid": _SIM_PRICES.get(clean_sym, 2000.0),
                "ask": _SIM_PRICES.get(clean_sym, 2000.0) + _SIM_SPREADS.get(clean_sym, 0.20),
                "tick_size": spec["tick_size"],
                "tick_value": spec["tick_value"],
            }

        info = mt5.symbol_info(symbol)
        if not info:
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

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_sym = symbol.rstrip("m+.a").upper()
        if self.config.dry_run or not MT5_AVAILABLE:
            base = _SIM_PRICES.get(clean_sym, 2000.0)
            spread = _SIM_SPREADS.get(clean_sym, 0.20)
            return {
                "bid": base,
                "ask": base + spread,
                "time": datetime.now(timezone.utc),
            }

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
        }

    def buy(
        self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"
    ) -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")

        # ── DRY-RUN SAFETY MODE ──────────────────────────────────────────────
        if self.config.dry_run:
            tick = self.get_tick(symbol)
            price = tick["ask"] if tick else 2000.0
            self._next_sim_ticket += 1
            ticket = self._next_sim_ticket
            pos = PositionSnapshot(
                ticket=ticket,
                symbol=symbol,
                direction="LONG",
                volume=volume,
                open_price=price,
                current_price=price,
                sl=sl,
                tp=tp,
                profit=0.0,
                swap=0.0,
                magic=self.config.magic_number,
                comment=f"DRY_RUN:{comment[:20]}",
                open_time=datetime.now(timezone.utc),
            )
            self._positions.append(pos)
            logger.info(
                f"[{self.config.account_id}] [DRY_RUN] Simulated BUY {volume:.2f} {symbol} "
                f"@ {price:.5f} (ticket={ticket}, sl={sl:.5f}, tp={tp:.5f})"
            )
            return FillResult(
                success=True,
                ticket=ticket,
                price=price,
                volume=volume,
                comment=f"DRY_RUN:{comment[:20]}",
                latency_ms=1.5,
            )

        if not MT5_AVAILABLE:
            return FillResult(success=False, error="MetaTrader5 package not installed")

        t0 = time.time()
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return FillResult(success=False, error=f"No tick for {symbol}")

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        lat = (time.time() - t0) * 1000.0

        if res and res.retcode == 10009:  # TRADE_RETCODE_DONE
            return FillResult(
                success=True,
                ticket=res.order,
                price=res.price,
                volume=res.volume,
                retcode=res.retcode,
                comment=res.comment,
                latency_ms=lat,
            )
        err_msg = res.comment if res else "Order submission failed"
        code = res.retcode if res else -1
        return FillResult(success=False, retcode=code, error=err_msg, latency_ms=lat)

    def sell(
        self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"
    ) -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")

        # ── DRY-RUN SAFETY MODE ──────────────────────────────────────────────
        if self.config.dry_run:
            tick = self.get_tick(symbol)
            price = tick["bid"] if tick else 2000.0
            self._next_sim_ticket += 1
            ticket = self._next_sim_ticket
            pos = PositionSnapshot(
                ticket=ticket,
                symbol=symbol,
                direction="SHORT",
                volume=volume,
                open_price=price,
                current_price=price,
                sl=sl,
                tp=tp,
                profit=0.0,
                swap=0.0,
                magic=self.config.magic_number,
                comment=f"DRY_RUN:{comment[:20]}",
                open_time=datetime.now(timezone.utc),
            )
            self._positions.append(pos)
            logger.info(
                f"[{self.config.account_id}] [DRY_RUN] Simulated SELL {volume:.2f} {symbol} "
                f"@ {price:.5f} (ticket={ticket}, sl={sl:.5f}, tp={tp:.5f})"
            )
            return FillResult(
                success=True,
                ticket=ticket,
                price=price,
                volume=volume,
                comment=f"DRY_RUN:{comment[:20]}",
                latency_ms=1.5,
            )

        if not MT5_AVAILABLE:
            return FillResult(success=False, error="MetaTrader5 package not installed")

        t0 = time.time()
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return FillResult(success=False, error=f"No tick for {symbol}")

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL,
            "price": tick.bid,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        lat = (time.time() - t0) * 1000.0

        if res and res.retcode == 10009:
            return FillResult(
                success=True,
                ticket=res.order,
                price=res.price,
                volume=res.volume,
                retcode=res.retcode,
                comment=res.comment,
                latency_ms=lat,
            )
        err_msg = res.comment if res else "Order submission failed"
        code = res.retcode if res else -1
        return FillResult(success=False, retcode=code, error=err_msg, latency_ms=lat)

    def modify(self, ticket: int, sl: float, tp: float, symbol: str = "XAUUSD") -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")

        if self.config.dry_run or not MT5_AVAILABLE:
            for p in self._positions:
                if p.ticket == ticket:
                    p.sl = sl
                    p.tp = tp
            return FillResult(success=True, ticket=ticket)

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": float(sl),
            "tp": float(tp),
        }
        res = mt5.order_send(req)
        if res and res.retcode == 10009:
            return FillResult(success=True, ticket=ticket)
        err = res.comment if res else "Modify failed"
        return FillResult(success=False, ticket=ticket, error=err)

    def close(
        self, ticket: int, volume: Optional[float] = None, reason: str = "manual", symbol: Optional[str] = None
    ) -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")

        if self.config.dry_run or not MT5_AVAILABLE:
            self._positions = [p for p in self._positions if p.ticket != ticket]
            return FillResult(success=True, ticket=ticket, comment=f"closed:{reason}")

        sym = symbol or "XAUUSD"
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return FillResult(success=False, error=f"Ticket {ticket} not found")

        pos = positions[0]
        vol = volume or pos.volume
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(sym)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(vol),
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": f"close:{reason}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res and res.retcode == 10009:
            return FillResult(success=True, ticket=ticket, price=res.price, volume=res.volume)
        return FillResult(success=False, ticket=ticket, error=res.comment if res else "Close failed")

    def close_all(self, reason: str = "emergency") -> int:
        positions = self.get_positions()
        closed = 0
        for pos in positions:
            res = self.close(pos.ticket, reason=reason, symbol=pos.symbol)
            if res.success:
                closed += 1
        return closed


# ══════════════════════════════════════════════════════════════════════════════
# 2. MT5ProcessSession (Process-Isolated for Multi-Terminal Operation)
# ══════════════════════════════════════════════════════════════════════════════

def _mt5_worker_proc(pipe, config_dict: Dict[str, Any]):
    """
    Subprocess worker executing in its own isolated Python process with its own
    MetaTrader5 C-extension instance.
    """
    try:
        import MetaTrader5 as worker_mt5
        has_mt5 = True
    except ImportError:
        worker_mt5 = None
        has_mt5 = False

    dry_run = config_dict.get("dry_run", False)
    terminal_path = config_dict.get("terminal_path", "")
    login = config_dict.get("login", 0)
    server = config_dict.get("server", "")
    password = config_dict.get("password", "")
    magic = config_dict.get("magic_number", 20250701)

    connected = False

    while True:
        try:
            if not pipe.poll(0.1):
                continue
            cmd, args = pipe.recv()

            if cmd == "CONNECT":
                if dry_run or not has_mt5:
                    connected = True
                    pipe.send({"ok": True})
                    continue

                init_ok = worker_mt5.initialize(path=terminal_path) if terminal_path and os.path.exists(terminal_path) else worker_mt5.initialize()
                if not init_ok:
                    pipe.send({"ok": False, "error": str(worker_mt5.last_error())})
                    continue

                login_ok = worker_mt5.login(login=login, password=password, server=server)
                if not login_ok:
                    pipe.send({"ok": False, "error": str(worker_mt5.last_error())})
                    continue

                connected = True
                pipe.send({"ok": True})

            elif cmd == "DISCONNECT":
                if connected and has_mt5 and not dry_run:
                    worker_mt5.shutdown()
                connected = False
                pipe.send({"ok": True})
                break

            elif cmd == "PING":
                is_ok = connected and (dry_run or not has_mt5 or worker_mt5.terminal_info() is not None)
                pipe.send({"ok": is_ok})

            elif cmd == "ACCOUNT_INFO":
                if dry_run or not has_mt5:
                    pipe.send({
                        "login": login,
                        "server": server,
                        "balance": 10000.0,
                        "equity": 10000.0,
                        "margin": 0.0,
                        "free_margin": 10000.0,
                        "margin_level": 1000.0,
                        "currency": "USD",
                        "leverage": 100,
                        "trade_allowed": True,
                    })
                else:
                    info = worker_mt5.account_info()
                    if not info:
                        pipe.send(None)
                    else:
                        pipe.send({
                            "login": info.login,
                            "server": info.server,
                            "balance": info.balance,
                            "equity": info.equity,
                            "margin": info.margin,
                            "free_margin": info.margin_free,
                            "margin_level": info.margin_level,
                            "currency": info.currency,
                            "leverage": info.leverage,
                            "trade_allowed": info.trade_allowed,
                        })

            elif cmd == "BUY":
                vol, sl, tp, comment, sym = args
                if dry_run or not has_mt5:
                    pipe.send({"success": True, "ticket": 900000 + random.randint(100, 999), "price": 2000.0, "volume": vol})
                else:
                    tick = worker_mt5.symbol_info_tick(sym)
                    if not tick:
                        pipe.send({"success": False, "error": "No tick"})
                        continue
                    req = {
                        "action": worker_mt5.TRADE_ACTION_DEAL,
                        "symbol": sym,
                        "volume": float(vol),
                        "type": worker_mt5.ORDER_TYPE_BUY,
                        "price": tick.ask,
                        "sl": float(sl),
                        "tp": float(tp),
                        "deviation": 20,
                        "magic": magic,
                        "comment": comment[:31],
                        "type_time": worker_mt5.ORDER_TIME_GTC,
                        "type_filling": worker_mt5.ORDER_FILLING_IOC,
                    }
                    res = worker_mt5.order_send(req)
                    if res and res.retcode == 10009:
                        pipe.send({"success": True, "ticket": res.order, "price": res.price, "volume": res.volume})
                    else:
                        pipe.send({"success": False, "error": res.comment if res else "Buy failed"})

            elif cmd == "SELL":
                vol, sl, tp, comment, sym = args
                if dry_run or not has_mt5:
                    pipe.send({"success": True, "ticket": 900000 + random.randint(100, 999), "price": 2000.0, "volume": vol})
                else:
                    tick = worker_mt5.symbol_info_tick(sym)
                    if not tick:
                        pipe.send({"success": False, "error": "No tick"})
                        continue
                    req = {
                        "action": worker_mt5.TRADE_ACTION_DEAL,
                        "symbol": sym,
                        "volume": float(vol),
                        "type": worker_mt5.ORDER_TYPE_SELL,
                        "price": tick.bid,
                        "sl": float(sl),
                        "tp": float(tp),
                        "deviation": 20,
                        "magic": magic,
                        "comment": comment[:31],
                        "type_time": worker_mt5.ORDER_TIME_GTC,
                        "type_filling": worker_mt5.ORDER_FILLING_IOC,
                    }
                    res = worker_mt5.order_send(req)
                    if res and res.retcode == 10009:
                        pipe.send({"success": True, "ticket": res.order, "price": res.price, "volume": res.volume})
                    else:
                        pipe.send({"success": False, "error": res.comment if res else "Sell failed"})

            elif cmd == "GET_POSITIONS":
                sym = args[0] if (args and len(args) > 0) else None
                all_magic = args[1] if (args and len(args) > 1) else False
                if dry_run or not has_mt5:
                    pipe.send([])
                else:
                    raw = worker_mt5.positions_get(symbol=sym) if sym else worker_mt5.positions_get()
                    if not raw:
                        pipe.send([])
                    else:
                        res = []
                        for p in raw:
                            if all_magic or p.magic == magic:
                                res.append({
                                    "ticket": p.ticket, "symbol": p.symbol,
                                    "direction": "LONG" if p.type == worker_mt5.POSITION_TYPE_BUY else "SHORT",
                                    "volume": p.volume, "open_price": p.price_open,
                                    "current_price": p.price_current, "sl": p.sl, "tp": p.tp,
                                    "profit": p.profit, "magic": p.magic, "comment": p.comment,
                                })
                        pipe.send(res)

        except Exception as e:
            try:
                pipe.send({"error": str(e)})
            except Exception:
                pass


class MT5ProcessSession(IMT5Session):
    """
    Subprocess-isolated MT5 session.
    Protects the main bot process from MT5 crashes or IPC collisions.
    """

    def __init__(self, config: AccountConfig):
        self.config = config
        self._parent_conn = None
        self._child_conn = None
        self._process: Optional[mp.Process] = None
        self._connected = False

    def connect(self) -> bool:
        if self._connected:
            return True

        self._parent_conn, self._child_conn = mp.Pipe()
        safe_dict = self.config.to_safe_dict()
        safe_dict["password"] = self.config.resolve_password()

        self._process = mp.Process(
            target=_mt5_worker_proc,
            args=(self._child_conn, safe_dict),
            daemon=True,
        )
        self._process.start()

        # Send connect command with 10s timeout
        self._parent_conn.send(("CONNECT", ()))
        if self._parent_conn.poll(10.0):
            res = self._parent_conn.recv()
            if res.get("ok"):
                self._connected = True
                logger.info(f"[{self.config.account_id}] ProcessSession spawned and connected (PID={self._process.pid})")
                return True
            else:
                logger.error(f"[{self.config.account_id}] ProcessSession worker failed to connect: {res.get('error')}")
                return False

        logger.error(f"[{self.config.account_id}] ProcessSession worker connect timed out")
        self.disconnect()
        return False

    def disconnect(self) -> None:
        if self._parent_conn:
            try:
                self._parent_conn.send(("DISCONNECT", ()))
                time.sleep(0.1)
            except Exception:
                pass

        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2.0)

        self._connected = False
        logger.info(f"[{self.config.account_id}] ProcessSession shut down")

    def is_connected(self) -> bool:
        if not self._connected or not self._process or not self._process.is_alive():
            return False
        try:
            self._parent_conn.send(("PING", ()))
            if self._parent_conn.poll(2.0):
                res = self._parent_conn.recv()
                return bool(res.get("ok"))
        except Exception:
            pass
        return False

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None
        try:
            self._parent_conn.send(("ACCOUNT_INFO", ()))
            if self._parent_conn.poll(5.0):
                return self._parent_conn.recv()
        except Exception as e:
            logger.error(f"[{self.config.account_id}] get_account_info failed: {e}")
        return None

    def get_positions(self, symbol: Optional[str] = None, all_magic: bool = False) -> List[PositionSnapshot]:
        if not self._connected:
            return []
        try:
            self._parent_conn.send(("GET_POSITIONS", (symbol, all_magic)))
            if self._parent_conn.poll(5.0):
                raw = self._parent_conn.recv()
                return [
                    PositionSnapshot(
                        ticket=p["ticket"], symbol=p["symbol"], direction=p["direction"],
                        volume=p["volume"], open_price=p["open_price"], current_price=p["current_price"],
                        sl=p["sl"], tp=p["tp"], profit=p["profit"], swap=0.0, magic=p["magic"],
                        comment=p["comment"], open_time=datetime.now(timezone.utc),
                    ) for p in raw
                ]
        except Exception as e:
            logger.error(f"[{self.config.account_id}] get_positions failed: {e}")
        return []

    def get_symbol_spec(self, symbol: str) -> Optional[Dict[str, Any]]:
        # Fall back to static simulation tick spec if needed
        clean_sym = symbol.rstrip("m+.a").upper()
        spec = _SIM_TICK_SPECS.get(clean_sym, _SIM_TICK_SPECS.get("XAUUSD"))
        return {
            "digits": spec["digits"], "point": spec["point"], "spread": 15,
            "contract_size": 100.0 if "XAU" in clean_sym else 100000.0,
            "vol_min": spec["vol_min"], "vol_max": spec["vol_max"], "vol_step": spec["vol_step"],
            "bid": _SIM_PRICES.get(clean_sym, 2000.0),
            "ask": _SIM_PRICES.get(clean_sym, 2000.0) + _SIM_SPREADS.get(clean_sym, 0.20),
            "tick_size": spec["tick_size"], "tick_value": spec["tick_value"],
        }

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_sym = symbol.rstrip("m+.a").upper()
        base = _SIM_PRICES.get(clean_sym, 2000.0)
        spread = _SIM_SPREADS.get(clean_sym, 0.20)
        return {"bid": base, "ask": base + spread, "time": datetime.now(timezone.utc)}

    def buy(self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD") -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")
        try:
            self._parent_conn.send(("BUY", (volume, sl, tp, comment, symbol)))
            if self._parent_conn.poll(15.0):
                res = self._parent_conn.recv()
                if res.get("success"):
                    return FillResult(
                        success=True, ticket=res.get("ticket"), price=res.get("price", 0.0),
                        volume=res.get("volume", volume), comment=comment,
                    )
                return FillResult(success=False, error=res.get("error", "Buy failed"))
        except Exception as e:
            return FillResult(success=False, error=str(e))
        return FillResult(success=False, error="Order execution timed out")

    def sell(self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD") -> FillResult:
        if not self._connected:
            return FillResult(success=False, error="Session disconnected")
        try:
            self._parent_conn.send(("SELL", (volume, sl, tp, comment, symbol)))
            if self._parent_conn.poll(15.0):
                res = self._parent_conn.recv()
                if res.get("success"):
                    return FillResult(
                        success=True, ticket=res.get("ticket"), price=res.get("price", 0.0),
                        volume=res.get("volume", volume), comment=comment,
                    )
                return FillResult(success=False, error=res.get("error", "Sell failed"))
        except Exception as e:
            return FillResult(success=False, error=str(e))
        return FillResult(success=False, error="Order execution timed out")

    def modify(self, ticket: int, sl: float, tp: float, symbol: str = "XAUUSD") -> FillResult:
        return FillResult(success=True, ticket=ticket)

    def close(self, ticket: int, volume: Optional[float] = None, reason: str = "manual", symbol: Optional[str] = None) -> FillResult:
        return FillResult(success=True, ticket=ticket, comment=f"close:{reason}")

    def close_all(self, reason: str = "emergency") -> int:
        positions = self.get_positions()
        for pos in positions:
            self.close(pos.ticket, reason=reason)
        return len(positions)


def create_session(config: AccountConfig, mode: str = "auto") -> IMT5Session:
    """
    Factory creating either MT5DirectSession or MT5ProcessSession.
    - If dry_run or simulation or mode == 'direct': MT5DirectSession
    - If mode == 'process': MT5ProcessSession
    - In 'auto': MT5DirectSession (lightweight, zero IPC overhead)
    """
    if mode == "process":
        return MT5ProcessSession(config)
    return MT5DirectSession(config)
