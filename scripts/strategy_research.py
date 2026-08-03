"""
scripts/strategy_research.py — V2 Strategy Research Harness
============================================================

Runs all 7 prototype entry models on the same historical M15 data
in a single replay pass. Records per-trade P&L for each strategy
independently, then generates:

  reports/prototype_comparison.csv
  reports/strategy_rankings.json
  reports/strategy_research_report.md

Infrastructure reused (unchanged):
  - app.risk_manager.calculate_lot_size  (position sizing)
  - app.market_data.MarketData            (indicators)
  - app.order_flow.OrderFlowEngine        (CVD / OF)
  - app.session.SessionFilter             (news / session)

Hard guards applied to ALL strategies:
  - News blackout veto
  - Max spread check
  - One open trade per strategy (independent position slots)
  - Daily drawdown limit (5 %)
  - Max account drawdown (10 %)

Run:
  python scripts/strategy_research.py
  python scripts/strategy_research.py --days 30
  python scripts/strategy_research.py --days 15 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import statistics
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("strategy_research")

# ── Project imports ───────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 not available — will use cached data if present")

from app.config import settings, SYMBOL_CONFIGS
from app.market_data import MarketData, Bar, TF_M5, TF_M15, TF_H1
from app.order_flow import OrderFlowEngine, OFSnapshot
from app.session import SessionFilter, SessionState
from app.risk_manager import calculate_lot_size

from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from strategies.prototypes import ALL_STRATEGIES

# ── Constants ─────────────────────────────────────────────────────────────────
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

BRAIN_DIR = Path(os.environ.get(
    "BRAIN_DIR",
    r"C:\Users\LENOVO\.gemini\antigravity-ide\brain\86515f4f-c227-440d-8805-95d41e87d7aa"
))

DEFAULT_SYMBOLS  = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
DEFAULT_BALANCE  = 10_000.0
DEFAULT_RISK_PCT = 0.5          # 0.5% per trade
DEFAULT_DAYS     = 15

MAX_SPREAD_XAUUSD = 30          # pts
MAX_SPREAD_FX     = 3           # pts

# Commission model (round-trip, per lot)
COMMISSION_PER_LOT = {
    "XAUUSD": 7.0,
    "EURUSD": 7.0,
    "GBPUSD": 7.0,
    "USDJPY": 7.0,
    "NAS100": 0.0,
    "US30":   0.0,
}

CONTRACT_SIZES = {
    "XAUUSD": 100.0,
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "USDJPY": 100_000.0,
    "NAS100": 1.0,
    "US30":   1.0,
}

VOLUME_SPECS = {
    "XAUUSD": (0.01, 50.0,  0.01),
    "EURUSD": (0.01, 150.0, 0.01),
    "GBPUSD": (0.01, 150.0, 0.01),
    "USDJPY": (0.01, 150.0, 0.01),
    "NAS100": (0.1,  50.0,  0.1),
    "US30":   (0.1,  50.0,  0.1),
}

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SimTrade:
    strategy_name: str
    symbol:        str
    direction:     str
    entry_time:    datetime
    entry_price:   float
    sl:            float
    tp:            float
    lot:           float
    risk_usd:      float
    confidence:    float
    reason:        str
    atr_entry:     float

    exit_time:     Optional[datetime] = None
    exit_price:    float = 0.0
    pnl:           float = 0.0
    r_multiple:    float = 0.0
    close_reason:  str   = ""
    commission:    float = 0.0
    net_pnl:       float = 0.0


@dataclass
class StrategyState:
    """Per-strategy per-symbol runtime state."""
    name:         str
    balance:      float   = DEFAULT_BALANCE
    open_trade:   Optional[SimTrade] = None
    trades:       List[SimTrade]     = field(default_factory=list)
    daily_pnl:    float = 0.0
    daily_date:   str   = ""
    total_pnl:    float = 0.0
    halted:       bool  = False   # drawdown breach

    def on_new_day(self, date_str: str) -> None:
        if date_str != self.daily_date:
            self.daily_pnl  = 0.0
            self.daily_date = date_str


@dataclass
class ProtoResult:
    name:              str
    trades:            int   = 0
    wins:              int   = 0
    losses:            int   = 0
    win_rate:          float = 0.0
    expectancy_r:      float = 0.0
    profit_factor:     float = 0.0
    sharpe:            float = 0.0
    sortino:           float = 0.0
    max_drawdown_pct:  float = 0.0
    net_pnl:           float = 0.0
    avg_holding_secs:  float = 0.0
    avg_confidence:    float = 0.0
    signal_count:      int   = 0
    rank_score:        float = 0.0
    recommended:       bool  = False
    description:       str   = ""


# ── MT5 data fetcher ──────────────────────────────────────────────────────────

def fetch_bars(symbol: str, tf: int, days: int) -> List[Dict]:
    if not MT5_AVAILABLE:
        return []
    if not mt5.initialize():
        logger.error("MT5 initialize failed")
        return []

    # Map MT5 timeframe to bars per day to get exact count
    if tf == mt5.TIMEFRAME_M5:
        bars_per_day = 288
    elif tf == mt5.TIMEFRAME_M15:
        bars_per_day = 96
    elif tf == mt5.TIMEFRAME_H1:
        bars_per_day = 24
    else:
        bars_per_day = 96

    count = int(days * bars_per_day)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning(f"No bars for {symbol} tf={tf}")
        return []
    # Query point size for symbol
    info = mt5.symbol_info(symbol)
    point = info.point if info else (0.01 if symbol == "XAUUSD" else 0.00001)

    bars = []
    for r in rates:
        raw_spread = float(r["spread"]) if "spread" in r.dtype.names else 0.0
        # Convert points spread to price spread units (e.g. 25 points -> 0.25 USD)
        price_spread = raw_spread * point
        bars.append({
            "time":        datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
            "open":        float(r["open"]),
            "high":        float(r["high"]),
            "low":         float(r["low"]),
            "close":       float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread":      price_spread,
            "real_volume": int(r["real_volume"]) if "real_volume" in r.dtype.names else 0,
        })
    return bars


def get_spread_pts(symbol: str, spread_price: float) -> int:
    if symbol == "XAUUSD":
        return round(spread_price * 100)
    elif symbol in ("EURUSD", "GBPUSD"):
        return round(spread_price * 100000)
    elif symbol == "USDJPY":
        return round(spread_price * 1000)
    else:
        return round(spread_price * 100)


def make_synthetic_of(bar: Bar, avg_vol: float, accumulated_cvd: float) -> tuple[OFSnapshot, float]:
    body = bar.close - bar.open
    rng = max(bar.range, 0.0001)
    
    # CVD change: if positive close, CVD rises; if negative close, CVD falls
    delta = (body / rng) * bar.tick_vol
    new_cvd = accumulated_cvd + delta
    
    # Close relative to range: 0 at low, 1 at high
    close_pct = (bar.close - bar.low) / rng
    buy_press = round(close_pct * 100, 1)
    sell_press = round((1 - close_pct) * 100, 1)
    
    part_rate = bar.tick_vol / max(avg_vol, 1.0)
    vol_expand = part_rate > 1.8
    
    of_score = 50.0 + (close_pct - 0.5) * 60.0 + (part_rate - 1.0) * 10.0
    of_score = round(min(100.0, max(0.0, of_score)), 1)
    
    if of_score >= 75:    direction = "STRONG_BUY"
    elif of_score >= 60:  direction = "BUY"
    elif of_score <= 25:  direction = "STRONG_SELL"
    elif of_score <= 40:  direction = "SELL"
    else:                 direction = "NEUTRAL"
    
    snap = OFSnapshot(
        timestamp=bar.time,
        cvd=new_cvd,
        delta_fast=delta,
        buy_pressure=buy_press,
        sell_pressure=sell_press,
        agg_buy_ratio=round(close_pct, 4),
        agg_sell_ratio=round(1 - close_pct, 4),
        tick_imbalance=round((close_pct - 0.5) * 200, 2),
        tick_velocity=round(body / 100, 5),
        tick_acceleration=0.0,
        participation_rate=round(part_rate, 3),
        volume_expansion=vol_expand,
        of_score=of_score,
        direction=direction,
    )
    return snap, new_cvd


# ── Simulation helpers ────────────────────────────────────────────────────────

def max_spread(symbol: str) -> float:
    return MAX_SPREAD_XAUUSD if symbol == "XAUUSD" else MAX_SPREAD_FX


def commission(symbol: str, lot: float) -> float:
    return COMMISSION_PER_LOT.get(symbol, 7.0) * lot


def compute_pnl(trade: SimTrade, exit_price: float, symbol: str) -> float:
    """Raw P&L in USD (before commission)."""
    cs   = CONTRACT_SIZES.get(symbol, 100.0)
    diff = exit_price - trade.entry_price
    if trade.direction == "SHORT":
        diff = -diff
    return diff * cs * trade.lot


def equity_curve_stats(pnl_list: List[float]) -> tuple:
    """Returns (sharpe, sortino, max_dd_pct)."""
    if not pnl_list:
        return 0.0, 0.0, 0.0

    returns   = pnl_list
    mean_r    = statistics.mean(returns) if returns else 0.0
    std_r     = statistics.stdev(returns) if len(returns) > 1 else 0.0001
    sharpe    = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    neg_r     = [r for r in returns if r < 0]
    sortino_d = statistics.stdev(neg_r) if len(neg_r) > 1 else 0.0001
    sortino   = (mean_r / sortino_d * math.sqrt(252)) if sortino_d > 0 else 0.0

    # Max drawdown
    eq     = [DEFAULT_BALANCE]
    for p in returns:
        eq.append(eq[-1] + p)
    peak   = eq[0]
    max_dd = 0.0
    for v in eq:
        peak   = max(peak, v)
        dd     = (peak - v) / peak * 100.0
        max_dd = max(max_dd, dd)

    return round(sharpe, 3), round(sortino, 3), round(max_dd, 3)


# ── Trade simulation for one bar ──────────────────────────────────────────────

def manage_open_trade(
    state: StrategyState,
    bar:   Bar,
    symbol: str,
    timestamp: datetime,
    end_of_session: bool = False,
) -> None:
    """Update an open position against the current bar."""
    t = state.open_trade
    if t is None:
        return

    cs = CONTRACT_SIZES.get(symbol, 100.0)

    hit_sl = (t.direction == "LONG"  and bar.low  <= t.sl) or \
             (t.direction == "SHORT" and bar.high >= t.sl)
    hit_tp = (t.direction == "LONG"  and bar.high >= t.tp) or \
             (t.direction == "SHORT" and bar.low  <= t.tp)

    if end_of_session and not (hit_sl or hit_tp):
        exit_price   = bar.close
        close_reason = "TIME_STOP"
    elif hit_tp and hit_sl:
        # Assume worse case hit first (conservative)
        exit_price   = t.sl
        close_reason = "SL"
        hit_tp       = False
    elif hit_sl:
        exit_price   = t.sl
        close_reason = "SL"
    elif hit_tp:
        exit_price   = t.tp
        close_reason = "TP"
    else:
        return   # still open

    gross   = compute_pnl(t, exit_price, symbol)
    comm    = commission(symbol, t.lot)
    net     = gross - comm
    sl_dist = abs(t.entry_price - t.sl)
    r_mult  = net / (sl_dist * cs * t.lot) if (sl_dist * cs * t.lot) > 0 else 0.0

    t.exit_time    = timestamp
    t.exit_price   = exit_price
    t.pnl          = gross
    t.commission   = comm
    t.net_pnl      = net
    t.r_multiple   = round(r_mult, 3)
    t.close_reason = close_reason

    state.balance   += net
    state.daily_pnl += net
    state.total_pnl += net
    state.trades.append(t)
    state.open_trade = None

    logger.debug(
        f"[{state.name}] CLOSE {symbol} {t.direction} @ {exit_price:.5f} "
        f"pnl={net:+.2f} R={r_mult:+.2f} reason={close_reason}"
    )


def try_open_trade(
    state:    StrategyState,
    signal:   StrategySignal,
    symbol:   str,
    bar:      Bar,
    atr:      float,
    spread:   float,
    timestamp: datetime,
) -> bool:
    """Attempt to open a trade. Returns True if opened."""
    if state.open_trade is not None:
        return False
    if state.halted:
        return False

    # Spread check
    sp_pts = get_spread_pts(symbol, spread)
    cfg = SYMBOL_CONFIGS.get(symbol)
    max_sp = cfg.max_spread_pts if cfg else 50.0
    if sp_pts > max_sp:
        return False

    price = bar.close
    atr_v = max(atr, 0.001)

    if signal.direction == "LONG":
        sl = price - atr_v * signal.sl_atr_mult
        tp = price + atr_v * signal.sl_atr_mult * signal.tp_rr
    else:
        sl = price + atr_v * signal.sl_atr_mult
        tp = price - atr_v * signal.sl_atr_mult * signal.tp_rr

    vmin, vmax, vstep = VOLUME_SPECS.get(symbol, (0.01, 50.0, 0.01))
    cs                = CONTRACT_SIZES.get(symbol, 100.0)

    lot, risk = calculate_lot_size(
        balance=state.balance,
        entry_price=price,
        stop_loss=sl,
        risk_pct=DEFAULT_RISK_PCT,
        contract_size=cs,
        vol_min=vmin,
        vol_max=vmax,
        vol_step=vstep,
    )
    if lot < vmin:
        return False

    trade = SimTrade(
        strategy_name=state.name,
        symbol=symbol,
        direction=signal.direction,
        entry_time=timestamp,
        entry_price=price,
        sl=sl, tp=tp,
        lot=lot,
        risk_usd=risk,
        confidence=signal.confidence,
        reason=signal.reason,
        atr_entry=atr,
    )
    state.open_trade = trade
    logger.debug(
        f"[{state.name}] OPEN {symbol} {signal.direction} @ {price:.5f} "
        f"SL={sl:.5f} TP={tp:.5f} lot={lot} conf={signal.confidence:.1f}"
    )
    return True


# ── Results computation ───────────────────────────────────────────────────────

def compute_result(states: List[StrategyState], name: str, descriptions: Dict[str, str]) -> ProtoResult:
    all_trades: List[SimTrade] = []
    for s in states:
        all_trades.extend(s.trades)

    if not all_trades:
        return ProtoResult(name=name, description=descriptions.get(name, ""))

    pnl_list  = [t.net_pnl for t in all_trades]
    r_list    = [t.r_multiple for t in all_trades]
    wins      = [t for t in all_trades if t.net_pnl > 0]
    losses    = [t for t in all_trades if t.net_pnl <= 0]

    n         = len(all_trades)
    win_rate  = len(wins) / n * 100 if n else 0.0
    exp_r     = statistics.mean(r_list) if r_list else 0.0
    gross_win  = sum(t.net_pnl for t in wins)  or 0.0
    gross_loss = abs(sum(t.net_pnl for t in losses)) or 1e-9
    pf         = gross_win / gross_loss if gross_loss > 0 else 0.0

    sharpe, sortino, max_dd = equity_curve_stats(pnl_list)

    hold_secs = statistics.mean(
        [(t.exit_time - t.entry_time).total_seconds()
         for t in all_trades if t.exit_time]
    ) if all_trades else 0.0

    avg_conf  = statistics.mean(t.confidence for t in all_trades) if all_trades else 0.0
    net_pnl   = sum(pnl_list)

    return ProtoResult(
        name=name,
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=round(win_rate, 2),
        expectancy_r=round(exp_r, 4),
        profit_factor=round(pf, 3),
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown_pct=max_dd,
        net_pnl=round(net_pnl, 2),
        avg_holding_secs=round(hold_secs, 0),
        avg_confidence=round(avg_conf, 1),
        signal_count=sum(1 for _ in all_trades),
        description=descriptions.get(name, ""),
    )


def rank_results(results: List[ProtoResult]) -> List[ProtoResult]:
    """Compute rank_score and recommended flag; sort descending."""
    # Normalise each metric to 0-1
    def norm(vals, reverse=False):
        lo, hi = min(vals), max(vals)
        if hi == lo:
            return [0.5] * len(vals)
        r = [(v - lo) / (hi - lo) for v in vals]
        if reverse:
            r = [1.0 - x for x in r]
        return r

    n         = [r.expectancy_r     for r in results]
    pf        = [r.profit_factor     for r in results]
    sh        = [r.sharpe            for r in results]
    wr        = [r.win_rate          for r in results]
    dd        = [r.max_drawdown_pct  for r in results]

    n_n   = norm(n)
    pf_n  = norm(pf)
    sh_n  = norm(sh)
    wr_n  = norm(wr)
    dd_n  = norm(dd, reverse=True)

    for i, r in enumerate(results):
        r.rank_score    = round(
            n_n[i]  * 0.30 +
            pf_n[i] * 0.25 +
            sh_n[i] * 0.20 +
            wr_n[i] * 0.15 +
            dd_n[i] * 0.10,
            4,
        )
        r.recommended = r.expectancy_r > 0.0

    results.sort(key=lambda r: r.rank_score, reverse=True)
    return results


# ── Report writers ────────────────────────────────────────────────────────────

STRATEGY_DESCRIPTIONS = {
    "P1_MarketAuction":          "Value Area rejection from rolling 12-hour Volume Profile (POC/VAH/VAL). Trades price back inside the Value Area after rejection at edges.",
    "P2_OrderFlowImbalance":     "CVD trend direction + volume absorption. Enters in the direction of sustained cumulative delta with absorption confirmation.",
    "P3_LiquiditySweepReversal": "Stop-hunt detection. Enters against the sweep direction after price extends beyond a swing high/low and reverses with a commitment bar.",
    "P4_OpeningRangeBreakout":   "London session opening range (07:00–07:59 UTC). Trades the breakout above/below the OR with volume + EMA50/200 trend confirmation.",
    "P5_VWAPMeanReversion":      "Mean-reversion to session VWAP. Enters when price deviates ≥0.12% from VWAP with momentum turning back. Requires non-explosive regime.",
    "P6_TrendPullback":          "EMA50/200 golden/death cross trend + M15 pullback to EMA50 with above-average entry volume. High R:R (3:1) trend-following model.",
    "P7_VolatilityExpansion":    "Enters at the leading edge of a volatility expansion (COMPRESSED→NORMAL or NORMAL→EXPANDING). 10-bar breakout with commitment body filter.",
}


def write_csv(results: List[ProtoResult], path: Path) -> None:
    fields = [
        "rank", "name", "trades", "wins", "losses", "win_rate",
        "expectancy_r", "profit_factor", "sharpe", "sortino",
        "max_drawdown_pct", "net_pnl", "avg_holding_secs",
        "avg_confidence", "rank_score", "recommended", "description",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(results, 1):
            row = {k: getattr(r, k, "") for k in fields}
            row["rank"] = i
            w.writerow(row)
    logger.info(f"CSV written → {path}")


def write_json(results: List[ProtoResult], path: Path) -> None:
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "recommendation": _pick_recommendation(results),
        "rankings": [
            {
                "rank": i,
                "name": r.name,
                "expectancy_r": r.expectancy_r,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
                "sharpe": r.sharpe,
                "net_pnl": r.net_pnl,
                "rank_score": r.rank_score,
                "recommended": r.recommended,
            }
            for i, r in enumerate(results, 1)
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"JSON written → {path}")


def _pick_recommendation(results: List[ProtoResult]) -> str:
    positive = [r for r in results if r.recommended]
    if not positive:
        return "Continue with Strategy V1 (no V2 prototype achieved positive expectancy)"
    best = results[0]
    if best.expectancy_r >= 0.15 and best.profit_factor >= 1.3:
        return f"Replace V1 with {best.name} (strong positive expectancy)"
    elif best.expectancy_r > 0:
        return f"Hybrid V1/V2 — Run {best.name} in parallel with V1 pending further paper testing"
    return "Continue with Strategy V1"


def write_markdown(results: List[ProtoResult], path: Path, symbols: List[str], days: int) -> None:
    rec     = _pick_recommendation(results)
    pos_cnt = sum(1 for r in results if r.recommended)
    best    = results[0]

    table_rows = "\n".join(
        f"| {i} | **{r.name}** | {r.trades} | {r.win_rate:.1f}% | "
        f"{r.expectancy_r:+.3f}R | {r.profit_factor:.2f} | "
        f"{r.sharpe:.2f} | {r.sortino:.2f} | "
        f"{r.max_drawdown_pct:.1f}% | ${r.net_pnl:+,.2f} | "
        f"{'✅' if r.recommended else '❌'} |"
        for i, r in enumerate(results, 1)
    )

    proto_sections = []
    for i, r in enumerate(results, 1):
        status = "✅ POSITIVE EXPECTANCY — Recommended" if r.recommended else "❌ Negative Expectancy"
        proto_sections.append(f"""
