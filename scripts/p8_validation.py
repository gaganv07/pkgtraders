"""
scripts/p8_validation.py — P8 ORB V2 vs P4 ORB Validation

Walk-forward comparison of P8 (forensics-fixed ORB) vs P4 (original ORB)
on 60 days of M15 history with Monte Carlo certification.

Usage:
    python scripts/p8_validation.py              # MT5-connected mode
    python scripts/p8_validation.py --offline    # synthetic bars
    REPLAY_DAYS=30 python scripts/p8_validation.py

Outputs:
    reports/p8_validation_report.md     — walk-forward comparison + certification
    reports/p8_trades.csv               — P8 per-trade log
    reports/p4_trades.csv               — P4 per-trade log (baseline)
"""

import os, sys, csv, math, random, logging, statistics
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

os.makedirs("reports", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("reports/p8_validation.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("p8_validation")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

OFFLINE_MODE = "--offline" in sys.argv

from app.config import settings, enabled_symbols
from app.market_data import (
    MultiSymbolMarketData, MarketData, TF_M5, TF_M15, TF_H1, Bar, Tick,
)
from app.microstructure import MicrostructureEngine
from app.volume_analytics import VolumeAnalytics
from app.session import SessionFilter
from strategies.context import StrategyContext
from strategies.prototypes.p4_opening_range_breakout import OpeningRangeBreakoutStrategy
from strategies.prototypes.p8_orb_v2 import OpeningRangeBreakoutV2Strategy
from app.position_sizer import PositionSizer, BrokerSpec

MarketData.is_fresh = property(lambda self: True)   # type: ignore

# ── Default specs ─────────────────────────────────────────────────────────────
_DEFAULT_SPECS: Dict[str, Dict] = {
    "XAUUSD": {"digits": 2, "point": 0.01, "spread": 15,
               "contract_size": 100.0, "vol_min": 0.01, "vol_max": 50.0, "vol_step": 0.01,
               "tick_size": 0.01, "tick_value": 1.00},
    "EURUSD": {"digits": 5, "point": 0.00001, "spread": 7,
               "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01,
               "tick_size": 0.00001, "tick_value": 1.00},
    "GBPUSD": {"digits": 5, "point": 0.00001, "spread": 10,
               "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01,
               "tick_size": 0.00001, "tick_value": 1.00},
}

# ── Symbols for ORB strategies ────────────────────────────────────────────────
_ORB_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"]


# ═══════════════════════════════════════════════════════════════════════════════
# Data generation
# ═══════════════════════════════════════════════════════════════════════════════

def _synthetic_bars(symbol: str, n_days: int = 70) -> Dict[int, List[Dict]]:
    base = {"XAUUSD": 3200.0, "EURUSD": 1.085, "GBPUSD": 1.27}.get(symbol, 1000.0)
    rng = random.Random(hash(symbol + "p8") & 0xFFFFFFFF)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days + 5)

    bars_m15: List[Dict] = []
    bars_h1:  List[Dict] = []
    bars_m5:  List[Dict] = []
    p = base

    t = start.replace(minute=0)
    while t < now:
        if t.weekday() >= 5:
            t += timedelta(hours=1)
            continue
        h = t.hour
        o = p + rng.gauss(0, base * 0.0003)
        rng_size = base * rng.uniform(0.0005, 0.0015)
        h_hi = o + rng_size * rng.uniform(0.3, 1.0)
        h_lo = o - rng_size * rng.uniform(0.3, 1.0)
        if 7 <= h <= 16:
            mult = rng.uniform(1.2, 2.5)
            h_hi = o + (h_hi - o) * mult
            h_lo = o - (o - h_lo) * mult
        c = rng.uniform(h_lo, h_hi)
        vol = rng.randint(300, 3000)
        if 7 <= h <= 16:
            vol = int(vol * rng.uniform(1.5, 3.0))

        bars_h1.append({
            "time": t, "open": round(o, 5), "high": round(h_hi, 5),
            "low": round(h_lo, 5), "close": round(c, 5),
            "tick_volume": vol, "spread": 10, "real_volume": 0,
        })

        sp_h = o
        for i in range(4):
            t_m15 = t + timedelta(minutes=15 * i)
            ep = c if i == 3 else rng.uniform(h_lo, h_hi)
            m15_hi = max(sp_h, ep) + rng.uniform(0, rng_size * 0.4)
            m15_lo = min(sp_h, ep) - rng.uniform(0, rng_size * 0.4)
            bars_m15.append({
                "time": t_m15, "open": round(sp_h, 5), "high": round(m15_hi, 5),
                "low": round(m15_lo, 5), "close": round(ep, 5),
                "tick_volume": vol // 4, "spread": 10, "real_volume": 0,
            })
            sp_m5 = sp_h
            for j in range(3):
                t_m5 = t_m15 + timedelta(minutes=5 * j)
                ep_m5 = ep if j == 2 else rng.uniform(m15_lo, m15_hi)
                bars_m5.append({
                    "time": t_m5, "open": round(sp_m5, 5),
                    "high": round(max(sp_m5, ep_m5) + rng.uniform(0, rng_size * 0.2), 5),
                    "low":  round(min(sp_m5, ep_m5) - rng.uniform(0, rng_size * 0.2), 5),
                    "close": round(ep_m5, 5),
                    "tick_volume": vol // 12, "spread": 10, "real_volume": 0,
                })
                sp_m5 = ep_m5
            sp_h = ep
        p = c
        t += timedelta(hours=1)

    return {TF_H1: bars_h1, TF_M15: bars_m15, TF_M5: bars_m5}


# ═══════════════════════════════════════════════════════════════════════════════
# Replay helpers
# ═══════════════════════════════════════════════════════════════════════════════

class _SimTrade:
    __slots__ = (
        "ts", "symbol", "direction", "strategy",
        "entry", "sl", "tp1", "tp3",
        "volume", "risk_usd",
        "pnl", "r_multiple", "close_reason",
    )
    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))


