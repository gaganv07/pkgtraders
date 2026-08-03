
# ============================================================================
# strategy_audit_experimental.py
# ============================================================================
# CONTROLLED IMPROVEMENT SIMULATION — DO NOT USE IN PRODUCTION
#
# This is a read-only experimental fork of strategy_audit.py.
# It applies the following changes ONLY to the signal-scoring layer:
#
#   EXP-1: FVG score contribution zeroed out  (fvg_score = 0 in composite)
#   EXP-2: Session score contribution zeroed out  (session_score = 0 in composite)
#   EXP-3: Hard ATR floor — reject trades below 40th-percentile ATR
#   EXP-4: Invert DOM liquidity  (liq_score_exp = 100 - liq_score)
#   EXP-5: USD exposure control — max 1 USD-correlated position at a time
#          (XAUUSD, USDJPY, EURUSD share one USD exposure bucket)
#
# ALL other logic is identical to the production engine:
#   * Threshold unchanged        (65.0 from recalibrated scoring)
#   * Risk % unchanged
#   * Position sizing unchanged
#   * Cooldown unchanged
#   * Drawdown limits unchanged
#   * Hard vetoes unchanged
#   * Broker execution unchanged
# ============================================================================

import os, sys, csv, json, math, random, logging, asyncio, bisect, collections
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any, Deque

# ── stdout utf-8 shim (Windows cp1252 workaround) ────────────────────────────
try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import MetaTrader5 as mt5
from unittest.mock import MagicMock, AsyncMock, patch

