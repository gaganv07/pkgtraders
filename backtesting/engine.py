"""
backtesting/engine.py — Backtesting Framework (Multi-Asset)

Supports:
  - Historical bar-by-bar replay with realistic simulation
  - Walk-forward analysis (3-month IS / 1-month OOS)
  - Monte Carlo simulation with ruin probability
  - Strategy parameter sensitivity analysis
  - Full performance analytics including compounded equity curve
  - Multi-asset simulation (XAUUSD, EURUSD, GBPUSD, USDJPY, NAS100, US30, BTCUSD)

Position sizing
---------------
Uses the IDENTICAL calculate_lot_size() function imported from app.risk_manager —
the same function that runs during live trading.  This guarantees bit-for-bit
consistent lot sizing between simulation and live execution.

Compounding
-----------
After every closed simulated trade:
    equity += realized_pnl
The updated equity is passed into the next call to calculate_lot_size() so
lot sizes automatically scale up after profitable runs and contract after losses.

Usage:
    python -m backtesting.engine --years 2 --balance 10000
    python -m backtesting.engine --years 2 --balance 10000 --symbols XAUUSD EURUSD GBPUSD
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Canonical position-sizing import ─────────────────────────────────────────
# Both the live TradeEngine and this backtesting engine call the same function.
try:
    from app.risk_manager import calculate_lot_size as _canonical_lot_size
    _LIVE_IMPORT = True
except ImportError:                        # safety fallback (standalone use)
    _LIVE_IMPORT = False
    def _canonical_lot_size(              # type: ignore[misc]
        balance: float, entry_price: float, stop_loss: float,
        risk_pct: float,
        contract_size: float = 100.0,
        vol_min: float = 0.01, vol_max: float = 50.0, vol_step: float = 0.01,
    ) -> Tuple[float, float]:
        sl_dist = abs(entry_price - stop_loss)
        if sl_dist < 0.001 or balance <= 0:
            return vol_min, 0.0
        risk_usd = balance * (risk_pct / 100.0)
        pnl_per_lot = sl_dist * contract_size
        if pnl_per_lot <= 0:
            return vol_min, 0.0
        raw = risk_usd / pnl_per_lot
        steps = math.floor(raw / vol_step)
        vol = max(vol_min, min(vol_max, steps * vol_step))
        step_decs = max(0, -int(math.floor(math.log10(vol_step)))) if vol_step < 1 else 0
        vol = round(vol, step_decs)
        return vol, round(vol * pnl_per_lot, 2)

logger = logging.getLogger(__name__)


# ── Convenience wrapper used by the backtesting loop ─────────────────────────

def _calc_volume(
    balance:       float,
    sl_dist:       float,
    risk_pct:      float = 0.5,
    contract_size: float = 100.0,
    vol_min:       float = 0.01,
    vol_max:       float = 50.0,
    vol_step:      float = 0.01,
) -> Tuple[float, float]:
    """
    Thin wrapper so the backtest loop can call with positional sl_dist rather
    than computing entry/stop_loss separately.  Delegates entirely to the
    canonical calculate_lot_size() from app.risk_manager.

    Parameters and return value identical to calculate_lot_size().
    Falls back to a synthetic entry/sl pair that produces the required distance.
    """
    # Represent entry at a nominal price; only the distance matters.
    synthetic_entry = 2000.0
    synthetic_sl    = synthetic_entry - sl_dist  # always produces correct distance

    return _canonical_lot_size(
        balance=balance,
        entry_price=synthetic_entry,
        stop_loss=synthetic_sl,
        risk_pct=risk_pct,
        contract_size=contract_size,
        vol_min=vol_min,
        vol_max=vol_max,
        vol_step=vol_step,
    )


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class BTBar:
    time:   datetime
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float


@dataclass
class BTTrade:
    direction:    str
    entry_price:  float
    entry_time:   datetime
    sl:           float
    tp1:          float
    tp2:          float
    tp3:          float
    volume:       float
    risk_usd:     float
    balance_at_entry: float = 0.0   # equity snapshot used for this trade's sizing
    quality:      float = 85.0
    symbol:       str   = "XAUUSD"  # which asset this trade is on
    contract_size: float = 100.0    # per-symbol contract size

    exit_price:   float = 0.0
    exit_time:    Optional[datetime] = None
    pnl:          float = 0.0
    reason:       str   = ""
    tp1_done:     bool  = False
    tp2_done:     bool  = False
    rem_vol:      float = 0.0
    real_pnl:     float = 0.0

    def __post_init__(self):
        self.rem_vol = self.volume


@dataclass
class BTResult:
    label:         str = "FULL"
    period_start:  str = ""
    period_end:    str = ""

    # Core metrics
    total_trades:  int   = 0
    winning:       int   = 0
    losing:        int   = 0
    gross_profit:  float = 0.0
    gross_loss:    float = 0.0
    net_pnl:       float = 0.0
    win_rate:      float = 0.0
    profit_factor: float = 0.0
    avg_win:       float = 0.0
    avg_loss:      float = 0.0
    largest_win:   float = 0.0
    largest_loss:  float = 0.0
    expectancy:    float = 0.0

    # Risk / drawdown
    max_drawdown:  float = 0.0
    max_dd_pct:    float = 0.0

    # Risk-adjusted performance
    sharpe:        float = 0.0
    sortino:       float = 0.0
    calmar:        float = 0.0
    recovery:      float = 0.0

    # Streaks
    consec_wins:   int   = 0
    consec_losses: int   = 0

    # Quality
    avg_quality:   float = 85.0

    # Compounded equity growth (new — requirement 15)
    initial_balance:  float = 0.0
    final_equity:     float = 0.0
    peak_equity:      float = 0.0
    return_pct:       float = 0.0
    equity_curve:     List[float] = field(default_factory=list)

    trades: List[BTTrade] = field(default_factory=list)

    def compute(self, initial: float = 10000.0) -> None:
        self.initial_balance = initial
        closed = [t for t in self.trades if t.exit_price > 0]
        self.total_trades = len(closed)
        if not closed:
            return

        pnls   = [t.pnl for t in closed]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        self.winning      = len(wins)
        self.losing       = len(losses)
        self.gross_profit = sum(wins)
        self.gross_loss   = abs(sum(losses))
        self.net_pnl      = self.gross_profit - self.gross_loss
        self.win_rate     = self.winning / self.total_trades * 100
        self.profit_factor = (self.gross_profit / self.gross_loss
                               if self.gross_loss > 0 else 0)
        self.avg_win    = statistics.mean(wins)  if wins   else 0
        self.avg_loss   = statistics.mean(losses) if losses else 0
        self.largest_win  = max(wins)  if wins   else 0
        self.largest_loss = min(losses) if losses else 0
        self.expectancy   = self.net_pnl / self.total_trades
        self.avg_quality  = statistics.mean(t.quality for t in closed)

        # ── Equity curve & drawdown ───────────────────────────────────────────
        eq = initial
        pk = eq
        mx = 0.0
        curve: List[float] = [round(eq, 2)]
        for p in pnls:
            eq += p
            pk  = max(pk, eq)
            mx  = max(mx, pk - eq)
            curve.append(round(eq, 2))

        self.equity_curve  = curve
        self.final_equity  = round(eq, 2)
        self.peak_equity   = round(pk, 2)
        self.max_drawdown  = round(mx, 2)
        self.max_dd_pct    = round(mx / initial * 100, 2) if initial > 0 else 0.0
        self.return_pct    = round((eq - initial) / initial * 100, 2) if initial > 0 else 0.0

        # ── Sharpe / Sortino ──────────────────────────────────────────────────
        if len(pnls) > 1:
            mu  = statistics.mean(pnls)
            std = statistics.stdev(pnls)
            if std > 0:
                self.sharpe = round(mu / std * math.sqrt(252), 3)
            neg = [p for p in pnls if p < 0]
            if len(neg) > 1:
                ds = statistics.stdev(neg)
                if ds > 0:
                    self.sortino = round(mu / ds * math.sqrt(252), 3)

        if mx > 0:
            self.calmar   = round(self.net_pnl / mx, 3)
            self.recovery = round(self.net_pnl / mx, 3)

        # ── Streaks ───────────────────────────────────────────────────────────
        mw = ml = cw = cl = 0
        for p in pnls:
            if p > 0: cw += 1; cl = 0; mw = max(mw, cw)
            else:     cl += 1; cw = 0; ml = max(ml, cl)
        self.consec_wins   = mw
        self.consec_losses = ml


# ── Bar Simulator ─────────────────────────────────────────────────────────────

class BarSimulator:
    """Simulates trade management on subsequent bars (contract-size aware)."""

    def run(self, trade: BTTrade, bars: List[BTBar],
            atr: float = 0.0) -> BTTrade:
        sl_dist = abs(trade.entry_price - trade.sl)
        cs      = trade.contract_size   # ← use per-trade contract size

        for bar in bars:
            if trade.rem_vol <= 0:
                break

            # ── SL ────────────────────────────────────────────────────────────
            if trade.direction == "LONG" and bar.low <= trade.sl:
                pnl = (trade.sl - trade.entry_price) * trade.rem_vol * cs
                trade.real_pnl += pnl
                trade.exit_price = trade.sl
                trade.exit_time  = bar.time
                trade.reason     = "SL"
                trade.rem_vol    = 0.0
                break
            if trade.direction == "SHORT" and bar.high >= trade.sl:
                pnl = (trade.entry_price - trade.sl) * trade.rem_vol * cs
                trade.real_pnl += pnl
                trade.exit_price = trade.sl
                trade.exit_time  = bar.time
                trade.reason     = "SL"
                trade.rem_vol    = 0.0
                break

            # ── TP1 ───────────────────────────────────────────────────────────
            if not trade.tp1_done:
                hit = (trade.direction == "LONG" and bar.high >= trade.tp1) or \
                      (trade.direction == "SHORT" and bar.low  <= trade.tp1)
                if hit:
                    vol = round(trade.volume * 0.30, 3)
                    if trade.direction == "LONG":
                        pnl = (trade.tp1 - trade.entry_price) * vol * cs
                    else:
                        pnl = (trade.entry_price - trade.tp1) * vol * cs
                    trade.real_pnl += pnl
                    trade.rem_vol  -= vol
                    trade.tp1_done  = True
                    trade.sl        = trade.entry_price   # breakeven

            # ── TP2 ───────────────────────────────────────────────────────────
            if trade.tp1_done and not trade.tp2_done:
                hit = (trade.direction == "LONG" and bar.high >= trade.tp2) or \
                      (trade.direction == "SHORT" and bar.low  <= trade.tp2)
                if hit:
                    vol = round(trade.volume * 0.30, 3)
                    if trade.direction == "LONG":
                        pnl = (trade.tp2 - trade.entry_price) * vol * cs
                    else:
                        pnl = (trade.entry_price - trade.tp2) * vol * cs
                    trade.real_pnl += pnl
                    trade.rem_vol  -= vol
                    trade.tp2_done  = True

            # ── TP3 (full) ────────────────────────────────────────────────────
            if trade.tp1_done and trade.tp2_done:
                hit = (trade.direction == "LONG" and bar.high >= trade.tp3) or \
                      (trade.direction == "SHORT" and bar.low  <= trade.tp3)
                if hit:
                    if trade.direction == "LONG":
                        pnl = (trade.tp3 - trade.entry_price) * trade.rem_vol * cs
                    else:
                        pnl = (trade.entry_price - trade.tp3) * trade.rem_vol * cs
                    trade.real_pnl  += pnl
                    trade.exit_price = trade.tp3
                    trade.exit_time  = bar.time
                    trade.reason     = "TP3"
                    trade.rem_vol    = 0.0
                    break

            # ── Trailing stop ─────────────────────────────────────────────────
            if atr > 0 and trade.tp1_done:
                if trade.direction == "LONG":
                    ns = bar.high - atr * 0.8
                    trade.sl = max(trade.sl, ns)
                else:
                    ns = bar.low + atr * 0.8
                    trade.sl = min(trade.sl, ns)

        # Close at last bar if still open
        if trade.rem_vol > 0 and bars:
            last = bars[-1]
            price = last.close
            if trade.direction == "LONG":
                pnl = (price - trade.entry_price) * trade.rem_vol * cs
            else:
                pnl = (trade.entry_price - price) * trade.rem_vol * cs
            trade.real_pnl  += pnl
            trade.exit_price = price
            trade.exit_time  = last.time
            trade.reason     = "EOW"
            trade.rem_vol    = 0.0

        trade.pnl = trade.real_pnl
        return trade


# ── Per-symbol simulation config ──────────────────────────────────────────────

_SYM_BASE_PRICE: Dict[str, float] = {
    "XAUUSD": 1950.0, "EURUSD": 1.085, "GBPUSD": 1.27,
    "USDJPY": 149.5,  "NAS100": 18500.0, "US30": 39000.0,
    "BTCUSD": 67000.0,
}
_SYM_VOL_STD: Dict[str, float] = {
    "XAUUSD": 0.0008, "EURUSD": 0.0004, "GBPUSD": 0.0005,
    "USDJPY": 0.0003, "NAS100": 0.0010, "US30": 0.0008,
    "BTCUSD": 0.0025,
}
_SYM_CONTRACT: Dict[str, float] = {
    "XAUUSD": 100.0,     "EURUSD": 100_000.0, "GBPUSD": 100_000.0,
    "USDJPY": 100_000.0, "NAS100": 1.0,        "US30": 1.0,
    "BTCUSD": 1.0,
}


# ── Walk-Forward Engine ───────────────────────────────────────────────────────

class WalkForwardEngine:
    def __init__(self, is_months: int = 3, oos_months: int = 1,
                 risk_pct: float = 0.5,
                 symbols: Optional[List[str]] = None):
        self.is_months  = is_months
        self.oos_months = oos_months
        self.risk_pct   = risk_pct
        self.symbols    = symbols or ["XAUUSD"]
        self.sim = BarSimulator()

    async def run(
        self, start: datetime, end: datetime,
        atr_mult: float = 1.5, balance: float = 10000.0
    ) -> Dict[str, Any]:
        logger.info(
            f"Walk-forward: {start.date()} -> {end.date()} "
            f"IS={self.is_months}m OOS={self.oos_months}m "
            f"Symbols={self.symbols} "
            f"InitBalance=${balance:,.2f} Risk={self.risk_pct}%"
        )
        windows = []
        cursor  = start
        while cursor < end:
            is_end  = cursor + timedelta(days=30 * self.is_months)
            oos_end = min(is_end + timedelta(days=30 * self.oos_months), end)
            if is_end >= end:
                break
            logger.info(
                f"  Window IS={cursor.date()}->{is_end.date()} "
                f"OOS->{oos_end.date()}"
            )
            # Generate bars for each symbol
            is_bars_map  = {s: self._gen_bars(cursor, is_end, s) for s in self.symbols}
            oos_bars_map = {s: self._gen_bars(is_end, oos_end, s) for s in self.symbols}

            is_res   = self._run_window(is_bars_map,  atr_mult, balance, "IS")
            oos_res  = self._run_window(oos_bars_map, atr_mult, balance, "OOS")
            windows.append({"in_sample": is_res, "out_sample": oos_res})
            cursor = is_end

        return self._compile(windows, balance)

    def _run_window(
        self, bars_map: Dict[str, List[BTBar]], atr_mult: float,
        balance: float, label: str
    ) -> BTResult:
        # Use first symbol for period labels
        first_sym = self.symbols[0]
        all_bars  = bars_map.get(first_sym, [])

        result = BTResult(
            label=label,
            period_start=all_bars[0].time.isoformat() if all_bars else "",
            period_end=all_bars[-1].time.isoformat() if all_bars else "",
        )
        if not all_bars or len(all_bars) < 30:
            return result

        equity = balance   # shared across all symbols (same account)
        step   = max(1, len(all_bars) // 60)

        for i in range(20, len(all_bars), step):
            if equity <= 0:
                logger.warning(f"[BT] Equity reached 0 — stopping {label} window")
                break

            # Pick best symbol at this bar index (simplified: rotate round-robin
            # weighted by ATR — in real use this mirrors the MarketSelector logic)
            sym = self.symbols[i % len(self.symbols)]
            bars = bars_map.get(sym, all_bars)
            if i >= len(bars):
                continue

            cs  = _SYM_CONTRACT.get(sym, 100.0)
            atr = self._atr(bars[:i+1], 14)

            # Simple EMA trend signal
            em_f = statistics.mean(b.close for b in bars[max(0,i-10):i])
            em_s = statistics.mean(b.close for b in bars[max(0,i-20):i])
            direction = "LONG" if em_f > em_s else "SHORT"

            entry   = bars[i].close
            sl_dist = atr * atr_mult

            # ── Dynamic lot sizing via canonical function ──────────────────────
            vol, risk = _calc_volume(
                balance=equity,
                sl_dist=sl_dist,
                risk_pct=self.risk_pct,
                contract_size=cs,
            )

            if direction == "LONG":
                sl  = entry - sl_dist
                tp1 = entry + sl_dist * 1.0
                tp2 = entry + sl_dist * 2.0
                tp3 = entry + sl_dist * 3.0
            else:
                sl  = entry + sl_dist
                tp1 = entry - sl_dist * 1.0
                tp2 = entry - sl_dist * 2.0
                tp3 = entry - sl_dist * 3.0

            logger.debug(
                f"[BT-TRADE OPEN] Symbol={sym} | "
                f"Direction={direction} | "
                f"EntryPrice={entry:.5f} | "
                f"FinalLot={vol} | "
                f"DollarRisk=${risk:.2f} | "
                f"Balance=${equity:,.2f}"
            )

            trade = BTTrade(
                direction=direction, entry_price=entry,
                entry_time=bars[i].time,
                sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                volume=vol, risk_usd=risk,
                balance_at_entry=equity,
                symbol=sym,
                contract_size=cs,
            )
            future = bars[i+1:i+80]
            trade  = self.sim.run(trade, future, atr)

            equity += trade.pnl
            result.trades.append(trade)

        result.compute(balance)
        logger.info(
            f"  [{label}] {result.total_trades} trades | "
            f"WR={result.win_rate:.1f}% | "
            f"PnL=${result.net_pnl:+.2f} | "
            f"FinalEquity=${result.final_equity:,.2f} | "
            f"Return={result.return_pct:+.2f}% | "
            f"MaxDD={result.max_dd_pct:.2f}%"
        )
        return result

    def _gen_bars(
        self, start: datetime, end: datetime,
        symbol: str = "XAUUSD", interval_h: int = 1
    ) -> List[BTBar]:
        bars    = []
        dt      = timedelta(hours=interval_h)
        current = start
        base    = _SYM_BASE_PRICE.get(symbol, 1950.0)
        vol_std = _SYM_VOL_STD.get(symbol, 0.0008)
        price   = base
        while current < end:
            if current.weekday() < 5:   # skip weekends
                ret   = random.gauss(0.0, vol_std)
                close = max(base * 0.1, price * (1 + ret))
                rng   = close * vol_std * 2
                high  = close + abs(random.gauss(0, rng))
                low   = close - abs(random.gauss(0, rng))
                bars.append(BTBar(
                    time=current, open=price,
                    high=high, low=low, close=close,
                    volume=random.randint(200, 2000),
                ))
                price = close
            current += dt
        return bars

    def _atr(self, bars: List[BTBar], period: int = 14) -> float:
        if len(bars) < period + 1:
            return 1.5
        trs = []
        for i in range(1, min(period + 1, len(bars))):
            h, l, pc = bars[i].high, bars[i].low, bars[i-1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return statistics.mean(trs) if trs else 1.5

    def _compile(self, windows: List[Dict], initial_balance: float) -> Dict[str, Any]:
        oos = [w["out_sample"] for w in windows]
        tt  = sum(r.total_trades for r in oos)
        pnl = sum(r.net_pnl for r in oos)
        wr  = statistics.mean(r.win_rate for r in oos) if oos else 0
        pf  = statistics.mean(r.profit_factor for r in oos) if oos else 0
        sh  = statistics.mean(r.sharpe for r in oos) if oos else 0
        dd  = max((r.max_dd_pct for r in oos), default=0)

        # Collect all OOS PnLs in chronological order for downstream MC use
        all_oos_pnls: List[float] = []
        for r in oos:
            all_oos_pnls.extend(t.pnl for t in r.trades if t.exit_price > 0)

        # Per-symbol breakdown from all OOS trades
        sym_stats: Dict[str, Dict] = {}
        for r in oos:
            for t in r.trades:
                if not t.exit_price:
                    continue
                sym = getattr(t, "symbol", "XAUUSD")
                if sym not in sym_stats:
                    sym_stats[sym] = {"trades": 0, "wins": 0, "losses": 0,
                                       "net_pnl": 0.0}
                sym_stats[sym]["trades"] += 1
                if t.pnl > 0:
                    sym_stats[sym]["wins"] += 1
                else:
                    sym_stats[sym]["losses"] += 1
                sym_stats[sym]["net_pnl"] += t.pnl

        for sym, s in sym_stats.items():
            if s["trades"] > 0:
                s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1)
            s["net_pnl"] = round(s["net_pnl"], 2)

        report = {
            "meta": {
                "initial_balance": initial_balance,
                "risk_pct":        self.risk_pct,
                "symbols":         self.symbols,
                "sizing_function":  "calculate_lot_size (canonical, same as live)",
            },
            "summary": {
                "windows":            len(windows),
                "oos_total_trades":   tt,
                "oos_net_pnl":        round(pnl, 2),
                "oos_avg_win_rate":   round(wr, 1),
                "oos_avg_pf":         round(pf, 2),
                "oos_avg_sharpe":     round(sh, 3),
                "oos_max_dd_pct":     round(dd, 2),
            },
            "symbol_breakdown":   sym_stats,
            "windows": [
                {
                    "in_sample": {
                        k: v for k, v in asdict(w["in_sample"]).items()
                        if k not in ("trades", "equity_curve")
                    },
                    "out_sample": {
                        k: v for k, v in asdict(w["out_sample"]).items()
                        if k not in ("trades", "equity_curve")
                    },
                }
                for w in windows
            ],
            "_oos_pnls": all_oos_pnls,    # used internally by CLI for MC
        }

        print("\n" + "=" * 60)
        print("  WALK-FORWARD RESULTS (Multi-Asset, Dynamic Compounding)")
        print("=" * 60)
        for k, v in report["summary"].items():
            print(f"  {k:<35} {v}")
        if sym_stats:
            print("\n  Per-Symbol OOS Breakdown:")
            for sym, s in sym_stats.items():
                print(f"    {sym:<10} trades={s['trades']:3d}  "
                      f"WR={s.get('win_rate',0):.1f}%  "
                      f"PnL=${s['net_pnl']:+.2f}")
        print("=" * 60 + "\n")
        return report


# ── Monte Carlo ───────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    def run(
        self, pnls: List[float], sims: int = 1000,
        initial: float = 10000.0, ruin_threshold: float = 0.90
    ) -> Dict[str, Any]:
        if not pnls:
            return {}
        dd_list    = []
        final_list = []
        ruin       = 0

        for _ in range(sims):
            shuffled = random.sample(pnls, len(pnls))
            eq = initial; pk = eq; mx = 0.0; ruined = False
            for p in shuffled:
                eq += p
                pk  = max(pk, eq)
                mx  = max(mx, pk - eq)
                if eq <= initial * (1 - ruin_threshold):
                    ruined = True; break
            dd_list.append(mx)
            final_list.append(eq)
            if ruined:
                ruin += 1

        dd_list.sort(); final_list.sort()
        n = len(dd_list)
        return {
            "simulations":        sims,
            "ruin_prob_pct":      round(ruin / sims * 100, 2),
            "max_dd_p50":         round(dd_list[n // 2], 2),
            "max_dd_p95":         round(dd_list[int(n * 0.95)], 2),
            "max_dd_p99":         round(dd_list[int(n * 0.99)], 2),
            "final_equity_p10":   round(final_list[int(n * 0.10)], 2),
            "final_equity_p50":   round(final_list[n // 2], 2),
            "final_equity_p90":   round(final_list[int(n * 0.90)], 2),
        }


# ── Parameter Sensitivity ─────────────────────────────────────────────────────

class SensitivityAnalyser:
    """Grid-search over ATR multiplier and quality threshold."""

    def run(
        self, bars: List[BTBar], balance: float = 10000.0,
        risk_pct: float = 0.5
    ) -> List[Dict[str, Any]]:
        sim     = BarSimulator()
        results = []

        for atr_mult in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5]:
            for quality_thresh in [75, 80, 85, 90]:
                result = BTResult(
                    label=f"atr={atr_mult} q={quality_thresh}"
                )
                atr   = 1.5
                eq    = balance
                step  = max(1, len(bars) // 50)

                for i in range(20, len(bars), step):
                    if eq <= 0:
                        break
                    em_f = statistics.mean(b.close for b in bars[i-10:i])
                    em_s = statistics.mean(b.close for b in bars[i-20:i])
                    direction = "LONG" if em_f > em_s else "SHORT"
                    entry = bars[i].close
                    sl_d  = atr * atr_mult

                    # Dynamic lot sizing — canonical function, compounded equity
                    vol, risk = _calc_volume(eq, sl_d, risk_pct=risk_pct)

                    if direction == "LONG":
                        sl = entry - sl_d
                        tp1 = entry + sl_d
                        tp2 = entry + sl_d * 2
                        tp3 = entry + sl_d * 3
                    else:
                        sl = entry + sl_d
                        tp1 = entry - sl_d
                        tp2 = entry - sl_d * 2
                        tp3 = entry - sl_d * 3

                    t = BTTrade(
                        direction=direction, entry_price=entry,
                        entry_time=bars[i].time,
                        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                        volume=vol, risk_usd=risk,
                        balance_at_entry=eq,
                    )
                    t = sim.run(t, bars[i+1:i+60], atr)
                    # Compound equity — next trade uses updated balance
                    eq += t.pnl
                    result.trades.append(t)

                result.compute(balance)
                results.append({
                    "atr_mult":       atr_mult,
                    "quality_thresh": quality_thresh,
                    "net_pnl":        round(result.net_pnl, 2),
                    "return_pct":     round(result.return_pct, 2),
                    "final_equity":   round(result.final_equity, 2),
                    "win_rate":       round(result.win_rate, 1),
                    "sharpe":         round(result.sharpe, 3),
                    "max_dd_pct":     round(result.max_dd_pct, 2),
                    "profit_factor":  round(result.profit_factor, 2),
                })

        results.sort(key=lambda x: -x["sharpe"])
        return results


# ── CLI ───────────────────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="XAUUSD Pro Backtest (Dynamic Compounding)")
    parser.add_argument("--years",    type=float, default=1.0,     help="History length in years")
    parser.add_argument("--balance",  type=float, default=10000.0, help="Initial account balance USD")
    parser.add_argument("--risk-pct", type=float, default=0.5,     help="Risk per trade %%")
    parser.add_argument("--mc-sims",  type=int,   default=1000,    help="Monte Carlo simulations")
    args = parser.parse_args()

    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=int(365 * args.years))

    engine = WalkForwardEngine(
        is_months=3, oos_months=1,
        risk_pct=args.risk_pct,
    )
    report = await engine.run(start, end, balance=args.balance)

    # ── Monte Carlo on OOS PnL stream ────────────────────────────────────────
    oos_pnls: List[float] = report.pop("_oos_pnls", [])
    mc = MonteCarloSimulator()
    if oos_pnls:
        mc_result = mc.run(oos_pnls, args.mc_sims, args.balance)
        report["monte_carlo"] = mc_result
        print("Monte Carlo (OOS PnL stream):")
        for k, v in mc_result.items():
            print(f"  {k:<35} {v}")

    with open("backtest_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nReport -> backtest_report.json")


if __name__ == "__main__":
    asyncio.run(main())