def _simulate_exit(
    direction: str, entry: float, sl: float, tp1: float,
    bars: List[Dict], start_idx: int, max_bars: int = 32
) -> Tuple[float, float, str]:
    risk_pts = abs(entry - sl)
    for i in range(start_idx, min(start_idx + max_bars, len(bars))):
        b = bars[i]
        if direction == "LONG":
            if b["low"] <= sl:   return sl,  -1.0, "SL"
            if b["high"] >= tp1: return tp1,  1.0, "TP1"
        else:
            if b["high"] >= sl:  return sl,  -1.0, "SL"
            if b["low"] <= tp1:  return tp1,  1.0, "TP1"
    last = bars[min(start_idx + max_bars - 1, len(bars) - 1)]["close"]
    pts  = (last - entry if direction == "LONG" else entry - last)
    r    = pts / risk_pts if risk_pts > 0 else 0.0
    return last, r, "TIME_STOP"


def _build_context(
    ts: datetime,
    md: "MarketData",
    mic: MicrostructureEngine,
) -> StrategyContext:
    """Build a StrategyContext from live market data at the given step."""
    vol_st = md.volatility   # VolState object
    atr = md.atr(TF_M15) or 1.0
    ms = mic.state()

    ctx = StrategyContext(
        timestamp=ts,
        symbol=getattr(md, "symbol", "XAUUSD"),
        bars_m15=md.bars(TF_M15) or [],
        bars_h1=md.bars(TF_H1) or [],
        bars_m5=md.bars(TF_M5) or [],
        atr=atr,
        atr_m15=md.atr(TF_M15) or atr,
        vwap=md.vwap(),
        vwap_slope=md.vwap_slope(),
        ema50=md.ema50(TF_H1),
        ema200=md.ema200(TF_H1),
        ema50_m15=md.ema50(TF_M15),
        vol_state=vol_st,
    )
    return ctx