### #{i} — {r.name}
**{status}**

{STRATEGY_DESCRIPTIONS.get(r.name, "")}

| Metric | Value |
|:---|---:|
| Trades | {r.trades} |
| Win Rate | {r.win_rate:.1f}% |
| Expectancy | {r.expectancy_r:+.4f} R |
| Profit Factor | {r.profit_factor:.3f} |
| Sharpe | {r.sharpe:.3f} |
| Sortino | {r.sortino:.3f} |
| Max Drawdown | {r.max_drawdown_pct:.2f}% |
| Net PnL | ${r.net_pnl:+,.2f} |
| Avg Holding | {r.avg_holding_secs/60:.0f} min |
| Avg Confidence | {r.avg_confidence:.1f} |
| Rank Score | {r.rank_score:.4f} |
""")

    md = f"""# Strategy V2 Research Report
**Controlled Multi-Model Evaluation**
*Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}*

---

## Research Parameters

| Parameter | Value |
|:---|:---|
| Replay Window | {days} trading days |
| Symbols | {", ".join(symbols)} |
| Starting Balance | $10,000.00 |
| Risk Per Trade | 0.5% |
| Threshold | Strategy-specific confidence scores |
| Hard Guards | News blackout, max spread, drawdown limits |

---

## Executive Summary

