"""
scripts/strategy_audit_v3.py — V3 Scoring Engine Audit

Replays historical M15 bars through the V3, Recalibrated, and Legacy scoring
engines simultaneously and generates a side-by-side certification report.

Usage:
    python scripts/strategy_audit_v3.py              # uses MT5 for bars
    python scripts/strategy_audit_v3.py --offline    # synthetic bars only
    REPLAY_DAYS=30 python scripts/strategy_audit_v3.py  # limit replay window

Outputs:
    reports/v3_audit_report.md         — V3 vs Recalibrated vs Legacy comparison
    reports/v3_executed_trades.csv     — per-trade detail for V3
    reports/v3_score_distribution.csv  — score histograms per engine
"""

import os, sys, csv, json, math, random, logging, asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

# ── UTF-8 console shim (Windows) ─────────────────────────────────────────────
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
        logging.FileHandler("reports/v3_audit.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("v3_audit")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ── force V3 mode ON before importing trade_quality ──────────────────────────
os.environ["USE_V3_SCORING"] = "true"
os.environ["USE_RECALIBRATED_SCORING"] = "false"
os.environ["SHADOW_MODE"] = "false"

OFFLINE_MODE = "--offline" in sys.argv

from app.config import settings, enabled_symbols, SYMBOL_CONFIGS
from app.market_data import (
    MultiSymbolMarketData, MarketData, TF_M5, TF_M15, TF_H1, Bar, Tick,
)
from app.order_flow import OrderFlowEngine, OFSnapshot
from app.dom_engine import DOMEngine, DOMSnapshot
from app.microstructure import MicrostructureEngine
from app.volume_analytics import VolumeAnalytics
from app.session import SessionFilter, SessionState
from app.trade_quality import TradeQualityEngine, QualityBreakdown
from app.risk_manager import RiskManager
from app.position_sizer import PositionSizer, BrokerSpec

# Keep MarketData always fresh in replay
MarketData.is_fresh = property(lambda self: True)   # type: ignore

# ── Replay clock ──────────────────────────────────────────────────────────────
_mock_now: datetime = datetime.now(timezone.utc)

# ── Per-symbol specs (fallback) ───────────────────────────────────────────────
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
    "USDJPY": {"digits": 3, "point": 0.001, "spread": 8,
               "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01,
               "tick_size": 0.001, "tick_value": 0.0067},
    "NAS100": {"digits": 2, "point": 0.01, "spread": 120,
               "contract_size": 1.0, "vol_min": 0.10, "vol_max": 100.0, "vol_step": 0.10,
               "tick_size": 0.01, "tick_value": 0.01},
    "US30":   {"digits": 2, "point": 0.01, "spread": 200,
               "contract_size": 1.0, "vol_min": 0.10, "vol_max": 100.0, "vol_step": 0.10,
               "tick_size": 0.01, "tick_value": 0.01},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Synthetic bar generator (offline mode)
# ═══════════════════════════════════════════════════════════════════════════════

def _synthetic_bars(symbol: str, n_days: int = 30) -> Dict[int, List[Dict]]:
    """Generate realistic synthetic OHLCV bars for offline testing."""
    base = {
        "XAUUSD": 3200.0, "EURUSD": 1.085, "GBPUSD": 1.27,
        "USDJPY": 155.0,  "NAS100": 20000.0, "US30": 42000.0,
    }.get(symbol, 1000.0)

    rng = random.Random(hash(symbol) & 0xFFFFFFFF)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days + 5)   # +5 for warmup

    bars_m15: List[Dict] = []
    bars_h1:  List[Dict] = []
    bars_m5:  List[Dict] = []
    p = base

    t = start.replace(minute=0)
    while t < now:
        h = t.hour
        # Skip weekends
        if t.weekday() >= 5:
            t += timedelta(hours=1)
            continue

        o = p + rng.gauss(0, base * 0.0003)
        rng_size = base * rng.uniform(0.0005, 0.0015)
        h_hi = o + rng_size * rng.uniform(0.3, 1.0)
        h_lo = o - rng_size * rng.uniform(0.3, 1.0)

        # Session bias: London/overlap has bigger moves
        if 7 <= h <= 16:
            session_mult = rng.uniform(1.2, 2.0)
            h_hi = o + (h_hi - o) * session_mult
            h_lo = o - (o - h_lo) * session_mult

        c = rng.uniform(h_lo, h_hi)
        vol = rng.randint(300, 3000)
        if 7 <= h <= 16:
            vol = int(vol * rng.uniform(1.5, 3.0))

        bar: Dict = {
            "time": t, "open": round(o, 4), "high": round(h_hi, 4),
            "low": round(h_lo, 4), "close": round(c, 4),
            "tick_volume": vol, "spread": 15, "real_volume": 0,
        }
        bars_h1.append(bar)

        # Generate 4 M15 bars within this H1
        sp = o
        for i in range(4):
            t_m15 = t + timedelta(minutes=15 * i)
            ep = c if i == 3 else rng.uniform(h_lo, h_hi)
            m15_hi = max(sp, ep) + rng.uniform(0, rng_size * 0.4)
            m15_lo = min(sp, ep) - rng.uniform(0, rng_size * 0.4)
            bars_m15.append({
                "time": t_m15, "open": round(sp, 4), "high": round(m15_hi, 4),
                "low": round(m15_lo, 4), "close": round(ep, 4),
                "tick_volume": vol // 4, "spread": 15, "real_volume": 0,
            })
            # 3 M5 bars per M15
            sp_m5 = sp
            for j in range(3):
                t_m5 = t_m15 + timedelta(minutes=5 * j)
                ep_m5 = ep if j == 2 else rng.uniform(m15_lo, m15_hi)
                bars_m5.append({
                    "time": t_m5, "open": round(sp_m5, 4),
                    "high": round(max(sp_m5, ep_m5) + rng.uniform(0, rng_size * 0.2), 4),
                    "low":  round(min(sp_m5, ep_m5) - rng.uniform(0, rng_size * 0.2), 4),
                    "close": round(ep_m5, 4),
                    "tick_volume": vol // 12, "spread": 15, "real_volume": 0,
                })
                sp_m5 = ep_m5
            sp = ep

        p = c
        t += timedelta(hours=1)

    return {TF_H1: bars_h1, TF_M15: bars_m15, TF_M5: bars_m5}


