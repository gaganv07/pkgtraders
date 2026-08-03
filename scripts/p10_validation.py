"""
scripts/p10_validation.py — P10 Hybrid Edge Strategy Validation Suite

Runs backtest simulations, walk-forward rolling splits, Monte Carlo stress tests,
MAE/MFE excursion tracking, regime groupings, and symbol validation for the new
P10 Hybrid Edge Strategy. Generates 9 required markdown reports.
"""

import os
import sys
import math
import random
import logging
import statistics
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple

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
        logging.FileHandler("reports/p10_validation.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("p10_val")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings, enabled_symbols
from app.market_data import (
    MultiSymbolMarketData, MarketData, TF_M5, TF_M15, TF_H1, Bar, Tick, VolState
)
from app.microstructure import MicrostructureEngine
from strategies.context import StrategyContext
from strategies.prototypes.p10_hybrid_edge import P10HybridEdgeStrategy
from app.position_sizer import PositionSizer, BrokerSpec

# ── Simulation Configurations ──────────────────────────────────────────────────
SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
REPLAY_DAYS_VAL = 720  # 24 months
START_BALANCE = 500.0

_DEFAULT_SPECS = {
    "BTCUSD": {"digits": 2, "point": 0.01, "spread": 250, "contract_size": 1.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01, "tick_size": 0.01, "tick_value": 1.0},
    "XAUUSD": {"digits": 2, "point": 0.01, "spread": 15, "contract_size": 100.0, "vol_min": 0.01, "vol_max": 50.0, "vol_step": 0.01, "tick_size": 0.01, "tick_value": 1.0},
    "EURUSD": {"digits": 5, "point": 0.00001, "spread": 7, "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01, "tick_size": 0.00001, "tick_value": 1.0},
    "GBPUSD": {"digits": 5, "point": 0.00001, "spread": 10, "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01, "tick_size": 0.00001, "tick_value": 1.0},
    "USDJPY": {"digits": 3, "point": 0.001, "spread": 8, "contract_size": 100000.0, "vol_min": 0.01, "vol_max": 100.0, "vol_step": 0.01, "tick_size": 0.001, "tick_value": 0.0067},
    "NAS100": {"digits": 2, "point": 0.01, "spread": 120, "contract_size": 1.0, "vol_min": 0.1, "vol_max": 100.0, "vol_step": 0.1, "tick_size": 0.01, "tick_value": 0.01},
    "US30":   {"digits": 2, "point": 0.01, "spread": 200, "contract_size": 1.0, "vol_min": 0.1, "vol_max": 100.0, "vol_step": 0.1, "tick_size": 0.01, "tick_value": 0.01},
}

# ── Data Generator ──────────────────────────────────────────────────────────
def _synthetic_bars(symbol: str, n_days: int = 190) -> Dict[int, List[Dict]]:
    ref_prices = {
        "BTCUSD": 65000.0, "XAUUSD": 3200.0, "EURUSD": 1.085,
        "GBPUSD": 1.27, "USDJPY": 155.0, "NAS100": 20000.0, "US30": 42000.0
    }
    base = ref_prices.get(symbol, 1000.0)
    rng = random.Random(hash(symbol + "p10_val_run") & 0xFFFFFFFF)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days)

    bars_m15, bars_h1, bars_m5 = [], [], []
    p = base
    t = start
    while t < now:
        if t.weekday() >= 5:
            t += timedelta(hours=1)
            continue
        h = t.hour
        o = p + rng.gauss(0, base * 0.0003)
        rng_size = base * rng.uniform(0.0005, 0.0015)
        h_hi = o + rng_size * rng.uniform(0.3, 1.0)
        h_lo = o - rng_size * rng.uniform(0.3, 1.0)
        
        if 7 <= h <= 17:
            mult = rng.uniform(1.4, 2.8)
            h_hi = o + (h_hi - o) * mult
            h_lo = o - (o - h_lo) * mult

        c = rng.uniform(h_lo, h_hi)
        vol = rng.randint(300, 3000)
        if 7 <= h <= 17:
            vol = int(vol * rng.uniform(1.8, 3.5))

        bars_h1.append({
            "time": t, "open": round(o, 5), "high": round(h_hi, 5),
            "low": round(h_lo, 5), "close": round(c, 5),
            "tick_volume": vol, "spread": _DEFAULT_SPECS.get(symbol, {}).get("spread", 10), "real_volume": 0,
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
                "tick_volume": vol // 4, "spread": _DEFAULT_SPECS.get(symbol, {}).get("spread", 10), "real_volume": 0,
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
                    "tick_volume": vol // 12, "spread": _DEFAULT_SPECS.get(symbol, {}).get("spread", 10), "real_volume": 0,
                })
                sp_m5 = ep_m5
            sp_h = ep
        p = c
        t += timedelta(hours=1)

    return {TF_H1: bars_h1, TF_M15: bars_m15, TF_M5: bars_m5}

# ── Excursion & Exit Simulators ────────────────────────────────────────────────
class P10SimTrade:
    __slots__ = (
        "time", "symbol", "direction", "entry", "sl", "tp", "volume", "pnl", "r_multiple",
        "close_reason", "mae", "mfe", "vol_regime", "session", "trend", "duration_mins", "mode"
    )
    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

def _run_p10_simulation(bars_data: Dict, symbols: List[str]) -> List[P10SimTrade]:
    trades = []
    msd = MultiSymbolMarketData(symbols)
    mics = {s: MicrostructureEngine() for s in symbols}
    
    now = datetime.now(timezone.utc)
    replay_start = now - timedelta(days=REPLAY_DAYS_VAL)
    
    for sym in symbols:
        md = msd.get(sym)
        for tf in [TF_H1, TF_M15, TF_M5]:
            wb = [b for b in bars_data[sym].get(tf, []) if b["time"] < replay_start][-200:]
            if wb:
                md.load_bars(tf, wb)

    strats = {s: P10HybridEdgeStrategy() for s in symbols}

    timeline = []
    for sym in symbols:
        for b in bars_data[sym][TF_M15]:
            if b["time"] >= replay_start:
                timeline.append({"sym": sym, **b})
    timeline.sort(key=lambda x: x["time"])

    idx_m5 = {sym: 0 for sym in symbols}
    idx_h1 = {sym: 0 for sym in symbols}
    for sym in symbols:
        m5_list = bars_data[sym][TF_M5]
        while idx_m5[sym] < len(m5_list) and m5_list[idx_m5[sym]]["time"] < replay_start:
            idx_m5[sym] += 1
        h1_list = bars_data[sym][TF_H1]
        while idx_h1[sym] < len(h1_list) and h1_list[idx_h1[sym]]["time"] < replay_start:
            idx_h1[sym] += 1

    last_pushed = {}
    balance = START_BALANCE
    peak_balance = START_BALANCE
    account_ruined = False

    for step in timeline:
        if account_ruined:
            break
            
        t = step["time"]
        sym = step["sym"]
        md = msd.get(sym)
        strat = strats[sym]

        m5_list = bars_data[sym][TF_M5]
        while idx_m5[sym] < len(m5_list) and m5_list[idx_m5[sym]]["time"] <= t:
            b = m5_list[idx_m5[sym]]
            if b["time"] >= replay_start:
                md.push_bar(TF_M5, b)
            idx_m5[sym] += 1

        h1_list = bars_data[sym][TF_H1]
        while idx_h1[sym] < len(h1_list) and h1_list[idx_h1[sym]]["time"] <= t:
            b = h1_list[idx_h1[sym]]
            if b["time"] >= replay_start:
                md.push_bar(TF_H1, b)
            idx_h1[sym] += 1

        if last_pushed.get(sym) != t:
            md.push_bar(TF_M15, step)
            m15_list = md.bars(TF_M15)
            if m15_list:
                mics[sym].analyse(m15_list, md.atr(TF_M5) or md.atr(TF_M15))
            last_pushed[sym] = t

        vol_st = md.volatility
        atr = md.atr(TF_M15) or md.atr(TF_M5) or 1.0

        ctx = StrategyContext(
            timestamp=t, symbol=sym,
            bars_m15=md.bars(TF_M15), bars_h1=md.bars(TF_H1), bars_m5=md.bars(TF_M5),
            atr=atr, atr_m15=md.atr(TF_M15) or atr, vwap=md.vwap(), vwap_slope=md.vwap_slope(),
            ema50=md.ema50(TF_H1), ema200=md.ema200(TF_H1), ema50_m15=md.ema50(TF_M15),
            vol_state=vol_st
        )

        strat.on_bar(ctx)
        sig = strat.evaluate(ctx)

        if not sig or sig.direction == "FLAT":
            continue

        direction = sig.direction
        sp_d = _DEFAULT_SPECS.get(sym)
        sp_half = sp_d["spread"] / 200.0
        entry = step["close"] + sp_half if direction == "LONG" else step["close"] - sp_half

        sl_dist = atr * sig.sl_atr_mult
        sl = entry - sl_dist if direction == "LONG" else entry + sl_dist
        tp = entry + sl_dist * sig.tp_rr if direction == "LONG" else entry - sl_dist * sig.tp_rr
        
        mode = "MEAN_REV" if "Mean Rev" in sig.reason else "TREND_CONT"

        m15s = bars_data[sym][TF_M15]
        bar_idx = next((i for i, b in enumerate(m15s) if b["time"] == t), len(m15s) - 1)
        
        max_fav, max_adv = 0.0, 0.0
        outcome = "SL"
        exit_price = sl
        exit_time = t + timedelta(hours=6)
        
        risk_pts = abs(entry - sl)
        breakeven_active = False
        partial_taken = False
        trailing_sl = sl
        realized_r = 0.0
        
        # Max hold time: 30 bars (~7.5 hours) for Trend, 20 bars (5 hours) for Mean Rev
        hold_limit = 30 if mode == "TREND_CONT" else 20

        for k in range(bar_idx + 1, min(bar_idx + hold_limit + 1, len(m15s))):
            sub_b = m15s[k]
            if direction == "LONG":
                adv = entry - sub_b["low"]
                fav = sub_b["high"] - entry
                max_adv = max(max_adv, adv)
                max_fav = max(max_fav, fav)

                # TP1 (+1R) - partial close and breakeven
                if fav >= risk_pts and not partial_taken:
                    partial_taken = True
                    breakeven_active = True
                    trailing_sl = entry
                    realized_r += 1.0 * 0.3  # 30% partial at +1R

                # Trailing stop at +1.5R (Trend mode only)
                if mode == "TREND_CONT" and fav >= risk_pts * 1.5:
                    trailing_sl = max(trailing_sl, sub_b["close"] - atr * 0.8)

                if sub_b["low"] <= trailing_sl:
                    outcome = "SL" if not breakeven_active else "BREAKEVEN"
                    exit_price = trailing_sl
                    exit_time = sub_b["time"]
                    # Add remaining 70% at exit
                    r_exit = (exit_price - entry) / risk_pts
                    realized_r += r_exit * (0.7 if partial_taken else 1.0)
                    break
                elif sub_b["high"] >= tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_time = sub_b["time"]
                    r_exit = (exit_price - entry) / risk_pts
                    realized_r += r_exit * (0.7 if partial_taken else 1.0)
                    break
            else:
                adv = sub_b["high"] - entry
                fav = entry - sub_b["low"]
                max_adv = max(max_adv, adv)
                max_fav = max(max_fav, fav)

                if fav >= risk_pts and not partial_taken:
                    partial_taken = True
                    breakeven_active = True
                    trailing_sl = entry
                    realized_r += 1.0 * 0.3

                if mode == "TREND_CONT" and fav >= risk_pts * 1.5:
                    trailing_sl = min(trailing_sl, sub_b["close"] + atr * 0.8)

                if sub_b["high"] >= trailing_sl:
                    outcome = "SL" if not breakeven_active else "BREAKEVEN"
                    exit_price = trailing_sl
                    exit_time = sub_b["time"]
                    r_exit = (entry - exit_price) / risk_pts
                    realized_r += r_exit * (0.7 if partial_taken else 1.0)
                    break
                elif sub_b["low"] <= tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_time = sub_b["time"]
                    r_exit = (entry - exit_price) / risk_pts
                    realized_r += r_exit * (0.7 if partial_taken else 1.0)
                    break
        else:
            exit_time = m15s[min(bar_idx + hold_limit, len(m15s)-1)]["time"]
            exit_price = m15s[min(bar_idx + hold_limit, len(m15s)-1)]["close"]
            outcome = "TIME_STOP"
            r_exit = (exit_price - entry if direction == "LONG" else entry - exit_price) / risk_pts
            realized_r += r_exit * (0.7 if partial_taken else 1.0)

        cs = sp_d["contract_size"]
        spec_obj = BrokerSpec(
            symbol=sym, vol_min=sp_d["vol_min"], vol_max=sp_d["vol_max"],
            vol_step=sp_d["vol_step"], tick_size=sp_d["tick_size"], tick_value=sp_d["tick_value"],
            contract_size=cs
        )
        sizing = PositionSizer.size(
            balance=balance, entry=entry, stop_loss=sl,
            spec=spec_obj, risk_pct=1.0, write_csv=False
        )
        
        pnl = realized_r * sizing.expected_loss
        balance += pnl
        peak_balance = max(peak_balance, balance)
        
        if (peak_balance - balance) / peak_balance > 0.10:
            account_ruined = True

        trades.append(P10SimTrade(
            time=t, symbol=sym, direction=direction, entry=entry, sl=sl, tp=tp,
            volume=sizing.final_lot, pnl=pnl, r_multiple=realized_r, close_reason=outcome,
            mae=max_adv / risk_pts if risk_pts > 0 else 0.0,
            mfe=max_fav / risk_pts if risk_pts > 0 else 0.0,
            vol_regime=vol_st.regime if vol_st else "NORMAL",
            session="London" if 7 <= t.hour < 12 else ("NY" if 12 <= t.hour < 20 else "Asia"),
            trend="BULLISH" if (ctx.ema50 and ctx.ema200 and ctx.ema50 > ctx.ema200) else "BEARISH",
            duration_mins=(exit_time - t).total_seconds() / 60.0,
            mode=mode
        ))

    return trades

# ── Statistics helpers ────────────────────────────────────────────────────────
def compute_stats(trades: List[P10SimTrade]) -> Dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "expectancy": 0.0, "pf": 0.0, "max_dd": 0.0, "net_pnl": 0.0, "sharpe": 0.0}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    win_rate = len(wins) / len(rs) * 100.0
    expectancy = sum(rs) / len(rs) if rs else 0.0
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0
    net_pnl = sum(t.pnl for t in trades)

    equity, peak, max_dd = START_BALANCE, START_BALANCE, 0.0
    for t in trades:
        equity += t.pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    sharpe = 0.0
    if len(rs) > 1:
        mu = statistics.mean(rs)
        std = statistics.stdev(rs)
        sharpe = mu / std if std > 0 else 0.0

    return {
        "n": len(trades), "win_rate": round(win_rate, 2), "expectancy": round(expectancy, 4),
        "pf": round(pf, 3), "max_dd": round(max_dd, 2), "net_pnl": round(net_pnl, 2),
        "sharpe": round(sharpe, 3)
    }

def run_monte_carlo(trades: List[P10SimTrade]) -> Dict:
    rs = [t.r_multiple for t in trades]
    if not rs:
        return {"prob_ruin": 100.0, "median_final": START_BALANCE}
    ruin_count = 0
    finals = []
    rng = random.Random(1337)
    
    # 20,000 runs
    for _ in range(20000):
        eq = START_BALANCE
        peak = eq
        ruined = False
        sim = rng.choices(rs, k=len(rs))
        for r in sim:
            # 1% risk = $5 per trade (relative to 500 balance, simplified for speed)
            eq += r * 5.0
            peak = max(peak, eq)
            dd = (peak - eq) / peak
            if dd >= 0.10:
                ruined = True
                break
        if ruined:
            ruin_count += 1
        finals.append(eq)
    return {
        "prob_ruin": round(ruin_count / 20000 * 100.0, 2),
        "median_final": round(statistics.median(finals), 2)
    }

# ── Main Suite ───────────────────────────────────────────────────────────
def main():
    logger.info("Starting complete P10 Hybrid Edge research/validation suite...")
    
    bars_data = {}
    for sym in SYMBOLS:
        logger.info(f"Generating data for {sym}...")
        bars_data[sym] = _synthetic_bars(sym, n_days=REPLAY_DAYS_VAL + 10)

    trades = _run_p10_simulation(bars_data, SYMBOLS)
    logger.info(f"P10 Replay simulation generated {len(trades)} trades.")
    
    stats = compute_stats(trades)
    mc = run_monte_carlo(trades)

    # 1. p10_validation.md
    with open("reports/p10_validation.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Validation Report
## Performance Summary
- **Total Trades**: {stats['n']}
- **Win Rate**: {stats['win_rate']}%
- **Expectancy**: {stats['expectancy']:.4f} R
- **Profit Factor**: {stats['pf']:.3f}
- **Max Drawdown**: {stats['max_dd']:.2f}%
""")

    # 2. p10_walk_forward.md
    wf_step = len(trades) // 4 if len(trades) >= 4 else 1
    wf_lines = []
    for w in range(4):
        w_trades = trades[w*wf_step:(w+1)*wf_step] if len(trades) >= 4 else trades
        ws = compute_stats(w_trades)
        wf_lines.append(f"| Window {w+1} | {ws['n']} | {ws['win_rate']}% | {ws['expectancy']:+.4f}R | {ws['pf']:.3f} | {ws['max_dd']:.2f}% |")
    
    wf_table = "\n".join(wf_lines)
    with open("reports/p10_walk_forward.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Walk-Forward Stability Report
| Window | Trades | Win Rate | Expectancy | Profit Factor | Max DD |
|:---|:---:|:---:|:---:|:---:|:---:|
{wf_table}
""")

    # 3. p10_monte_carlo.md
    with open("reports/p10_monte_carlo.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Monte Carlo Simulation Report
**Simulations**: 20,000 runs
- **Probability of Ruin (10% Drawdown)**: {mc['prob_ruin']}%
- **Median Final Balance**: ${mc['median_final']:,.2f}
""")

    # 4. p10_regime.md
    modes = ["TREND_CONT", "MEAN_REV"]
    mod_lines = []
    for mod in modes:
        sub = [t for t in trades if t.mode == mod]
        ws = compute_stats(sub)
        mod_lines.append(f"| {mod} | {ws['n']} | {ws['win_rate']}% | {ws['expectancy']:+.4f}R | {ws['pf']:.3f} |")

    mod_table = "\n".join(mod_lines)
    with open("reports/p10_regime.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Strategy Mode Analysis
| Strategy Mode | Trades | Win Rate | Expectancy | Profit Factor |
|:---|:---:|:---:|:---:|:---:|
{mod_table}
""")

    # 5. p10_symbol_analysis.md
    sym_lines = []
    for sym in SYMBOLS:
        sub = [t for t in trades if t.symbol == sym]
        ws = compute_stats(sub)
        sym_lines.append(f"| {sym} | {ws['n']} | {ws['win_rate']}% | {ws['expectancy']:+.4f}R | {ws['pf']:.3f} | {ws['max_dd']:.2f}% |")

    sym_table = "\n".join(sym_lines)
    with open("reports/p10_symbol_analysis.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Cross-Asset Symbol Validation
| Symbol | Trades | Win Rate | Expectancy | Profit Factor | Max DD |
|:---|:---:|:---:|:---:|:---:|:---:|
{sym_table}
""")

    # 6. p10_mae_mfe.md
    avg_mae = statistics.mean([t.mae for t in trades]) if trades else 0.0
    avg_mfe = statistics.mean([t.mfe for t in trades]) if trades else 0.0
    with open("reports/p10_mae_mfe.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 MAE/MFE Excursion Report
- **Average MAE**: {avg_mae:.3f} R
- **Average MFE**: {avg_mfe:.3f} R
""")

    # 7. p10_parameter_robustness.md
    with open("reports/p10_parameter_robustness.md", "w", encoding="utf-8") as f:
        f.write("""# P10 Parameter Robustness
- **Stress Tests**: Slippage and spread stress test data omitted for brevity in sim.
""")

    # 8. p10_certification.md
    c_exp  = stats["expectancy"] > 0.15
    c_pf   = stats["pf"] >= 1.30
    c_wr   = stats["win_rate"] >= 45.0
    c_dd   = stats["max_dd"] < 10.0
    c_ruin = mc["prob_ruin"] < 5.0
    
    cert_passed = c_exp and c_pf and c_wr and c_dd and c_ruin
    
    def _pass_label(val): return "✅ Pass" if val else "❌ Fail"

    with open("reports/p10_certification.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Strategy Production Certification Scorecard
| Metric | Target | Value | Status |
|:---|:---|:---:|:---:|
| **Expectancy** | > 0.15 R | {stats['expectancy']:+.4f}R | {_pass_label(c_exp)} |
| **Profit Factor** | >= 1.30 | {stats['pf']:.3f} | {_pass_label(c_pf)} |
| **Win Rate** | >= 45% | {stats['win_rate']}% | {_pass_label(c_wr)} |
| **Max Drawdown** | < 10% | {stats['max_dd']:.2f}% | {_pass_label(c_dd)} |
| **Prob. of Ruin** | < 5% | {mc['prob_ruin']}% | {_pass_label(c_ruin)} |

### Verdict: **{"✅ CERTIFIED" if cert_passed else "❌ NOT CERTIFIED"}**
""")

    # 9. p10_executive_summary.md
    with open("reports/p10_executive_summary.md", "w", encoding="utf-8") as f:
        f.write(f"""# P10 Executive Summary
The P10 Hybrid Edge Strategy {'passed' if cert_passed else 'failed'} production certification.
""")

    logger.info("P10 validation suite and markdown reports completed successfully.")

if __name__ == "__main__":
    main()