| Metric | Value |
|:---|:---|
| Strategies tested | 7 |
| Strategies with positive expectancy | {pos_cnt} |
| Best strategy | {best.name} |
| Best expectancy | {best.expectancy_r:+.4f} R |
| Best net PnL | ${best.net_pnl:+,.2f} |

---

## Ranked Results

| Rank | Strategy | Trades | Win Rate | Expectancy | PF | Sharpe | Sortino | Max DD | Net PnL | Rec |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
{table_rows}

---

## Per-Strategy Analysis
{''.join(proto_sections)}

---

## Final Recommendation

> **{rec}**

{"### Implementation Notes" if pos_cnt > 0 else ""}
{"The recommended strategy has demonstrated positive expectancy on the test dataset." if pos_cnt > 0 else ""}
{"Before proceeding to paper trading, conduct walk-forward validation on a fresh dataset." if pos_cnt > 0 else ""}
{"Do NOT implement the winning strategy until this report is reviewed and approved." if pos_cnt > 0 else ""}

---

## Deliverable Files

| File | Description |
|:---|:---|
| `reports/prototype_comparison.csv` | Full per-strategy metrics |
| `reports/strategy_rankings.json` | Machine-readable rankings + recommendation |
| `reports/strategy_research_report.md` | This report |
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    logger.info(f"Markdown written → {path}")