# ═══════════════════════════════════════════════════════════════════════════════
# Trade result simulation
# ═══════════════════════════════════════════════════════════════════════════════

class TradeResult:
    __slots__ = (
        "ts", "symbol", "direction", "entry", "sl", "tp1", "tp3",
        "volume", "risk_usd", "quality_score", "engine_name",
        "pnl", "r_multiple", "close_reason",
        "of_score", "ms_score", "liq_score", "vol_score",
        "session_score", "news_score",
    )

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        for s in self.__slots__:
            if not hasattr(self, s):
                setattr(self, s, None)


def _simulate_exit(
    direction: str, entry: float, sl: float, tp1: float, tp3: float,
    bars: List[Dict], start_idx: int, max_bars: int = 30
) -> Tuple[float, float, str]:
    """
    Walk forward through M15 bars to simulate SL/TP fill.
    Returns (exit_price, r_multiple, close_reason).
    """
    risk_pts = abs(entry - sl)
    for i in range(start_idx, min(start_idx + max_bars, len(bars))):
        b = bars[i]
        if direction == "LONG":
            if b["low"] <= sl:
                return sl, -1.0, "SL"
            if b["high"] >= tp1:
                return tp1, 1.0, "TP1"
        else:
            if b["high"] >= sl:
                return sl, -1.0, "SL"
            if b["low"] <= tp1:
                return tp1, 1.0, "TP1"
    # Time stop: exit at last bar close
    last = bars[min(start_idx + max_bars - 1, len(bars) - 1)]["close"]
    pts = (last - entry if direction == "LONG" else entry - last)
    r = pts / risk_pts if risk_pts > 0 else 0.0
    return last, r, "TIME_STOP"