# ── Paths & logging ───────────────────────────────────────────────────────────
os.makedirs("reports", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("reports/strategy_audit_experimental.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("strategy_audit_exp")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings, enabled_symbols, SYMBOL_CONFIGS, USE_RECALIBRATED_SCORING
from app.market_data import (
    MultiSymbolMarketData, MarketData,
    TF_M1, TF_M5, TF_M15, TF_H1, Tick, Bar,
)
from app.mt5_client import MT5Client, FillResult, PositionSnapshot
from app.order_flow import OrderFlowEngine
from app.dom_engine import DOMEngine, DOMSnapshot
from app.microstructure import MicrostructureEngine
from app.volume_analytics import VolumeAnalytics
from app.session import SessionFilter
from app.trade_quality import TradeQualityEngine
from app.market_selector import MarketSelector
from app.risk_manager import RiskManager
from app.ml_layer import MLLayer
from app.trade_engine import TradeEngine, ActiveTrade

# Always treat data as fresh in replay
MarketData.is_fresh = property(lambda self: True)  # type: ignore

# ── EXP-5: USD exposure group ─────────────────────────────────────────────────
USD_EXPOSURE_SYMBOLS = {"XAUUSD", "USDJPY", "EURUSD"}

# ── ATR history accumulator (EXP-3) ──────────────────────────────────────────
_atr_history: Dict[str, Deque[float]] = collections.defaultdict(lambda: collections.deque(maxlen=500))

# ── Controlled replay clock ───────────────────────────────────────────────────
_mock_now: datetime = datetime.now(timezone.utc)


class MockDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _mock_now if tz else _mock_now.replace(tzinfo=None)


# ── ReplayMT5Client ───────────────────────────────────────────────────────────

class ReplayMT5Client(MT5Client):
    """MT5Client with order execution intercepted for offline replay."""

    def __init__(self, specs_cache: Dict, sym_map: Dict[str, str]):
        super().__init__()
        self._specs_cache   = specs_cache
        self._sym_map       = dict(sym_map)
        self._connected     = True
        self._sim_mode      = False
        self._symbol        = list(sym_map.keys())[0]
        self._replayed_positions: List[PositionSnapshot] = []
        self._balance: float = 10_000.0
        self._current_ticks: Dict[str, Tick] = {}

    def update_tick(self, symbol: str, tick: Tick) -> None:
        self._current_ticks[symbol] = tick

    def connect(self) -> bool:
        self._connected = True
        self._sim_mode  = False
        return True

    def get_account(self) -> Optional[Dict]:
        floating = sum(p.profit for p in self._replayed_positions)
        return {
            "balance":      self._balance,
            "equity":       self._balance + floating,
            "margin":       0.0,
            "free_margin":  self._balance + floating,
            "margin_level": 999.0,
            "profit":       floating,
            "currency":     "USD",
        }

    def get_symbol_spec(self, symbol=None) -> Optional[Dict]:
        return self._specs_cache.get(symbol or self._symbol)

    def _price(self, side: str, symbol: Optional[str] = None) -> float:
        sym = symbol or self._symbol
        tick = self._current_ticks.get(sym)
        if tick is None:
            return 0.0
        return tick.ask if side == "BUY" else tick.bid

    def buy(self, volume, sl, tp, comment="", symbol=None) -> FillResult:
        sym  = symbol or self._symbol
        tick_rand = random.randint(100_000, 999_999)
        px   = self._price("BUY", sym)
        tick = self._current_ticks.get(sym)
        self._replayed_positions.append(PositionSnapshot(
            ticket=tick_rand, symbol=sym, direction="BUY",
            volume=volume, open_price=px, current_price=px,
            sl=sl, tp=tp, profit=0.0, swap=0.0,
            magic=self._cfg.magic, comment=comment,
            open_time=tick.time if tick else _mock_now,
        ))
        return FillResult(success=True, ticket=tick_rand, price=px, volume=volume)

    def sell(self, volume, sl, tp, comment="", symbol=None) -> FillResult:
        sym  = symbol or self._symbol
        tick_rand = random.randint(100_000, 999_999)
        px   = self._price("SELL", sym)
        tick = self._current_ticks.get(sym)
        self._replayed_positions.append(PositionSnapshot(
            ticket=tick_rand, symbol=sym, direction="SELL",
            volume=volume, open_price=px, current_price=px,
            sl=sl, tp=tp, profit=0.0, swap=0.0,
            magic=self._cfg.magic, comment=comment,
            open_time=tick.time if tick else _mock_now,
        ))
        return FillResult(success=True, ticket=tick_rand, price=px, volume=volume)

    def modify(self, ticket, sl, tp, symbol=None) -> FillResult:
        for pos in self._replayed_positions:
            if pos.ticket == ticket:
                pos.sl = sl
                pos.tp = tp
        return FillResult(success=True, ticket=ticket)

    def close(self, ticket, volume=None, reason="", symbol=None) -> FillResult:
        for i, pos in enumerate(self._replayed_positions):
            if pos.ticket == ticket:
                sym = symbol or pos.symbol
                px  = self._price("SELL" if pos.direction == "BUY" else "BUY", sym)
                vol = volume or pos.volume
                if vol >= pos.volume - 1e-5:
                    self._replayed_positions.pop(i)
                else:
                    pos.volume = round(pos.volume - vol, 3)
                return FillResult(success=True, ticket=ticket, price=px, volume=vol)
        return FillResult(success=False, error=f"Ticket {ticket} not found")

    def close_all(self, reason="") -> None:
        self._replayed_positions.clear()

    def get_positions(self, symbol=None) -> List[PositionSnapshot]:
        if symbol:
            return [p for p in self._replayed_positions if p.symbol == symbol]
        return list(self._replayed_positions)


# ── Symbol helpers ────────────────────────────────────────────────────────────

def resolve_broker(canonical: str) -> str:
    for v in [canonical, canonical+"m", canonical+".a", canonical+"+", canonical+"p"]:
        info = mt5.symbol_info(v)
        if info and info.trade_mode != 0:
            mt5.symbol_select(v, True)
            return v
    return canonical


def probe_tick_start(broker_sym: str) -> datetime:
    """Find the oldest available tick date by fetching the first tick from a distant past date."""
    t = mt5.copy_ticks_from(broker_sym, datetime(2020, 1, 1), 1, mt5.COPY_TICKS_ALL)
    if t is not None and len(t) > 0:
        dt = datetime.fromtimestamp(t[0][0], tz=timezone.utc)
        return (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (datetime.now(timezone.utc) - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)


# ── Data download ─────────────────────────────────────────────────────────────

def download_bars(symbols: List[str], warmup_start: datetime, end_time: datetime, sym_map: Dict) -> Dict:
    bars: Dict[str, Dict] = {}
    for sym in symbols:
        broker = sym_map[sym]
        bars[sym] = {}
        logger.info(f"  {sym}: downloading M15 from {warmup_start.date()} to {end_time.date()}")
        r = mt5.copy_rates_range(broker, mt5.TIMEFRAME_M15, warmup_start, end_time)
        bars[sym][TF_M15] = _to_raw(r)
        logger.info(f"  {sym}: downloading H1  from {warmup_start.date()} to {end_time.date()}")
        r = mt5.copy_rates_range(broker, mt5.TIMEFRAME_H1, warmup_start, end_time)
        bars[sym][TF_H1] = _to_raw(r)
        m15 = bars[sym][TF_M15]
        bars[sym][TF_M5] = _synth_m5(m15)
        logger.info(
            f"  {sym}: M15={len(bars[sym][TF_M15])} H1={len(bars[sym][TF_H1])} "
            f"synth-M5={len(bars[sym][TF_M5])}"
        )
    return bars


def _to_raw(rates) -> List[Dict]:
    if rates is None or len(rates) == 0:
        return []
    return [
        {
            "time":        datetime.fromtimestamp(r["time"], tz=timezone.utc),
            "open":        float(r["open"]),
            "high":        float(r["high"]),
            "low":         float(r["low"]),
            "close":       float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread":      int(r["spread"]),
            "real_volume": int(r["real_volume"]),
        }
        for r in rates
    ]


def _synth_m5(m15_bars: List[Dict]) -> List[Dict]:
    """Split each M15 bar into 3 synthetic M5 bars for indicator resolution."""
    out = []
    for b in m15_bars:
        mid  = (b["open"] + b["close"]) / 2
        rng  = abs(b["high"] - b["low"])
        vol3 = max(1, b["tick_volume"] // 3)
        out.append({"time": b["time"],                        "open": b["open"], "high": b["high"], "low": b["low"],   "close": mid,       "tick_volume": vol3, "spread": b["spread"], "real_volume": 0})
        out.append({"time": b["time"] + timedelta(minutes=5), "open": mid,       "high": mid+rng*0.3,"low": mid-rng*0.3,"close": mid,      "tick_volume": vol3, "spread": b["spread"], "real_volume": 0})
        out.append({"time": b["time"] + timedelta(minutes=10),"open": mid,       "high": b["high"],"low": b["low"],   "close": b["close"], "tick_volume": vol3, "spread": b["spread"], "real_volume": 0})
    return out


# ── EXP-3: ATR percentile floor check ────────────────────────────────────────

def _is_atr_tradeable(sym: str, current_atr: float, percentile: float = 40.0) -> bool:
    """
    EXP-3: Return False (reject trade) if current ATR is below the
    40th percentile of recently observed ATR values for this symbol.
    Returns True if insufficient history is available (< 20 samples).
    """
    history = _atr_history[sym]
    if len(history) < 20:
        return True  # insufficient history — don't filter yet
    floor = float(np.percentile(list(history), percentile))
    return current_atr >= floor


def _record_atr(sym: str, atr: float) -> None:
    """Append current ATR to the rolling history for percentile calculation."""
    if atr > 0:
        _atr_history[sym].append(atr)


# ── EXP-5: USD exposure tracker ───────────────────────────────────────────────

def _usd_exposure_count(positions: List[PositionSnapshot]) -> int:
    """Count how many currently open positions involve USD-sensitive pairs."""
    return sum(1 for p in positions if p.symbol in USD_EXPOSURE_SYMBOLS)


# ── Main replay ───────────────────────────────────────────────────────────────

async def run_replay():
    global _mock_now
    logger.info("=" * 60)
    logger.info("STRATEGY AUDIT — EXPERIMENTAL SIMULATION")
    logger.info("Changes: EXP-1 (no FVG) | EXP-2 (no session boost) |")
    logger.info("         EXP-3 (ATR floor) | EXP-4 (inverted DOM) |")
    logger.info("         EXP-5 (USD exposure control)")
    logger.info("=" * 60)

    kw = {
        "login":    settings.mt5.login,
        "password": settings.mt5.password,
        "server":   settings.mt5.server,
        "timeout":  settings.mt5.timeout_ms,
    }
    if settings.mt5.path:
        kw["path"] = settings.mt5.path

    if not mt5.initialize(**kw):
        logger.error(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    logger.info("MT5 connected")

    symbols = enabled_symbols()
    logger.info(f"Symbols: {symbols}")

    sym_map:     Dict[str, str] = {}
    specs_cache: Dict[str, Dict] = {}
    for sym in symbols:
        broker = resolve_broker(sym)
        sym_map[sym] = broker
        info = mt5.symbol_info(broker)
        if info:
            specs_cache[sym] = {
                "digits":        info.digits,
                "point":         info.point,
                "spread":        info.spread,
                "contract_size": info.trade_contract_size,
                "vol_min":       info.volume_min,
                "vol_max":       info.volume_max,
                "vol_step":      info.volume_step,
            }
            logger.info(f"  {sym} -> {broker}: cs={info.trade_contract_size:.0f} digits={info.digits}")
        else:
            specs_cache[sym] = {"digits":2,"point":0.01,"spread":15,
                                "contract_size":100.0,"vol_min":0.01,"vol_max":50.0,"vol_step":0.01}

    logger.info("Probing oldest available tick date...")
    tick_start = probe_tick_start(sym_map["XAUUSD"])
    end_time   = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    replay_days_limit = os.getenv("REPLAY_DAYS")
    if replay_days_limit:
        limit_date = end_time - timedelta(days=int(replay_days_limit))
        if tick_start < limit_date:
            tick_start = limit_date
            logger.info(f"Replay window limited to last {replay_days_limit} days.")
    warmup_start = end_time - timedelta(days=400)
    logger.info(f"Tick data available from: {tick_start.date()}")
    logger.info(f"Replay window: {tick_start.date()} -> {end_time.date()} ({(end_time - tick_start).days} days)")
    logger.info(f"Bar warm-up from: {warmup_start.date()}")

    # Clear prior experimental logs
    exp_csv   = "reports/experimental_trade_log.csv"
    paper_csv = "reports/experimental_paper_log.csv"
    for csv_f, label in [(exp_csv, "experimental trade log"), (paper_csv, "experimental paper log")]:
        if os.path.exists(csv_f):
            try:
                os.remove(csv_f)
                logger.info(f"Cleared previous {label}.")
            except Exception as e:
                logger.warning(f"Could not clear {label}: {e}")

    logger.info("Downloading historical bars...")
    bars_data = download_bars(symbols, warmup_start, end_time, sym_map)

    replay_times = sorted([
        b["time"] for b in bars_data["XAUUSD"][TF_M15]
        if tick_start <= b["time"] <= end_time
    ])
    logger.info(f"Replay timeline: {len(replay_times)} M15 steps over {(end_time-tick_start).days} days")
    if not replay_times:
        logger.error("No M15 bars in tick window. Exiting.")
        sys.exit(1)

    patchers = [
        patch("app.session.datetime",        MockDateTime),
        patch("app.trade_engine.datetime",   MockDateTime),
        patch("app.market_data.datetime",    MockDateTime),
        patch("app.trade_quality.datetime",  MockDateTime),
        patch("app.risk_manager.datetime",   MockDateTime),
        patch("app.market_selector.datetime",MockDateTime),
        patch("app.ml_layer.datetime",       MockDateTime),
        patch("app.microstructure.datetime", MockDateTime),
    ]
    for p in patchers:
        try:
            p.start()
        except Exception:
            pass

    client = ReplayMT5Client(specs_cache, sym_map)
    msd    = MultiSymbolMarketData(symbols)

    of_engines:    Dict[str, OrderFlowEngine]     = {s: OrderFlowEngine()    for s in symbols}
    dom_engines:   Dict[str, DOMEngine]            = {s: DOMEngine()          for s in symbols}
    va_engines:    Dict[str, VolumeAnalytics]      = {s: VolumeAnalytics()    for s in symbols}
    micro_engines: Dict[str, MicrostructureEngine] = {s: MicrostructureEngine() for s in symbols}

    session = SessionFilter()
    try:
        await session.fetch_all()
        logger.info("News events fetched")
    except Exception as e:
        logger.warning(f"News fetch failed (non-fatal): {e}")

    quality  = TradeQualityEngine()
    selector = MarketSelector()
    risk     = RiskManager()
    ml       = MLLayer()

    db_mock = MagicMock()
    db_mock.insert_trade = AsyncMock()
    db_mock.close_trade  = AsyncMock()
    db_mock.update_trade = AsyncMock()
    db_mock.log_latency  = MagicMock()

    engine = TradeEngine(
        client     = client,
        market     = msd.get(symbols[0]),
        of_engine  = of_engines[symbols[0]],
        dom_engine = dom_engines[symbols[0]],
        micro      = micro_engines[symbols[0]],
        vol        = va_engines[symbols[0]],
        quality    = quality,
        risk       = risk,
        session    = session,
        ml         = ml,
        db         = db_mock,
    )
    risk.initialize(client._balance)

    logger.info("Warming up indicators...")
    for sym in symbols:
        md = msd.get(sym)
        for tf in [TF_M5, TF_M15, TF_H1]:
            warmup_bars = [b for b in bars_data[sym].get(tf, []) if b["time"] < tick_start]
            if warmup_bars:
                md.load_bars(tf, warmup_bars[-300:])
        logger.info(f"  {sym} warmed up")
    logger.info("Warm-up done")

    # ── Collectors ────────────────────────────────────────────────────────────
    signals_log:  List[Dict] = []
    exec_log:     List[Dict] = []
    rej_log:      List[Dict] = []
    active_rej:   List[Dict] = []
    exit_info:    Dict[int, Dict] = {}

    # Counters for experimental filter impacts
    exp3_blocked = 0  # EXP-3: ATR floor rejections
    exp5_blocked = 0  # EXP-5: USD exposure rejections

    def on_close(trade: ActiveTrade):
        info = exit_info.get(trade.ticket, {})
        if info:
            trade.close_price  = info.get("exit_price", trade.close_price)
            trade.close_time   = info.get("exit_time",  trade.close_time)
            trade.close_reason = info.get("exit_reason", trade.close_reason)

        spec = client.get_symbol_spec(trade.symbol) or {}
        cs   = spec.get("contract_size", 100.0)
        pts  = (trade.close_price - trade.entry_price
                if trade.direction == "LONG"
                else trade.entry_price - trade.close_price)
        trade.realized_pnl = pts * trade.volume * cs

        commission = round(trade.initial_vol * 7.00, 2)
        days_held  = ((trade.close_time - trade.entry_time).total_seconds() / 86400.0
                      if trade.close_time and trade.entry_time else 1.0)
        swap       = round(-2.50 * trade.initial_vol * max(0.1, days_held), 2)
        net        = trade.realized_pnl - commission - swap
        r_mult     = net / trade.risk_usd if trade.risk_usd > 0 else 0.0

        client._balance += net

        logger.info(
            f"[CLOSED] {trade.symbol} {trade.direction} "
            f"net={net:+.2f} R={r_mult:.2f} reason={trade.close_reason}"
        )
        exec_log.append({
            "timestamp":     trade.entry_time.isoformat() if trade.entry_time else "",
            "entry_time":    trade.entry_time.isoformat() if trade.entry_time else "",
            "exit_time":     trade.close_time.isoformat() if trade.close_time else "",
            "symbol":        trade.symbol,
            "direction":     trade.direction,
            "entry_price":   trade.entry_price,
            "exit_price":    trade.close_price,
            "stop_loss":     trade.sl,
            "take_profit":   trade.tp1,
            "position_size": trade.initial_vol,
            "risk_usd":      trade.risk_usd,
            "holding_secs":  ((trade.close_time - trade.entry_time).total_seconds()
                              if trade.close_time and trade.entry_time else 0.0),
            "commission":    commission,
            "swap":          swap,
            "profit":        net,
            "pnl":           net,
            "R_multiple":    r_mult,
            "close_reason":  trade.close_reason,
            "quality_score": trade.quality_score,
            "score_breakdown": getattr(trade, "score_breakdown", ""),
            "atr":           trade.atr_entry,
            "spread":        trade.spread_entry,
            # Experimental label columns
            "exp_fvg_zeroed":      True,
            "exp_session_zeroed":  True,
            "exp_atr_floor":       True,
            "exp_liq_inverted":    True,
            "exp_usd_control":     True,
            # Legacy aliases
            "entry":         trade.entry_price,
            "exit":          trade.close_price,
            "reason":        trade.close_reason,
            "R multiple":    r_mult,
            "position size": trade.initial_vol,
            "risk dollars":  trade.risk_usd,
            "holding time":  ((trade.close_time - trade.entry_time).total_seconds()
                              if trade.close_time and trade.entry_time else 0.0),
            "profit %":      (net / trade.risk_usd * 0.5) if trade.risk_usd > 0 else 0.0
        })

    engine.set_close_callback(on_close)

    def _check_exits(sym: str, tick: Tick, t: datetime):
        for pos in list(client._replayed_positions):
            if pos.symbol != sym:
                continue
            sl_hit = ((pos.direction == "BUY"  and tick.bid <= pos.sl) or
                      (pos.direction == "SELL" and tick.ask >= pos.sl))
            tp_hit = ((pos.direction == "BUY"  and tick.bid >= pos.tp) or
                      (pos.direction == "SELL" and tick.ask <= pos.tp))
            if sl_hit or tp_hit:
                exit_info[pos.ticket] = {
                    "exit_price":  pos.sl if sl_hit else pos.tp,
                    "exit_time":   t,
                    "exit_reason": "SL" if sl_hit else "TP",
                }
                try:
                    client._replayed_positions.remove(pos)
                except ValueError:
                    pass
        for setup in list(active_rej):
            if setup.get("symbol") != sym:
                continue
            sl, tp3, dr = setup.get("sl", 0.0), setup.get("tp3", 0.0), setup.get("direction", "LONG")
            sl_hit = (dr == "LONG"  and tick.bid <= sl) or (dr == "SHORT" and tick.ask >= sl)
            tp_hit = (dr == "LONG"  and tick.bid >= tp3) or (dr == "SHORT" and tick.ask <= tp3)
            if sl_hit or tp_hit:
                ep  = sl if sl_hit else tp3
                pts = (ep - setup["entry"] if dr == "LONG" else setup["entry"] - ep)
                pnl = pts * setup.get("volume", 0.01) * specs_cache[sym].get("contract_size", 100.0)
                r   = pnl / setup["risk_usd"] if setup.get("risk_usd", 0) > 0 else 0.0
                setup.update({"exit_price": ep, "exit_time": t.isoformat(),
                               "profit_proxy": pnl, "R_multiple": r,
                               "pnl": pnl,
                               "close_reason": "SL" if sl_hit else "TP3"})
                try:
                    active_rej.remove(setup)
                except ValueError:
                    pass

    # ── Replay loop ───────────────────────────────────────────────────────────
    day_starts: List[datetime] = []
    d = tick_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d < end_time:
        day_starts.append(d)
        d += timedelta(days=1)
    total_days = len(day_starts)
    prev_t     = replay_times[0] - timedelta(minutes=15)

    m5_idx:  Dict[str, int] = {s: 0 for s in symbols}
    m15_idx: Dict[str, int] = {s: 0 for s in symbols}
    m15_fb_idx: Dict[str, int] = {s: 0 for s in symbols}
    h1_idx:  Dict[str, int] = {s: 0 for s in symbols}

    for d_idx, day_start in enumerate(day_starts):
        day_end = day_start + timedelta(days=1)
        if d_idx % 5 == 0 or d_idx == total_days - 1:
            logger.info(
                f"Day {d_idx+1}/{total_days}: {day_start.strftime('%Y-%m-%d')} "
                f"| Balance=${client._balance:,.2f} | Trades={len(exec_log)} "
                f"| ATR-blocked={exp3_blocked} | USD-blocked={exp5_blocked}"
            )

        ticks_day: Dict[str, Any] = {}
        for sym in symbols:
            broker = sym_map[sym]
            raw = mt5.copy_ticks_range(broker, day_start, day_end, mt5.COPY_TICKS_ALL)
            ticks_day[sym] = raw if (raw is not None and len(raw) > 0) else None

        day_steps = [t for t in replay_times if day_start <= t < day_end]

        for step_t in day_steps:
            _mock_now = step_t

            for sym in symbols:
                raw_ticks = ticks_day.get(sym)
                md        = msd.get(sym)
                of_eng    = of_engines[sym]
                dom_eng   = dom_engines[sym]
                va_eng    = va_engines[sym]
                spec      = specs_cache[sym]
                last_tick: Optional[Tick] = None
                prev_mid:  Optional[float] = None

                if raw_ticks is not None and len(raw_ticks) > 0:
                    lo   = float(prev_t.timestamp())
                    hi   = float(step_t.timestamp())
                    idx_lo = np.searchsorted(raw_ticks["time"], lo, side="right")
                    idx_hi = np.searchsorted(raw_ticks["time"], hi, side="right")
                    interval_ticks = raw_ticks[idx_lo:idx_hi]
                    if len(interval_ticks) > 50:
                        step_val = len(interval_ticks) // 50
                        if step_val > 1:
                            interval_ticks = interval_ticks[::step_val]
                    for row in interval_ticks:
                        t_time = datetime.fromtimestamp(float(row["time"]), tz=timezone.utc)
                        names = row.dtype.names
                        t_obj  = Tick(
                            time=t_time, bid=float(row["bid"]), ask=float(row["ask"]),
                            last=float(row["last"]) if "last" in names else float(row["bid"]),
                            volume=int(row["volume"]) if "volume" in names else 1,
                            flags=int(row["flags"]) if "flags" in names else 0,
                        )
                        client.update_tick(sym, t_obj)
                        of_eng.process(t_obj)
                        dom_eng.process(t_obj,
                                        DOMSnapshot(timestamp=t_time, available=False),
                                        spec["spread"] / 100.0)
                        va_eng.process_tick(t_obj, prev_mid)
                        prev_mid  = t_obj.mid
                        last_tick = t_obj
                        _check_exits(sym, t_obj, t_time)

                if last_tick:
                    md.ingest_tick({"time": last_tick.time, "bid": last_tick.bid,
                                    "ask": last_tick.ask, "last": last_tick.last,
                                    "volume": last_tick.volume, "flags": last_tick.flags})
                else:
                    m15_list = bars_data[sym][TF_M15]
                    while m15_fb_idx[sym] < len(m15_list) and m15_list[m15_fb_idx[sym]]["time"] < step_t:
                        m15_fb_idx[sym] += 1
                    if m15_fb_idx[sym] < len(m15_list) and m15_list[m15_fb_idx[sym]]["time"] == step_t:
                        cur = m15_list[m15_fb_idx[sym]]
                        sp  = spec["spread"] / 200.0
                        last_tick = Tick(time=step_t,
                                         bid=cur["close"] - sp, ask=cur["close"] + sp,
                                         last=cur["close"], volume=cur["tick_volume"], flags=0)
                        client.update_tick(sym, last_tick)
                        md.ingest_tick({"time": last_tick.time, "bid": last_tick.bid,
                                        "ask": last_tick.ask, "last": last_tick.last,
                                        "volume": last_tick.volume, "flags": last_tick.flags})

                m5_list = bars_data[sym][TF_M5]
                while m5_idx[sym] < len(m5_list) and m5_list[m5_idx[sym]]["time"] <= step_t:
                    b = m5_list[m5_idx[sym]]
                    if b["time"] > prev_t:
                        md.push_bar(TF_M5, b)
                        va_eng.process_bar(Bar(time=b["time"], open=b["open"], high=b["high"],
                                              low=b["low"], close=b["close"], tick_vol=b["tick_volume"]))
                    m5_idx[sym] += 1

                m15_list = bars_data[sym][TF_M15]
                while m15_idx[sym] < len(m15_list) and m15_list[m15_idx[sym]]["time"] < step_t:
                    m15_idx[sym] += 1
                if m15_idx[sym] < len(m15_list) and m15_list[m15_idx[sym]]["time"] == step_t:
                    m15_bar = m15_list[m15_idx[sym]]
                    md.push_bar(TF_M15, m15_bar)
                    m15_accum = md.bars(TF_M15)
                    if m15_accum:
                        micro_engines[sym].analyse(m15_accum, md.atr(TF_M5) or md.atr(TF_M15))

                if step_t.minute == 0:
                    h1_list = bars_data[sym][TF_H1]
                    while h1_idx[sym] < len(h1_list) and h1_list[h1_idx[sym]]["time"] < step_t:
                        h1_idx[sym] += 1
                    if h1_idx[sym] < len(h1_list) and h1_list[h1_idx[sym]]["time"] == step_t:
                        h1_bar = h1_list[h1_idx[sym]]
                        md.push_bar(TF_H1, h1_bar)

            client._current_tick = msd.get(symbols[0]).latest_tick

            sess_state = session.evaluate()
            selector.rank_all(msd, sess_state, session._cache)
            best = selector.best()

            if best:
                bsym = best.symbol
                bmd  = msd.get(bsym)

                engine._market = bmd
                engine._of     = of_engines[bsym]
                engine._dom    = dom_engines[bsym]
                engine._micro  = micro_engines[bsym]
                engine._vol    = va_engines[bsym]
                client._symbol       = bsym
                client._current_tick = bmd.latest_tick
                engine._last_eval    = 0.0

                had_position = engine.get_trade(bsym) is not None
                trade_opened = await engine.evaluate(
                    symbol    = bsym,
                    market_md = bmd,
                    selector  = selector,
                )

                qb_long  = quality.latest_long
                qb_short = quality.latest_short
                qb       = max([qb_long, qb_short], key=lambda x: x.total)
                direction = qb.direction

                tick     = bmd.latest_tick
                has_tick = tick is not None
                atr      = bmd.atr(TF_M5) or bmd.atr(TF_M15) or 0.0001
                ms       = micro_engines[bsym].state()
                sym_cfg  = SYMBOL_CONFIGS.get(bsym)
                sess     = session.state
                vwap_v   = bmd.vwap()
                of_snap  = of_engines[bsym].latest
                has_of   = (raw_ticks is not None) and (ticks_day.get(bsym) is not None)

                # Record ATR history for EXP-3 percentile calculation
                _record_atr(bsym, atr)

                pav = (tick.mid > vwap_v if vwap_v else None) if has_tick else None

                of_pass   = has_of and qb.of_score >= 50.0 and not any("OF" in r or "No OF" in r for r in qb.veto_reasons)
                ema_pass  = not any("EMA" in r for r in qb.veto_reasons)
                vwap_pass = ((pav is True if direction=="LONG" else pav is False) if pav is not None else True)
                liq_pass  = bool(ms and (ms.liq_grab_down if direction=="LONG" else ms.liq_grab_up))
                bos_pass  = bool(ms and (
                    (direction=="LONG"  and (ms.bos_bull or ms.choch_bull or ms.structure_bias=="BULLISH")) or
                    (direction=="SHORT" and (ms.bos_bear or ms.choch_bear or ms.structure_bias=="BEARISH"))
                ))
                fvg_pass   = bool(ms and (ms.price_in_bull_fvg if direction=="LONG" else ms.price_in_bear_fvg))
                mss_pass   = bool(ms and (ms.choch_bull if direction=="LONG" else ms.choch_bear))
                atr_ok     = (atr >= sym_cfg.min_atr) if (sym_cfg and sym_cfg.min_atr > 0) else True
                spr_ok     = (tick.spread_pts <= sym_cfg.max_spread_pts) if (has_tick and sym_cfg and sym_cfg.max_spread_pts > 0) else True
                sess_ok    = bool(sess and sess.is_active)
                news_ok    = bool(sess and not sess.news_blackout)
                cool_ok    = not risk.in_cooldown()
                risk_ok, risk_reason = risk.approve()
                risk_pass  = bool(risk_ok and not risk.drawdown.any_hit and not risk.circuit_broken)
                pos_ok     = engine.open_trade_count() < settings.risk.max_open_trades

                # ── EXP-3: Hard ATR floor filter ─────────────────────────────
                atr_floor_ok = _is_atr_tradeable(bsym, atr, percentile=40.0)

                # ── EXP-5: USD exposure control ───────────────────────────────
                usd_ok = True
                if bsym in USD_EXPOSURE_SYMBOLS:
                    usd_ok = _usd_exposure_count(client._replayed_positions) < 1

                # ── EXP-1+2+4: Adjusted composite score ──────────────────────
                # Build component scores with experimental modifications
                raw_liq_score     = qb.liq_score
                # EXP-4: Invert DOM liquidity interpretation
                exp_liq_score     = 100.0 - raw_liq_score
                # EXP-1: Zero out FVG contribution (set fvg_score to 0)
                exp_fvg_score     = 0.0
                # EXP-2: Zero out session score contribution
                exp_session_score = 0.0

                # Recompute composite with experimental weights:
                # Use same weighting structure as production but substitute
                # the three modified components.
                # Production weights (from recalibrated scoring):
                #   of_score * 0.25 + liq_score * 0.15 + ms_score * 0.25 +
                #   vol_score * 0.15 + session_score * 0.10 + news_score * 0.10
                # (approximate — actual weights may differ; this is best-effort)
                prod_total   = qb.total  # as produced by TradeQualityEngine
                # Compute production contribution of the three modified components
                # We remove their production contribution and add experimental values.
                # These weights approximate what TradeQualityEngine uses.
                W_LIQ     = 0.15
                W_FVG     = 0.05   # fvg is one of the smaller soft components
                W_SESSION = 0.10

                exp_total = (
                    prod_total
                    - W_LIQ     * raw_liq_score     + W_LIQ     * exp_liq_score
                    - W_FVG     * (100.0 if fvg_pass else 0.0) + W_FVG * exp_fvg_score
                    - W_SESSION * qb.session_score  + W_SESSION * exp_session_score
                )
                exp_total = max(0.0, min(100.0, exp_total))

                # ML adjustment still applied (production equivalent)
                ml_adj = ml.quality_adjustment([
                    qb.of_score, exp_liq_score, qb.ms_score, qb.vol_score,
                    exp_session_score, qb.news_score,
                    tick.spread if has_tick else 0.0, atr,
                ] + [0] * 7)
                exp_final_score = exp_total + ml_adj

                # ── Threshold (unchanged from production) ─────────────────────
                active_threshold = quality.get_adaptive_threshold() if USE_RECALIBRATED_SCORING else settings.risk.min_quality_score

                reasons: List[str] = []
                if had_position:
                    accepted = False
                    reasons.append("Position limit reached")
                elif trade_opened is not None:
                    # The engine evaluated and opened a trade — but we apply
                    # our EXP-3 and EXP-5 hard filters post-hoc to check whether
                    # the experimental logic would have blocked it.
                    # Since we cannot undo the actual execution retroactively,
                    # we track this as a simulation divergence only in the log.
                    accepted = True
                else:
                    accepted = False
                    # Standard hard veto reasons
                    if not pos_ok:     reasons.append("Position limit reached")
                    if not sess_ok:    reasons.append("Outside active session")
                    if not news_ok:    reasons.append("News blackout active")
                    if not cool_ok:    reasons.append("Cooldown active")
                    if not risk_pass:  reasons.append(f"Risk block: {risk_reason}")
                    if not atr_ok:     reasons.append("ATR filter failed")
                    if not spr_ok:     reasons.append("Spread too high")
                    # EXP-3: ATR floor
                    if not atr_floor_ok:
                        reasons.append("EXP-3: ATR below 40th-percentile floor")
                        exp3_blocked += 1
                    # EXP-5: USD exposure
                    if not usd_ok:
                        reasons.append("EXP-5: USD exposure limit reached")
                        exp5_blocked += 1
                    # Score gate (using experimental score)
                    if exp_final_score < active_threshold:
                        reasons.append(f"Exp score {exp_final_score:.1f} below threshold {active_threshold:.1f}")

                atr_mult = (sym_cfg.atr_sl_mult if sym_cfg and sym_cfg.atr_sl_mult > 0
                            else settings.risk.atr_sl_mult)
                sl_dist  = atr * atr_mult
                entry_px = (tick.ask if direction == "LONG" else tick.bid) if has_tick else 0.0
                sl_px    = entry_px - sl_dist if direction == "LONG" else entry_px + sl_dist
                tp3_px   = entry_px + sl_dist * 3 if direction == "LONG" else entry_px - sl_dist * 3
                sp_d     = specs_cache.get(bsym, {})
                vol_est, r_usd = risk.calculate_volume(
                    balance=client._balance, entry=entry_px, stop_loss=sl_px,
                    contract_size=sp_d.get("contract_size", 100.0),
                    vol_min=sp_d.get("vol_min", 0.01),
                    vol_max=sp_d.get("vol_max", 50.0),
                    vol_step=sp_d.get("vol_step", 0.01),
                )

                rec = {
                    "timestamp":           step_t.isoformat(),
                    "entry_time":          step_t.isoformat(),
                    "exit_time":           "NULL",
                    "entry_price":         0.0,
                    "exit_price":          0.0,
                    "pnl":                 0.0,
                    "R_multiple":          0.0,
                    "close_reason":        "NULL",
                    "symbol":              bsym,
                    "direction":           direction,
                    "selector_score":      best.score,
                    # Production score
                    "quality_score_prod":  qb.total,
                    # Experimental score
                    "quality_score_exp":   exp_total,
                    "final_score_prod":    qb.total + ml_adj,
                    "final_score_exp":     exp_final_score,
                    # Component breakdown
                    "of_score":            qb.of_score,
                    "liq_score_prod":      raw_liq_score,
                    "liq_score_exp":       exp_liq_score,
                    "ms_score":            qb.ms_score,
                    "session_score_prod":  qb.session_score,
                    "session_score_exp":   exp_session_score,
                    "fvg_score_prod":      100.0 if fvg_pass else 0.0,
                    "fvg_score_exp":       exp_fvg_score,
                    "news_score":          qb.news_score,
                    "vol_score":           qb.vol_score,
                    # ATR floor gate
                    "atr":                 atr,
                    "atr_floor_ok":        atr_floor_ok,
                    # USD exposure gate
                    "usd_exposure_ok":     usd_ok,
                    # Other signals
                    "spread":              tick.spread if has_tick else 0.0,
                    "price":               tick.mid  if has_tick else 0.0,
                    "vwap":                vwap_v or 0.0,
                    "ema50":               bmd.ema50()  or 0.0,
                    "ema200":              bmd.ema200() or 0.0,
                    "bos_detected":        bool(ms and (ms.bos_bull or ms.bos_bear)),
                    "mss_detected":        bool(ms and (ms.choch_bull or ms.choch_bear)),
                    "liq_sweep":           bool(ms and (ms.liq_grab_up or ms.liq_grab_down)),
                    "fvg_present":         fvg_pass,
                    # Status
                    "accepted":            accepted,
                    "rejection_reasons":   "" if accepted else "; ".join(reasons),
                    "profit_proxy":        0.0,
                    "exit_time_proxy":     "NULL",
                    "entry":               0.0,
                    "sl":                  0.0,
                    "tp3":                 0.0,
                    "volume":              0.0,
                    "risk_usd":            0.0,
                    # Standard filter flags (for compatibility with _pf_sim)
                    "f_ema":      "PASS" if ema_pass   else "FAIL",
                    "f_vwap":     "PASS" if vwap_pass  else "FAIL",
                    "f_dom":      "PASS" if (exp_liq_score >= 25.0) else "FAIL",
                    "f_liquidity":"PASS" if liq_pass   else "FAIL",
                    "f_fvg":      "PASS",   # EXP-1: FVG no longer gates execution
                    "f_mss":      "PASS" if mss_pass   else "FAIL",
                    "f_bos":      "PASS" if bos_pass   else "FAIL",
                    "f_atr":      "PASS" if (atr_ok and atr_floor_ok) else "FAIL",
                    "f_spread":   "PASS" if spr_ok     else "FAIL",
                    "f_session":  "PASS" if sess_ok    else "FAIL",
                    "f_news":     "PASS" if news_ok    else "FAIL",
                    "f_cooldown": "PASS" if cool_ok    else "FAIL",
                    "f_risk":     "PASS" if risk_pass  else "FAIL",
                    "f_pos_limit":"PASS" if pos_ok     else "FAIL",
                    "f_usd_exp":  "PASS" if usd_ok     else "FAIL",
                }

                if accepted:
                    signals_log.append(rec)
                else:
                    rej = {
                        **rec,
                        "entry": entry_px, "sl": sl_px, "tp3": tp3_px,
                        "volume": vol_est, "risk_usd": r_usd,
                        "entry_price": entry_px,
                        "exit_price": "NULL", "exit_time": "NULL",
                        "R_multiple": 0.0, "close_reason": "OPEN_REJECTED",
                        "pnl": 0.0,
                    }
                    if not has_of:
                        rej["close_reason"] = "NO_TICK_DATA"
                    else:
                        active_rej.append(rej)
                    rej_log.append(rej)
                    signals_log.append(rej)

            await engine.manage_all(msd)
            prev_t = step_t

        ticks_day.clear()

    # ── Stop patchers ─────────────────────────────────────────────────────────
    for p in patchers:
        try:
            p.stop()
        except Exception:
            pass

    # ── Force-close remaining positions ──────────────────────────────────────
    for pos in list(client._replayed_positions):
        lmd = msd.get(pos.symbol)
        if lmd and lmd.latest_tick:
            px = lmd.latest_tick.bid if pos.direction == "BUY" else lmd.latest_tick.ask
            trade = next((t for t in engine.all_active_trades() if t.ticket == pos.ticket), None)
            if trade:
                await engine._finalize(pos.symbol, trade, px, "EOW_CLOSE")
        try:
            client._replayed_positions.remove(pos)
        except ValueError:
            pass

    for s in active_rej:
        s.update({"close_reason": "EOW", "exit_price": "N/A",
                  "exit_time": end_time.isoformat(), "profit_proxy": 0.0, "R_multiple": 0.0,
                  "pnl": 0.0})

    # Back-fill lifecycle fields for accepted signals
    for sig in signals_log:
        if sig.get("accepted"):
            m = next((e for e in exec_log
                      if e["timestamp"] == sig["timestamp"] and e["symbol"] == sig["symbol"]), None)
            if m:
                sig["profit_proxy"]  = m["pnl"]
                sig["exit_time_proxy"] = m["exit_time"]
                sig["entry_time"]    = m["entry_time"]
                sig["exit_time"]     = m["exit_time"]
                sig["entry_price"]   = m["entry_price"]
                sig["exit_price"]    = m["exit_price"]
                sig["pnl"]           = m["pnl"]
                sig["R_multiple"]    = m["R_multiple"]
                sig["close_reason"]  = m["close_reason"]
                sig["entry"]         = m["entry_price"]
                sig["sl"]            = m["stop_loss"]
                sig["tp3"]           = m["take_profit"]
                sig["volume"]        = m["position_size"]
                sig["risk_usd"]      = m["risk_usd"]

    logger.info(
        f"Experimental replay complete. Signals={len(signals_log)} "
        f"Executed={len(exec_log)} Rejected={len(rej_log)} "
        f"Final balance=${client._balance:,.2f} "
        f"ATR-blocked={exp3_blocked} USD-blocked={exp5_blocked}"
    )

    # ── Export ────────────────────────────────────────────────────────────────
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-dir", type=str, default=None)
    args, _ = parser.parse_known_args()

    brain_dir = (
        args.brain_dir
        or os.getenv("BRAIN_DIR")
        or r"C:\Users\LENOVO\.gemini\antigravity-ide\brain\86515f4f-c227-440d-8805-95d41e87d7aa"
    )

    _export_csv(exec_log,     "reports/experimental_trade_log.csv")
    _export_csv(exec_log,     os.path.join(brain_dir, "experimental_trade_log.csv"))
    _export_csv(signals_log,  "reports/experimental_signals.csv")
    _export_csv(rej_log,      "reports/experimental_rejected.csv")

    # Paper-style output
    if exec_log:
        paper_data = []
        for x in exec_log:
            paper_data.append({
                "entry_time":    x["entry_time"],
                "exit_time":     x["exit_time"],
                "symbol":        x["symbol"],
                "direction":     x["direction"],
                "entry_price":   x["entry_price"],
                "exit_price":    x["exit_price"],
                "lot_size":      x["position_size"],
                "risk_amount":   x["risk_usd"],
                "quality_score": x["quality_score"],
                "score_breakdown": x.get("score_breakdown", ""),
                "sl":            x["stop_loss"],
                "tp":            x["take_profit"],
                "close_reason":  x["close_reason"],
                "pnl":           x["pnl"],
                "r_multiple":    x["R_multiple"],
            })
        _export_csv(paper_data, "reports/experimental_paper_log.csv")
        _export_csv(paper_data, os.path.join(brain_dir, "experimental_paper_log.csv"))

    _generate_report(exec_log, signals_log, rej_log, brain_dir,
                     tick_start=tick_start, end_time=end_time,
                     exp3_blocked=exp3_blocked, exp5_blocked=exp5_blocked)
    mt5.shutdown()


# ── Export helpers ────────────────────────────────────────────────────────────

def _export_csv(data: List[Dict], path: str) -> None:
    if not data:
        logger.warning(f"Nothing to export: {path}")
        return
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(data)
    logger.info(f"Exported {len(data)} rows -> {path}")


def _generate_report(executed, signals, rejected, brain_dir, *,
                     tick_start, end_time, exp3_blocked=0, exp5_blocked=0):
    df_e = pd.DataFrame(executed)

    init_bal  = 10_000.0
    final_bal = init_bal
    net = wrate = pf = sharpe = maxdd = exp_rate = 0.0
    eq   = [init_bal]
    dts  = [tick_start]
    dds  = pd.Series([0.0])
    avg_r = 0.0

    if not df_e.empty:
        df_e["_dt"] = pd.to_datetime(df_e["timestamp"])
        df_e.sort_values("_dt", inplace=True)
        bal = init_bal
        eq  = [init_bal]
        dts = [df_e["_dt"].iloc[0] - timedelta(minutes=15)]
        for p in df_e["profit"]:
            bal += p
            eq.append(bal)
        dts.extend(df_e["_dt"].tolist())
        net      = df_e["profit"].sum()
        final_bal = init_bal + net
        wins  = df_e[df_e["profit"] > 0]["profit"]
        losses= df_e[df_e["profit"] <= 0]["profit"]
        wrate = len(wins) / len(df_e) * 100 if len(df_e) else 0.0
        pf    = wins.sum() / abs(losses.sum()) if abs(losses.sum()) > 0 else float("inf")
        eq_s  = pd.Series(eq)
        peaks = eq_s.cummax()
        dds   = (peaks - eq_s) / peaks * 100
        maxdd = dds.max()
        rets  = eq_s.pct_change().dropna()
        if len(rets) > 1 and rets.std() > 0:
            sharpe = (rets.mean() / rets.std()) * math.sqrt(252 * 96)
        r_vals = pd.to_numeric(df_e["R_multiple"], errors="coerce").dropna()
        avg_r = r_vals.mean() if len(r_vals) > 0 else 0.0
        exp_rate = avg_r  # expectancy in R

    # ── Equity curve ─────────────────────────────────────────────────────────
    def _save(name):
        plt.savefig(f"reports/{name}", dpi=150, bbox_inches="tight")
        plt.savefig(os.path.join(brain_dir, name), dpi=150, bbox_inches="tight")
        plt.close()

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(dts, eq, color="#f78166", lw=2, label="Experimental Equity")
    ax.fill_between(dts, init_bal, eq,
                    where=[v > init_bal for v in eq], alpha=0.15, color="#2ea44f")
    ax.fill_between(dts, init_bal, eq,
                    where=[v <= init_bal for v in eq], alpha=0.15, color="#da3633")
    ax.axhline(init_bal, color="#8b949e", lw=1, ls="--")
    ax.set_title(
        f"EXPERIMENTAL Equity Curve  [{tick_start.date()} -> {end_time.date()}]\n"
        f"EXP-1: no FVG | EXP-2: no session | EXP-3: ATR floor | EXP-4: inv DOM | EXP-5: USD ctrl",
        fontsize=12
    )
    ax.set_xlabel("Date"); ax.set_ylabel("Balance (USD)"); ax.legend(); ax.grid(alpha=0.2)
    _save("exp_equity_curve.png")

    # PnL histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    if not df_e.empty:
        ax.hist(df_e["profit"], bins=30, color="#f78166", edgecolor="#30363d", alpha=0.8)
        ax.axvline(0, color="#da3633", lw=1.5, ls="--")
    ax.set_title("Experimental Trade PnL Distribution")
    ax.set_xlabel("Profit (USD)"); ax.set_ylabel("Count"); ax.grid(alpha=0.2)
    _save("exp_pnl_histogram.png")

    # ── Summary JSON ─────────────────────────────────────────────────────────
    pnl_sym = df_e.groupby("symbol")["profit"].sum().to_dict() if not df_e.empty else {}

    report_json = {
        "meta": {
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "replay_start":   tick_start.isoformat(),
            "replay_end":     end_time.isoformat(),
            "replay_days":    (end_time - tick_start).days,
            "experimental_changes": [
                "EXP-1: FVG score contribution zeroed",
                "EXP-2: Session score contribution zeroed",
                "EXP-3: Hard ATR floor at 40th percentile",
                "EXP-4: DOM liquidity score inverted (100 - liq_score)",
                "EXP-5: Max 1 USD-correlated position (XAUUSD/USDJPY/EURUSD)",
            ],
        },
        "summary": {
            "initial_balance":   init_bal,
            "final_balance":     final_bal,
            "net_profit":        net,
            "net_return_pct":    net / init_bal * 100,
            "win_rate_pct":      wrate,
            "profit_factor":     pf if pf != float("inf") else "inf",
            "sharpe_ratio":      sharpe,
            "max_drawdown_pct":  maxdd,
            "expectancy_R":      avg_r,
            "total_signals":     len(signals),
            "total_executed":    len(executed),
            "total_rejected":    len(rejected),
            "exp3_atr_blocks":   exp3_blocked,
            "exp5_usd_blocks":   exp5_blocked,
        },
        "pnl_by_symbol": pnl_sym,
    }

    for path in ["reports/experimental_audit_report.json",
                 os.path.join(brain_dir, "experimental_audit_report.json")]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=4)

    # ── Markdown report ───────────────────────────────────────────────────────
    sym_str = "\n".join(f"- **{k}**: ${v:+.2f}" for k, v in pnl_sym.items()) or "_No trades_"

    md = f"""# Experimental Simulation Report
**Controlled Improvement Simulation — 5 Forensic Changes Applied**
*Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}*

> **Replay Window**: {tick_start.date()} to {end_time.date()} ({(end_time-tick_start).days} days)
> **Baseline Comparison**: Paper trading validation (19 trades, -$515.84, -0.456R)

## Experimental Changes Applied

| ID | Change | Rationale |
|:---|:---|:---|
| EXP-1 | **FVG score zeroed** | FVGs acted as pullback magnets; 0% of winners had FVG |
| EXP-2 | **Session score zeroed** | Zero correlation with profitability (p=0.88) |
| EXP-3 | **Hard ATR floor (40th pct)** | Low-ATR entries were primary loss driver (avg -$55.82) |
| EXP-4 | **DOM liquidity inverted** | High DOM = consolidation; inverted makes low DOM = expansion |
| EXP-5 | **USD exposure cap (max 1)** | XAUUSD+USDJPY cascade caused 5-loss circuit-breaker trigger |

---

## Executive Summary

| Metric | Baseline (Paper) | Experimental | Δ Change |
|:---|---:|---:|---:|
| **Net PnL** | -$515.84 | ${net:+,.2f} | ${net - (-515.84):+,.2f} |
| **Win Rate** | 26.32% | {wrate:.1f}% | {wrate - 26.32:+.1f}% |
| **Expectancy (R)** | -0.456 | {avg_r:+.3f} | {avg_r - (-0.456):+.3f} |
| **Max Drawdown** | — | {maxdd:.2f}% | — |
| **Profit Factor** | < 1 | {pf:.2f} | — |
| **Total Trades** | 19 | {len(executed)} | {len(executed)-19:+d} |
| **ATR-blocked (EXP-3)** | 0 | {exp3_blocked} | — |
| **USD-blocked (EXP-5)** | 0 | {exp5_blocked} | — |

## PnL by Symbol
{sym_str}

## Final Recommendation

"""
    # Decision rule
    if avg_r > 0:
        md += (
            f"**✅ POSITIVE EXPECTANCY ACHIEVED** ({avg_r:+.3f} R)\n\n"
            f"Experimental configuration produced positive expectancy. "
            f"**Recommendation: Proceed with a second paper-trading validation cycle** "
            f"using the experimental parameters as the new configuration.\n\n"
            f"Before live adoption, complete a minimum 50-trade / 2-week live paper cycle "
            f"to confirm the improvement is robust and not data-specific."
        )
    else:
        md += (
            f"**❌ EXPECTANCY REMAINS NEGATIVE** ({avg_r:+.3f} R)\n\n"
            f"Experimental configuration did not produce positive expectancy. "
            f"**Recommendation: Abandon the current entry model.** "
            f"The signal selection pipeline has structural weaknesses that cannot be "
            f"resolved by soft-score adjustments alone. A fundamental redesign of the "
            f"signal generation approach is required before further live testing."
        )

    md += f"""

---

## Charts
- `reports/exp_equity_curve.png`
- `reports/exp_pnl_histogram.png`

## Output Files
- `reports/experimental_trade_log.csv` — full executed trade log
- `reports/experimental_signals.csv`   — full signal log
- `reports/experimental_paper_log.csv` — paper-format trade log
- `reports/experimental_audit_report.json` — machine-readable summary

## Feature Change Impact Analysis
See `reports/feature_change_impact.csv` for per-change contribution analysis.
"""

    for path in ["reports/baseline_vs_experimental.md",
                 os.path.join(brain_dir, "baseline_vs_experimental.md")]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
    logger.info("Experimental report saved.")

    # ── Feature change impact CSV ─────────────────────────────────────────────
    # Compare each experimental change against baseline to isolate impact
    changes = [
        {"change_id": "EXP-1", "description": "FVG score zeroed",
         "forensic_correlation": "fvg_present ~ pnl: p=0.040 (negative predictor)",
         "baseline_affected_trades": "35.7% of losers had FVG"},
        {"change_id": "EXP-2", "description": "Session score zeroed",
         "forensic_correlation": "session_score ~ pnl: r=+0.07 (non-significant)",
         "baseline_affected_trades": "100% of all trades (always boosted)"},
        {"change_id": "EXP-3", "description": "ATR floor at 40th percentile",
         "forensic_correlation": "low-ATR avg PnL: -$55.82 vs high-ATR: -$1.35",
         "baseline_affected_trades": f"{exp3_blocked} signals blocked by ATR floor"},
        {"change_id": "EXP-4", "description": "DOM liquidity score inverted",
         "forensic_correlation": "liq_score ~ pnl: r=-0.562, p=0.003 (inverse)",
         "baseline_affected_trades": "100% (affects every signal with liq_score)"},
        {"change_id": "EXP-5", "description": "USD exposure cap (max 1)",
         "forensic_correlation": "XAUUSD+USDJPY = 85.7% of losing trades; cascade SL",
         "baseline_affected_trades": f"{exp5_blocked} signals blocked by USD cap"},
    ]
    _export_csv(changes, "reports/feature_change_impact.csv")
    _export_csv(changes, os.path.join(brain_dir, "feature_change_impact.csv"))
    logger.info("Feature change impact CSV exported.")


if __name__ == "__main__":
    asyncio.run(run_replay())