def _run_strategy(
    strategy_cls,
    bars_data: Dict[str, Dict],
    symbols: List[str],
    specs: Dict,
    replay_days: int,
    strategy_name: str,
) -> List[_SimTrade]:
    """Run a strategy across all symbols and return trade list."""
    now = datetime.now(timezone.utc)
    replay_start = now - timedelta(days=replay_days)

    msd  = MultiSymbolMarketData(symbols)
    mics = {s: MicrostructureEngine() for s in symbols}

    # Warm up
    warmup_end = replay_start
    for sym in symbols:
        md = msd.get(sym)
        if md is None:
            continue
        for tf in [TF_H1, TF_M15, TF_M5]:
            wb = [b for b in bars_data[sym].get(tf, []) if b["time"] < warmup_end][-300:]
            if wb:
                md.load_bars(tf, wb)

    # Each symbol gets its own strategy instance (stateful: OR tracking)
    strategies = {s: strategy_cls() for s in symbols}

    all_m15: List[Dict] = []
    for sym in symbols:
        for b in bars_data[sym][TF_M15]:
            all_m15.append({"sym": sym, **b})
    all_m15.sort(key=lambda x: x["time"])

    trades: List[_SimTrade] = []
    last_pushed: Dict[str, datetime] = {}
    balance = 10_000.0

    for bar in all_m15:
        t   = bar["time"]
        sym = bar["sym"]
        if t < replay_start:
            continue

        md  = msd.get(sym)
        mic = mics[sym]
        strat = strategies[sym]

        if md is None:
            continue

        if last_pushed.get(sym) != t:
            md.push_bar(TF_M15, bar)
            m15_list = md.bars(TF_M15)
            if m15_list:
                mic.analyse(m15_list, md.atr(TF_M5) or md.atr(TF_M15))
            last_pushed[sym] = t

        ctx = _build_context(t, md, mic)
        strat.on_bar(ctx)
        sig = strat.evaluate(ctx)

        if not sig or sig.direction == "FLAT":
            continue

        direction = sig.direction
        atr = md.atr(TF_M15) or ctx.atr or 1.0
        sp_d = specs.get(sym, _DEFAULT_SPECS.get(sym, _DEFAULT_SPECS["XAUUSD"]))
        sp_half = sp_d.get("spread", 15) / 200.0
        entry = bar["close"] + sp_half if direction == "LONG" else bar["close"] - sp_half

        # SL/TP using signal's sl_mult and tp_rr
        sl_dist = atr * sig.sl_atr_mult
        sl  = entry - sl_dist if direction == "LONG" else entry + sl_dist
        tp1 = entry + sl_dist * sig.tp_rr if direction == "LONG" else entry - sl_dist * sig.tp_rr
        tp3 = entry + sl_dist * 3.0 if direction == "LONG" else entry - sl_dist * 3.0

        spec_obj = BrokerSpec(
            symbol=sym,
            vol_min=sp_d.get("vol_min", 0.01), vol_max=sp_d.get("vol_max", 50.0),
            vol_step=sp_d.get("vol_step", 0.01),
            tick_size=sp_d.get("tick_size", 0.01), tick_value=sp_d.get("tick_value", 1.0),
            contract_size=sp_d.get("contract_size", 100.0),
        )
        sizing = PositionSizer.size(
            balance=balance, entry=entry, stop_loss=sl,
            spec=spec_obj, risk_pct=settings.risk.risk_per_trade_pct,
            write_csv=False,
        )

        # Find bar index for exit simulation
        m15s = bars_data[sym][TF_M15]
        bar_idx = next((i for i, b in enumerate(m15s) if b["time"] == t), len(m15s) - 1)
        exit_px, r_mult, close_reason = _simulate_exit(
            direction, entry, sl, tp1, m15s, bar_idx + 1, max_bars=30
        )
        pnl = (exit_px - entry if direction == "LONG" else entry - exit_px) \
              * sizing.final_lot * sp_d.get("contract_size", 100.0)
        balance += pnl

        trades.append(_SimTrade(
            ts=t, symbol=sym, direction=direction, strategy=strategy_name,
            entry=entry, sl=sl, tp1=tp1, tp3=tp3,
            volume=sizing.final_lot, risk_usd=sizing.expected_loss,
            pnl=pnl, r_multiple=r_mult, close_reason=close_reason,
        ))

    return trades


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics & Monte Carlo
# ═══════════════════════════════════════════════════════════════════════════════