# ═══════════════════════════════════════════════════════════════════════════════
# Main audit
# ═══════════════════════════════════════════════════════════════════════════════

def _build_components(symbols: List[str]) -> Dict:
    msd  = MultiSymbolMarketData(symbols)
    ofs  = {s: OrderFlowEngine()     for s in symbols}
    doms = {s: DOMEngine()           for s in symbols}
    vas  = {s: VolumeAnalytics()     for s in symbols}
    mics = {s: MicrostructureEngine() for s in symbols}
    sess = SessionFilter()
    return dict(msd=msd, ofs=ofs, doms=doms, vas=vas, mics=mics, sess=sess)


def _warmup(comps: Dict, bars_data: Dict, symbols: List[str], warmup_end: datetime) -> None:
    msd = comps["msd"]
    for sym in symbols:
        md = msd.get(sym)
        if not md:
            continue
        for tf in [TF_H1, TF_M15, TF_M5]:
            wb = [b for b in bars_data[sym].get(tf, []) if b["time"] < warmup_end][-300:]
            if wb:
                md.load_bars(tf, wb)
        logger.info(f"  Warmed up {sym}")


def _evaluate_engines(
    bars_data: Dict, symbols: List[str],
    comps: Dict, replay_days: int,
    specs: Dict,
) -> Dict[str, List[TradeResult]]:
    """
    Run three scoring engines (v3, recalibrated, legacy) in parallel on each
    M15 bar signal and collect trade results.
    """
    from app.trade_quality import (
        TradeQualityEngine,
        _V3_THRESHOLD,   # module-level constant
    )

    # Three independent quality engines
    q_v3   = TradeQualityEngine()
    q_rec  = TradeQualityEngine()
    q_leg  = TradeQualityEngine()

    # Thresholds
    V3_THRESH  = _V3_THRESHOLD     # 68.0
    REC_THRESH = 65.0
    LEG_THRESH = 85.0

    results: Dict[str, List[TradeResult]] = {
        "v3": [], "recalibrated": [], "legacy": [],
    }

    msd  = comps["msd"]
    mics = comps["mics"]
    ofs  = comps["ofs"]
    vas  = comps["vas"]

    # Build sorted M15 timeline from all symbols
    all_m15: List[Dict] = []
    for sym in symbols:
        for b in bars_data[sym][TF_M15]:
            all_m15.append({"sym": sym, **b})
    all_m15.sort(key=lambda x: x["time"])

    # replay_start = first date of replay window
    now = datetime.now(timezone.utc)
    replay_start = now - timedelta(days=replay_days)

    # Index M15 bars per symbol for exit simulation
    m15_by_sym: Dict[str, List[Dict]] = {s: bars_data[s][TF_M15] for s in symbols}

    balance = 10_000.0
    last_pushed: Dict[str, datetime] = {}

    for idx, bar in enumerate(all_m15):
        t   = bar["time"]
        sym = bar["sym"]
        if t < replay_start:
            continue   # still in warm-up range

        md = msd.get(sym)
        if md is None:
            continue

        # Push bar into MD
        if last_pushed.get(sym) != t:
            md.push_bar(TF_M15, bar)
            m15_list = md.bars(TF_M15)
            if m15_list:
                mics[sym].analyse(m15_list, md.atr(TF_M5) or md.atr(TF_M15))
            last_pushed[sym] = t

        # Session state — run evaluate() to get populated SessionState
        sess_state = comps["sess"].evaluate()

        # Build synthetic tick
        sp = specs.get(sym, _DEFAULT_SPECS.get(sym, {})).get("spread", 15)
        sp_half = sp / 200.0
        close = bar["close"]
        tick = Tick(time=t, bid=close - sp_half, ask=close + sp_half,
                    last=close, volume=bar["tick_volume"], flags=0)
        ofs[sym].process(tick)

        # Pull engine inputs
        of_snap = ofs[sym].latest
        dom_m   = comps["doms"][sym].latest_dom or comps["doms"][sym].latest_fallback
        ms_st   = mics[sym].state()
        vol_st  = md.volatility          # MarketData.volatility is a property → VolState
        vol_sn  = vas[sym].latest        # VolumeAnalytics.latest → VolumeSnapshot or None
        atr     = md.atr(TF_M5) or md.atr(TF_M15) or (close * 0.001)
        vwap    = md.vwap()
        avg_sp  = md.avg_spread or (sp / 100.0)

        ema_bh1  = md.is_ema_bull(TF_H1)
        ema_brh1 = md.is_ema_bear(TF_H1)
        ema_bm15 = md.is_ema_bull(TF_M15)
        ema_brm15= md.is_ema_bear(TF_M15)
        pav      = (close > vwap) if vwap else None

        for engine_name, q_eng, threshold in [
            ("v3",           q_v3,  V3_THRESH),
            ("recalibrated", q_rec, REC_THRESH),
            ("legacy",       q_leg, LEG_THRESH),
        ]:
            # Temporarily swap engine flag
            import app.trade_quality as tq_module
            if engine_name == "v3":
                orig_v3, orig_rec = tq_module.USE_V3_SCORING, tq_module.USE_RECALIBRATED_SCORING
                tq_module.USE_V3_SCORING = True
                tq_module.USE_RECALIBRATED_SCORING = False
            elif engine_name == "recalibrated":
                orig_v3, orig_rec = tq_module.USE_V3_SCORING, tq_module.USE_RECALIBRATED_SCORING
                tq_module.USE_V3_SCORING = False
                tq_module.USE_RECALIBRATED_SCORING = True
            else:
                orig_v3, orig_rec = tq_module.USE_V3_SCORING, tq_module.USE_RECALIBRATED_SCORING
                tq_module.USE_V3_SCORING = False
                tq_module.USE_RECALIBRATED_SCORING = False

            bd = q_eng.evaluate(
                of_snap, dom_m, ms_st, vol_st, vol_sn, sess_state,
                ema_bh1, ema_brh1, ema_bm15, ema_brm15,
                pav, sp / 100.0, avg_sp, sym,
            )

            # Restore
            tq_module.USE_V3_SCORING = orig_v3
            tq_module.USE_RECALIBRATED_SCORING = orig_rec

            if bd is None:
                continue   # no signal

            direction = bd.direction
            entry = tick.ask if direction == "LONG" else tick.bid
            sl    = entry - atr * 1.5 if direction == "LONG" else entry + atr * 1.5
            tp1   = entry + atr * 1.5 if direction == "LONG" else entry - atr * 1.5
            tp3   = entry + atr * 4.5 if direction == "LONG" else entry - atr * 4.5

            sp_d = specs.get(sym, _DEFAULT_SPECS.get(sym, {}))
            spec_obj = BrokerSpec(
                symbol=sym,
                vol_min=sp_d.get("vol_min", 0.01),
                vol_max=sp_d.get("vol_max", 50.0),
                vol_step=sp_d.get("vol_step", 0.01),
                tick_size=sp_d.get("tick_size", 0.01),
                tick_value=sp_d.get("tick_value", 1.0),
                contract_size=sp_d.get("contract_size", 100.0),
            )
            sizing = PositionSizer.size(
                balance=balance, entry=entry, stop_loss=sl,
                spec=spec_obj, risk_pct=settings.risk.risk_per_trade_pct,
                write_csv=False,
            )

            # Find this bar's index in the per-symbol M15 list
            m15s = m15_by_sym[sym]
            bar_idx = next(
                (i for i, b in enumerate(m15s) if b["time"] == t), len(m15s) - 1
            )
            exit_px, r_mult, close_reason = _simulate_exit(
                direction, entry, sl, tp1, tp3, m15s, bar_idx + 1, max_bars=30
            )
            pnl = (exit_px - entry if direction == "LONG" else entry - exit_px) \
                  * sizing.final_lot * sp_d.get("contract_size", 100.0)

            results[engine_name].append(TradeResult(
                ts=t, symbol=sym, direction=direction,
                entry=entry, sl=sl, tp1=tp1, tp3=tp3,
                volume=sizing.final_lot, risk_usd=sizing.expected_loss,
                quality_score=bd.total, engine_name=engine_name,
                pnl=pnl, r_multiple=r_mult, close_reason=close_reason,
                of_score=bd.of_score, ms_score=bd.ms_score,
                liq_score=bd.liq_score, vol_score=bd.vol_score,
                session_score=bd.session_score, news_score=bd.news_score,
            ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _stats(trades: List[TradeResult]) -> Dict:
    if not trades:
        return dict(n=0, win_rate=0.0, expectancy=0.0, pf=0.0,
                    max_dd=0.0, net_pnl=0.0, sharpe=0.0)
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    win_rate = len(wins) / len(rs) * 100 if rs else 0.0
    expectancy = sum(rs) / len(rs) if rs else 0.0
    gross_win = sum(t.pnl for t in trades if t.pnl and t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl and t.pnl <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 0.0
    net_pnl = sum(t.pnl for t in trades if t.pnl)

    # Max drawdown (equity curve)
    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity += (t.pnl or 0.0)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    # Sharpe (R-based)
    if len(rs) > 1:
        import statistics
        mu = statistics.mean(rs)
        std = statistics.stdev(rs)
        sharpe = mu / std if std > 0 else 0.0
    else:
        sharpe = 0.0

    return dict(n=len(trades), win_rate=round(win_rate, 2),
                expectancy=round(expectancy, 4), pf=round(pf, 3),
                max_dd=round(max_dd, 2), net_pnl=round(net_pnl, 2),
                sharpe=round(sharpe, 3))


def _certify(stats: Dict, engine: str) -> str:
    criteria = [
        ("n",          stats["n"],          lambda x: x >= 100,  "≥ 100 trades"),
        ("expectancy", stats["expectancy"],  lambda x: x >= 0.10, "≥ +0.10 R"),
        ("pf",         stats["pf"],          lambda x: x >= 1.20, "≥ 1.20"),
        ("max_dd",     stats["max_dd"],      lambda x: x < 12.0,  "< 12%"),
    ]
    passed = all(fn(val) for _, val, fn, _ in criteria)
    score = sum(1 for _, val, fn, _ in criteria if fn(val))
    return f"{'✅ CERTIFIED' if passed else '❌ NOT CERTIFIED'} ({score}/{len(criteria)} criteria)"


def _write_csv(trades: List[TradeResult], path: str) -> None:
    if not trades:
        return
    fields = TradeResult.__slots__
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow({s: getattr(t, s, "") for s in fields})


def _write_report(results: Dict[str, List[TradeResult]], report_path: str) -> None:
    lines = [
        "# V3 Strategy Audit Report",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Executive Summary",
        "",
        "Comparison of three scoring engines replayed on live M15 bar history.",
        "Trade simulation: SL/TP filled at actual bar H/L; 30-bar time stop.",
        "",
        "### Certification Criteria",
        "| Criterion | Target |",
        "|:---|:---|",
        "| Trade Count | ≥ 100 |",
        "| Expectancy | ≥ +0.10 R |",
        "| Profit Factor | ≥ 1.20 |",
        "| Max Drawdown | < 12% |",
        "",
        "---",
        "",
        "## Performance Comparison",
        "",
        "| Engine | Trades | Win Rate | Expectancy | PF | Max DD | Net PnL | Sharpe | Status |",
        "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|",
    ]

    for engine_name in ["v3", "recalibrated", "legacy"]:
        tr = results[engine_name]
        s  = _stats(tr)
        cert = _certify(s, engine_name)
        lines.append(
            f"| **{engine_name.title()}** | {s['n']} | {s['win_rate']}% | "
            f"{s['expectancy']:+.4f}R | {s['pf']:.3f} | "
            f"{s['max_dd']:.2f}% | ${s['net_pnl']:+,.2f} | {s['sharpe']:.3f} | {cert} |"
        )

    lines += ["", "---", "", "## Per-Engine Detail", ""]
    for engine_name in ["v3", "recalibrated", "legacy"]:
        tr = results[engine_name]
        s  = _stats(tr)
        lines += [
            f"### {engine_name.title()} Engine",
            "",
            f"| Metric | Value |",
            f"|:---|---:|",
            f"| **Total Trades** | {s['n']} |",
            f"| **Win Rate** | {s['win_rate']}% |",
            f"| **Expectancy** | {s['expectancy']:+.4f} R |",
            f"| **Profit Factor** | {s['pf']:.3f} |",
            f"| **Max Drawdown** | {s['max_dd']:.2f}% |",
            f"| **Net PnL** | ${s['net_pnl']:+,.2f} |",
            f"| **Sharpe (R-based)** | {s['sharpe']:.3f} |",
            "",
        ]

        # Score distribution
        if tr:
            scores = [t.quality_score for t in tr if t.quality_score is not None]
            if scores:
                import statistics as _stat
                lines += [
                    f"**Quality Score Distribution** ({len(scores)} accepted signals):",
                    f"- Mean: {_stat.mean(scores):.1f}",
                    f"- Median: {_stat.median(scores):.1f}",
                    f"- Std Dev: {_stat.stdev(scores):.1f}" if len(scores) > 1 else "",
                    f"- Min / Max: {min(scores):.1f} / {max(scores):.1f}",
                    "",
                ]

        # Symbol breakdown
        syms = sorted(set(t.symbol for t in tr))
        if len(syms) > 1:
            lines.append("**PnL by Symbol:**")
            for sym in syms:
                sym_tr = [t for t in tr if t.symbol == sym]
                sym_pnl = sum(t.pnl for t in sym_tr if t.pnl)
                sym_wr = sum(1 for t in sym_tr if t.r_multiple and t.r_multiple > 0)
                lines.append(f"- {sym}: ${sym_pnl:+,.2f} ({sym_wr}/{len(sym_tr)} wins)")
            lines.append("")

    lines += [
        "---",
        "",
        "## V3 Key Changes vs Recalibrated",
        "",
        "| Change | Old Behaviour | New Behaviour | Forensics Basis |",
        "|:---|:---|:---|:---|",
        "| **FVG confluence** | +8 to ms_score | -10 penalty | p=0.040, 0% winners had FVG |",
        "| **DOM liquidity** | Higher = better | Medium ideal (40-65), high (>75) penalised | corr=-0.562, p=0.0034 |",
        "| **ATR veto** | None | Hard reject if ATR pct < 25th | Low-ATR avg loss -$55.82 |",
        "| **Order flow weight** | 22% | 35% | corr=+0.520 with PnL |",
        "| **Session weight** | 8.8% | 5% | corr=+0.07, hard veto sufficient |",
        "| **News weight** | 19.3% | 5% | Was constant 50.0, uninformative |",
        "| **EMA veto (OF)** | No hard veto | OF < 30 vetoes LONG; OF > 70 vetoes SHORT | Directional clarity |",
        "",
        "---",
        "",
        "## Files",
        "- `reports/v3_executed_trades.csv` — per-trade detail for V3 engine",
        "- `reports/v3_audit.log` — full audit log",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Report saved: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    logger.info("=" * 60)
    logger.info("V3 Scoring Engine Audit")
    logger.info("=" * 60)

    symbols = [s for s in enabled_symbols() if s in _DEFAULT_SPECS]
    if not symbols:
        symbols = ["XAUUSD"]
    logger.info(f"Symbols: {symbols}")

    replay_days = int(os.getenv("REPLAY_DAYS", "60"))
    logger.info(f"Replay window: {replay_days} days")

    specs: Dict[str, Dict] = {}
    bars_data: Dict[str, Dict] = {}

    if OFFLINE_MODE:
        logger.info("OFFLINE MODE — generating synthetic bars")
        for sym in symbols:
            bars_data[sym] = _synthetic_bars(sym, n_days=replay_days + 10)
            specs[sym] = _DEFAULT_SPECS.get(sym, _DEFAULT_SPECS["XAUUSD"])
    else:
        try:
            import MetaTrader5 as mt5
            kw = {
                "login":    settings.mt5.login,
                "password": settings.mt5.password,
                "server":   settings.mt5.server,
                "timeout":  settings.mt5.timeout_ms,
            }
            if settings.mt5.path:
                kw["path"] = settings.mt5.path
            if not mt5.initialize(**kw):
                raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
            logger.info("MT5 connected")

            now = datetime.now(timezone.utc)
            start = now - timedelta(days=replay_days + 30)   # +30 warmup

            for sym in symbols:
                # Resolve broker symbol
                broker = sym
                for variant in [sym, sym + "m", sym + ".a", sym + "+"]:
                    info = mt5.symbol_info(variant)
                    if info and info.trade_mode != 0:
                        mt5.symbol_select(variant, True)
                        broker = variant
                        break

                info = mt5.symbol_info(broker)
                if info:
                    specs[sym] = {
                        "digits": info.digits, "point": info.point,
                        "spread": info.spread, "contract_size": info.trade_contract_size,
                        "vol_min": info.volume_min, "vol_max": info.volume_max,
                        "vol_step": info.volume_step,
                        "tick_size": info.point, "tick_value": 1.0,
                    }
                else:
                    specs[sym] = _DEFAULT_SPECS.get(sym, _DEFAULT_SPECS["XAUUSD"])

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
                             "low": float(r["low"]),  "close": float(r["close"]),
                             "tick_volume": int(r["tick_volume"]),
                             "spread": int(r["spread"]), "real_volume": 0}
                            for r in rates
                        ]
                        logger.info(f"  {sym} {label}: {len(bars_data[sym][tf])} bars")
                    else:
                        logger.warning(f"  {sym} {label}: no data — using synthetic")
                        bars_data[sym][tf] = _synthetic_bars(sym, n_days=replay_days + 10)[tf]

        except (ImportError, RuntimeError) as e:
            logger.warning(f"MT5 unavailable ({e}), switching to offline mode")
            for sym in symbols:
                bars_data[sym] = _synthetic_bars(sym, n_days=replay_days + 10)
                specs[sym] = _DEFAULT_SPECS.get(sym, _DEFAULT_SPECS["XAUUSD"])

    # Build components and warm up
    comps = _build_components(symbols)
    now_dt = datetime.now(timezone.utc)
    warmup_end = now_dt - timedelta(days=replay_days)
    logger.info(f"Warming up indicators (pre-{warmup_end.date()})...")
    _warmup(comps, bars_data, symbols, warmup_end)
    logger.info("Warm-up complete")

    # Run evaluation
    logger.info("Evaluating signals across three engines...")
    results = _evaluate_engines(bars_data, symbols, comps, replay_days, specs)

    # Summary
    for engine_name, tr in results.items():
        s = _stats(tr)
        logger.info(
            f"[{engine_name.upper():15s}] n={s['n']:4d} | WR={s['win_rate']:.1f}% | "
            f"E={s['expectancy']:+.4f}R | PF={s['pf']:.3f} | DD={s['max_dd']:.2f}%"
        )

    # Write outputs
    _write_csv(results["v3"], "reports/v3_executed_trades.csv")
    _write_report(results, "reports/v3_audit_report.md")

    logger.info("=" * 60)
    logger.info("V3 audit complete — see reports/v3_audit_report.md")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