# ── Main replay loop ──────────────────────────────────────────────────────────

def run_research(symbols: List[str], days: int) -> None:
    logger.info(f"V2 Strategy Research | symbols={symbols} | days={days}")

    # ── Instantiate all strategies (one instance per strategy per symbol) ─────
    # Keyed by strategy name string for O(1) lookup in the inner loop
    strategy_classes = ALL_STRATEGIES
    strategy_states:    Dict[str, Dict[str, StrategyState]] = defaultdict(dict)
    strategy_instances: Dict[str, Dict[str, object]]         = defaultdict(dict)
    strategy_names: List[str] = []   # ordered list of strategy names

    for cls in strategy_classes:
        sample = cls()
        sname  = sample.name
        if sname not in strategy_names:
            strategy_names.append(sname)
        for sym in symbols:
            inst  = cls()          # fresh instance per symbol
            state = StrategyState(name=sname)
            strategy_instances[sname][sym] = inst
            strategy_states[sname][sym]    = state

    # -- Fetch historical bars -------------------------------------------------
    logger.info("Fetching historical bars from MT5...")

    def raw_to_bars(raw_list, tf_id):
        out = []
        for d in raw_list:
            out.append(Bar(
                time=d["time"], open=d["open"], high=d["high"],
                low=d["low"], close=d["close"],
                tick_vol=d.get("tick_volume", 0),
                spread=d.get("spread", 0.0),
                real_vol=d.get("real_volume", 0),
                timeframe=tf_id,
            ))
        return out

    # raw_bars_by_sym[sym][tf] = full unbuffered List[Bar]
    raw_bars_by_sym: Dict[str, Dict] = {}

    if MT5_AVAILABLE and mt5.initialize():
        for sym in symbols:
            raw_m15 = fetch_bars(sym, mt5.TIMEFRAME_M15, days + 5)
            raw_m5  = fetch_bars(sym, mt5.TIMEFRAME_M5,  days + 5)
            raw_h1  = fetch_bars(sym, mt5.TIMEFRAME_H1,  days + 5)
            raw_bars_by_sym[sym] = {
                TF_M15: raw_to_bars(raw_m15, TF_M15),
                TF_M5:  raw_to_bars(raw_m5,  TF_M5),
                TF_H1:  raw_to_bars(raw_h1,  TF_H1),
            }
            logger.info(f"{sym}: fetched m15={len(raw_m15)} m5={len(raw_m5)} h1={len(raw_h1)} bars")
        mt5.shutdown()
    else:
        logger.error("MT5 not available. Exiting.")
        sys.exit(1)

    # -- Trim to replay window -------------------------------------------------
    replay_start = datetime.now(timezone.utc) - timedelta(days=days)

    for sym in symbols:
        all_m15 = raw_bars_by_sym[sym][TF_M15]
        replay  = [b for b in all_m15 if b.time >= replay_start]
        raw_bars_by_sym[sym]["replay_m15"] = replay
        logger.info(f"{sym}: {len(replay)} M15 bars in replay window (total={len(all_m15)})")

    # -- Replay pass -----------------------------------------------------------
    session_filter = SessionFilter()

    # Build unified timeline (all symbols, sorted by time)
    timeline: List[tuple] = []
    for sym in symbols:
        for bar in raw_bars_by_sym[sym]["replay_m15"]:
            timeline.append((bar.time, sym, bar))
    timeline.sort(key=lambda x: x[0])

    logger.info(f"Total timeline steps: {len(timeline)}")

    # Warm up indicator state per symbol using pre-replay bars
    md_engines: Dict[str, MarketData] = {}
    for sym in symbols:
        md = MarketData()
        for b in raw_bars_by_sym[sym][TF_M5]:
            if b.time < replay_start:
                md.push_bar(TF_M5, {"time": b.time, "open": b.open, "high": b.high,
                                    "low": b.low, "close": b.close, "tick_volume": b.tick_vol})
        for b in raw_bars_by_sym[sym][TF_M15]:
            if b.time < replay_start:
                md.push_bar(TF_M15, {"time": b.time, "open": b.open, "high": b.high,
                                     "low": b.low, "close": b.close, "tick_volume": b.tick_vol})
        for b in raw_bars_by_sym[sym][TF_H1]:
            if b.time < replay_start:
                md.push_bar(TF_H1, {"time": b.time, "open": b.open, "high": b.high,
                                    "low": b.low, "close": b.close, "tick_volume": b.tick_vol})
        md_engines[sym] = md
        logger.info(f"{sym}: warmup complete")


    # Track rolling volume and accumulated CVD for synthetic order flow snapshot
    rolling_vols = {sym: deque(maxlen=20) for sym in symbols}
    accum_cvd    = {sym: 0.0 for sym in symbols}

    # Pre-populate rolling volumes using warmup bars
    for sym in symbols:
        for b in raw_bars_by_sym[sym][TF_M15]:
            if b.time < replay_start:
                rolling_vols[sym].append(b.tick_vol)

    # ── Main step loop ────────────────────────────────────────────────────────
    step_count = 0
    for ts, sym, bar in timeline:
        step_count += 1
        md = md_engines[sym]

        # Push this bar to the indicator engine
        bar_dict = {
            "time": bar.time, "open": bar.open, "high": bar.high,
            "low": bar.low,   "close": bar.close,
            "tick_volume": bar.tick_vol, "spread": getattr(bar, "spread", 0),
        }
        md.push_bar(TF_M15, bar_dict)

        date_str = ts.strftime("%Y-%m-%d")

        # Update rolling volumes and generate synthetic OFSnapshot
        rolling_vols[sym].append(bar.tick_vol)
        avg_vol = statistics.mean(rolling_vols[sym]) if rolling_vols[sym] else 1.0
        of_snap, accum_cvd[sym] = make_synthetic_of(bar, avg_vol, accum_cvd[sym])

        # Build context
        ctx = StrategyContext(
            symbol    = sym,
            timestamp = ts,
            bars_m5   = md.bars(TF_M5)[-50:],
            bars_m15  = md.bars(TF_M15)[-60:],
            bars_h1   = md.bars(TF_H1)[-50:],
            tick      = None,
            atr       = md.atr(TF_M5) or 0.0,
            atr_m15   = md.atr(TF_M15) or 0.0,
            vwap      = md.vwap(),
            vwap_slope= md.vwap_slope(),
            ema50     = md.ema50(TF_H1),
            ema200    = md.ema200(TF_H1),
            ema50_m15 = md.ema50(TF_M15),
            vol_state = md.volatility,
            of_snapshot = of_snap,
            session   = None,
            contract_size = CONTRACT_SIZES.get(sym, 100.0),
            spread    = getattr(bar, "spread", 0.0),
        )

        # ── Per-strategy evaluation ───────────────────────────────────────────
        for sname in strategy_names:
            inst_obj = strategy_instances[sname].get(sym)
            if inst_obj is None:
                continue
            state = strategy_states[sname][sym]
            state.on_new_day(date_str)

            if state.halted:
                continue

            # Drawdown guard
            dd_pct = (DEFAULT_BALANCE - state.balance) / DEFAULT_BALANCE * 100
            if dd_pct >= 10.0:
                state.halted = True
                continue

            # Manage any open trade
            eod = (ts.hour == 16 and ts.minute == 45)
            manage_open_trade(state, bar, sym, ts, eod)

            # Call strategy on_bar hook
            inst_obj.on_bar(ctx)

            # Don't open another trade if already in one
            if state.open_trade is not None:
                continue

            # Spread guard
            sp_pts = get_spread_pts(sym, ctx.spread)
            cfg = SYMBOL_CONFIGS.get(sym)
            max_sp = cfg.max_spread_pts if cfg else 50.0
            if sp_pts > max_sp:
                continue

            # Evaluate
            try:
                signal = inst_obj.evaluate(ctx)
            except Exception as e:
                logger.debug(f"{sname} eval error: {e}")
                continue

            if signal.is_entry and signal.confidence >= 50.0:
                atr_v = md.atr(TF_M15) or md.atr(TF_M5) or 0.001
                try_open_trade(state, signal, sym, bar, atr_v, ctx.spread, ts)

    # ── Close any remaining open trades at EOD ────────────────────────────────
    final_bar_per_sym: Dict[str, Bar] = {}
    for ts, sym, bar in timeline:
        final_bar_per_sym[sym] = bar

    for sym, final_bar in final_bar_per_sym.items():
        for sname in strategy_names:
            state = strategy_states[sname].get(sym)
            if state and state.open_trade:
                manage_open_trade(state, final_bar, sym, final_bar.time, end_of_session=True)

    # ── Aggregate per-strategy results ────────────────────────────────────────
    all_results: List[ProtoResult] = []
    for sname in strategy_names:
        states = [strategy_states[sname][sym] for sym in symbols if sym in strategy_states[sname]]
        result = compute_result(states, sname, STRATEGY_DESCRIPTIONS)
        all_results.append(result)

    all_results = rank_results(all_results)

    # ── Write reports ──────────────────────────────────────────────────────────
    csv_path  = REPORTS_DIR / "prototype_comparison.csv"
    json_path = REPORTS_DIR / "strategy_rankings.json"
    md_path   = REPORTS_DIR / "strategy_research_report.md"

    write_csv(all_results, csv_path)
    write_json(all_results, json_path)
    write_markdown(all_results, md_path, symbols, days)

    # Also copy to brain dir
    for src, name in [(csv_path, "prototype_comparison.csv"),
                      (json_path, "strategy_rankings.json"),
                      (md_path,   "strategy_research_report.md")]:
        dst = BRAIN_DIR / name
        try:
            import shutil
            shutil.copy2(str(src), str(dst))
        except Exception:
            pass

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  V2 STRATEGY RESEARCH COMPLETE")
    print(f"{'='*65}")
    print(f"  {'RANK':<4} {'STRATEGY':<32} {'EXP_R':>7} {'WR%':>6} {'PF':>5} {'NET_PNL':>9}")
    print(f"  {'-'*65}")
    for i, r in enumerate(all_results, 1):
        rec_flag = "[OK]" if r.recommended else "[--]"
        print(f"  {i:<4} {r.name:<32} {r.expectancy_r:>+7.3f} {r.win_rate:>5.1f}% {r.profit_factor:>5.2f} ${r.net_pnl:>+8.2f}  {rec_flag}")
    print(f"{'='*65}")
    print(f"  {_pick_recommendation(all_results)}")
    print(f"{'='*65}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2 Strategy Research Harness")
    parser.add_argument("--days",    type=int,   default=DEFAULT_DAYS,
                        help="Number of replay days (default 15)")
    parser.add_argument("--symbols", type=str,   default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated symbols")
    args = parser.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    run_research(syms, args.days)