def _stats(trades: List[_SimTrade]) -> Dict:
    if not trades:
        return dict(n=0, win_rate=0.0, expectancy=0.0, pf=0.0,
                    max_dd=0.0, net_pnl=0.0, sharpe=0.0)
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    win_rate = len(wins) / len(rs) * 100 if rs else 0.0
    expectancy = sum(rs) / len(rs) if rs else 0.0
    gross_win  = sum(t.pnl for t in trades if t.pnl and t.pnl > 0) or 0.0
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl and t.pnl <= 0)) or 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else 0.0
    net_pnl = sum(t.pnl for t in trades if t.pnl) or 0.0

    equity, peak, max_dd = 10_000.0, 10_000.0, 0.0
    for t in trades:
        equity += (t.pnl or 0.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    sharpe = 0.0
    if len(rs) > 1:
        mu = statistics.mean(rs)
        std = statistics.stdev(rs)
        sharpe = mu / std if std > 0 else 0.0

    return dict(n=len(trades), win_rate=round(win_rate, 2),
                expectancy=round(expectancy, 4), pf=round(pf, 3),
                max_dd=round(max_dd, 2), net_pnl=round(net_pnl, 2),
                sharpe=round(sharpe, 3))


def _monte_carlo(
    trades: List[_SimTrade],
    n_sims: int = 1000,
    n_trades: Optional[int] = None,
    initial_balance: float = 10_000.0,
    ruin_threshold: float = 0.20,   # 20% drawdown = ruin
) -> Dict:
    """Monte Carlo simulation: bootstrapped R-multiples."""
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    risk_usd = statistics.mean(
        [t.risk_usd for t in trades if t.risk_usd and t.risk_usd > 0]
    ) if trades else 100.0

    n = n_trades or len(rs)
    if n < 5 or not rs:
        return dict(prob_ruin=100.0, median_final_balance=initial_balance, n_sims=0)

    rng = random.Random(42)
    ruin_count = 0
    finals: List[float] = []

    for _ in range(n_sims):
        eq = initial_balance
        peak = eq
        ruined = False
        sim_trades = rng.choices(rs, k=n)
        for r in sim_trades:
            eq += r * risk_usd
            peak = max(peak, eq)
            dd = (peak - eq) / peak
            if dd >= ruin_threshold:
                ruined = True
                break
        if ruined:
            ruin_count += 1
        finals.append(eq)

    prob_ruin = ruin_count / n_sims * 100
    med_final = statistics.median(finals)
    return dict(
        prob_ruin=round(prob_ruin, 2),
        median_final_balance=round(med_final, 2),
        n_sims=n_sims,
    )


def _certify(stats: Dict, mc: Dict) -> Tuple[str, int, int]:
    criteria = [
        (stats["n"] >= 100,          "n ≥ 100 trades"),
        (stats["expectancy"] >= 0.10, "Expectancy ≥ +0.10 R"),
        (stats["pf"] >= 1.20,         "Profit Factor ≥ 1.20"),
        (stats["max_dd"] < 12.0,      "Max DD < 12%"),
        (mc["prob_ruin"] < 5.0,       "Prob. of Ruin < 5%"),
    ]
    passed = all(p for p, _ in criteria)
    score  = sum(1 for p, _ in criteria if p)
    total  = len(criteria)
    if passed:
        label = f"✅ CERTIFIED ({score}/{total})"
    else:
        label = f"❌ NOT CERTIFIED ({score}/{total})"
    return label, score, total


def _write_csv_trades(trades: List[_SimTrade], path: str) -> None:
    if not trades:
        return
    fields = _SimTrade.__slots__
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow({s: getattr(t, s, "") for s in fields})


def _write_report(
    p4_trades: List[_SimTrade], p8_trades: List[_SimTrade],
    report_path: str,
) -> None:
    p4_s  = _stats(p4_trades)
    p8_s  = _stats(p8_trades)
    p4_mc = _monte_carlo(p4_trades)
    p8_mc = _monte_carlo(p8_trades)
    p4_cert, p4_sc, total = _certify(p4_s, p4_mc)
    p8_cert, p8_sc, _     = _certify(p8_s, p8_mc)

    def _tick(val): return "✅" if val else "❌"

    lines = [
        "# P8 ORB V2 Validation Report",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## P8 vs P4 Walk-Forward Comparison",
        "",
        "P8 is a forensics-guided redesign of P4 Opening Range Breakout.",
        "Key fixes: wider SL (max of OR range vs ATR), dual-TF EMA requirement, ",
        "stricter volume threshold (1.5×), ATR percentile floor (≥40), ",
        "shortened trade window (08:00–11:30 UTC).",
        "",
        "| Metric | P4 (Baseline) | P8 (V2) | Δ |",
        "|:---|:---:|:---:|:---:|",
        f"| **Trades** | {p4_s['n']} | {p8_s['n']} | {p8_s['n'] - p4_s['n']:+d} |",
        f"| **Win Rate** | {p4_s['win_rate']}% | {p8_s['win_rate']}% | {p8_s['win_rate'] - p4_s['win_rate']:+.2f}% |",
        f"| **Expectancy** | {p4_s['expectancy']:+.4f}R | {p8_s['expectancy']:+.4f}R | {p8_s['expectancy'] - p4_s['expectancy']:+.4f}R |",
        f"| **Profit Factor** | {p4_s['pf']:.3f} | {p8_s['pf']:.3f} | {p8_s['pf'] - p4_s['pf']:+.3f} |",
        f"| **Max DD** | {p4_s['max_dd']:.2f}% | {p8_s['max_dd']:.2f}% | {p8_s['max_dd'] - p4_s['max_dd']:+.2f}% |",
        f"| **Net PnL** | ${p4_s['net_pnl']:+,.2f} | ${p8_s['net_pnl']:+,.2f} | ${p8_s['net_pnl'] - p4_s['net_pnl']:+,.2f} |",
        f"| **Sharpe** | {p4_s['sharpe']:.3f} | {p8_s['sharpe']:.3f} | {p8_s['sharpe'] - p4_s['sharpe']:+.3f} |",
        f"| **Prob. of Ruin** | {p4_mc['prob_ruin']:.2f}% | {p8_mc['prob_ruin']:.2f}% | {p8_mc['prob_ruin'] - p4_mc['prob_ruin']:+.2f}% |",
        "",
        "---",
        "",
        "## Certification Scorecard",
        "",
        "| Requirement | Threshold | P4 | P8 |",
        "|:---|:---|:---:|:---:|",
        f"| **Expectancy** | ≥ +0.10 R | {p4_s['expectancy']:+.4f}R {_tick(p4_s['expectancy'] >= 0.10)} | {p8_s['expectancy']:+.4f}R {_tick(p8_s['expectancy'] >= 0.10)} |",
        f"| **Profit Factor** | ≥ 1.20 | {p4_s['pf']:.3f} {_tick(p4_s['pf'] >= 1.20)} | {p8_s['pf']:.3f} {_tick(p8_s['pf'] >= 1.20)} |",
        f"| **Max Drawdown** | < 12% | {p4_s['max_dd']:.2f}% {_tick(p4_s['max_dd'] < 12.0)} | {p8_s['max_dd']:.2f}% {_tick(p8_s['max_dd'] < 12.0)} |",
        f"| **Sample Size** | ≥ 100 | {p4_s['n']} {_tick(p4_s['n'] >= 100)} | {p8_s['n']} {_tick(p8_s['n'] >= 100)} |",
        f"| **Prob. of Ruin** | < 5% | {p4_mc['prob_ruin']:.2f}% {_tick(p4_mc['prob_ruin'] < 5.0)} | {p8_mc['prob_ruin']:.2f}% {_tick(p8_mc['prob_ruin'] < 5.0)} |",
        "",
        f"**P4 Decision**: {p4_cert}",
        f"**P8 Decision**: {p8_cert}",
        "",
        "---",
        "",
        "## Monte Carlo Detail",
        "",
        f"| Parameter | P4 | P8 |",
        f"|:---|:---:|:---:|",
        f"| Simulations | {p4_mc['n_sims']} | {p8_mc['n_sims']} |",
        f"| Prob. of Ruin (20% DD) | {p4_mc['prob_ruin']:.2f}% | {p8_mc['prob_ruin']:.2f}% |",
        f"| Median Final Balance | ${p4_mc['median_final_balance']:,.2f} | ${p8_mc['median_final_balance']:,.2f} |",
        "",
        "---",
        "",
        "## P8 Design Changes from P4",
        "",
        "| Attribute | P4 | P8 | Rationale |",
        "|:---|:---|:---|:---|",
        "| SL distance | 0.3× ATR | max(OR range, 1.0× ATR) | P4's SL inside intraday noise |",
        "| Volume threshold | 1.2× avg | 1.5× avg | Too many weak-move entries |",
        "| EMA requirement | H1 only | H1 AND M15 | P4 took counter-trend trades |",
        "| ATR percentile | None | ≥ 40 | V3 finding: low-ATR traps |",
        "| OR range filter | ≥ 0.2× ATR | ≥ 1.5× ATR | Old filter was trivially easy |",
        "| Trade window end | 13:00 UTC | 11:30 UTC | Late signals had poor fills |",
        "",
        "---",
        "",
        "## Files",
        "- `reports/p8_trades.csv` — P8 per-trade log",
        "- `reports/p4_trades.csv` — P4 baseline per-trade log",
        "- `reports/p8_validation.log` — full validation log",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Report saved: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    logger.info("=" * 60)
    logger.info("P8 ORB V2 vs P4 Validation")
    logger.info("=" * 60)

    symbols = [s for s in _ORB_SYMBOLS if s in _DEFAULT_SPECS]
    replay_days = int(os.getenv("REPLAY_DAYS", "60"))
    logger.info(f"Symbols: {symbols} | Replay: {replay_days} days")

    specs: Dict[str, Dict] = {}
    bars_data: Dict[str, Dict] = {}

    if OFFLINE_MODE:
        logger.info("OFFLINE MODE — synthetic bars")
        for sym in symbols:
            bars_data[sym] = _synthetic_bars(sym, n_days=replay_days + 10)
            specs[sym] = _DEFAULT_SPECS[sym]
    else:
        try:
            import MetaTrader5 as mt5
            kw = {
                "login": settings.mt5.login, "password": settings.mt5.password,
                "server": settings.mt5.server, "timeout": settings.mt5.timeout_ms,
            }
            if settings.mt5.path:
                kw["path"] = settings.mt5.path
            if not mt5.initialize(**kw):
                raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
            logger.info("MT5 connected")

            now = datetime.now(timezone.utc)
            start = now - timedelta(days=replay_days + 30)

            for sym in symbols:
                broker = sym
                for v in [sym, sym + "m", sym + ".a", sym + "+"]:
                    info = mt5.symbol_info(v)
                    if info and info.trade_mode != 0:
                        mt5.symbol_select(v, True)
                        broker = v
                        break

                info = mt5.symbol_info(broker)
                specs[sym] = {
                    "digits": info.digits, "point": info.point, "spread": info.spread,
                    "contract_size": info.trade_contract_size,
                    "vol_min": info.volume_min, "vol_max": info.volume_max,
                    "vol_step": info.volume_step,
                    "tick_size": info.point, "tick_value": 1.0,
                } if info else _DEFAULT_SPECS.get(sym, _DEFAULT_SPECS["XAUUSD"])

                bars_data[sym] = {}
                for tf, mt5_tf, label in [
                    (TF_H1, mt5.TIMEFRAME_H1, "H1"),
                    (TF_M15, mt5.TIMEFRAME_M15, "M15"),
                    (TF_M5, mt5.TIMEFRAME_M5, "M5"),
                ]:
                    rates = mt5.copy_rates_range(broker, mt5_tf, start, now)
                    if rates is not None and len(rates) > 0:
                        bars_data[sym][tf] = [
                            {"time": datetime.fromtimestamp(r["time"], tz=timezone.utc),
                             "open": float(r["open"]), "high": float(r["high"]),
                             "low": float(r["low"]), "close": float(r["close"]),
                             "tick_volume": int(r["tick_volume"]),
                             "spread": int(r["spread"]), "real_volume": 0}
                            for r in rates
                        ]
                        logger.info(f"  {sym} {label}: {len(bars_data[sym][tf])} bars")
                    else:
                        logger.warning(f"  {sym} {label}: no data — synthetic fallback")
                        bars_data[sym][tf] = _synthetic_bars(sym, n_days=replay_days + 10)[tf]

        except (ImportError, RuntimeError) as e:
            logger.warning(f"MT5 unavailable ({e}) — switching to offline")
            for sym in symbols:
                bars_data[sym] = _synthetic_bars(sym, n_days=replay_days + 10)
                specs[sym] = _DEFAULT_SPECS[sym]

    logger.info("Running P4 strategy...")
    p4_trades = _run_strategy(OpeningRangeBreakoutStrategy, bars_data, symbols,
                              specs, replay_days, "P4")
    logger.info(f"  P4: {len(p4_trades)} trades")

    logger.info("Running P8 strategy...")
    p8_trades = _run_strategy(OpeningRangeBreakoutV2Strategy, bars_data, symbols,
                              specs, replay_days, "P8")
    logger.info(f"  P8: {len(p8_trades)} trades")

    p4_s = _stats(p4_trades)
    p8_s = _stats(p8_trades)
    logger.info(
        f"P4 | n={p4_s['n']} WR={p4_s['win_rate']}% E={p4_s['expectancy']:+.4f}R "
        f"PF={p4_s['pf']:.3f} DD={p4_s['max_dd']:.2f}%"
    )
    logger.info(
        f"P8 | n={p8_s['n']} WR={p8_s['win_rate']}% E={p8_s['expectancy']:+.4f}R "
        f"PF={p8_s['pf']:.3f} DD={p8_s['max_dd']:.2f}%"
    )

    _write_csv_trades(p4_trades, "reports/p4_trades.csv")
    _write_csv_trades(p8_trades, "reports/p8_trades.csv")
    _write_report(p4_trades, p8_trades, "reports/p8_validation_report.md")

    logger.info("=" * 60)
    logger.info("P8 validation complete — see reports/p8_validation_report.md")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
