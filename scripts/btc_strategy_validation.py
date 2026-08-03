"""
scripts/btc_strategy_validation.py — BTCUSD Strategy Validation Engine
=====================================================================

Executes the production certification validation for BTC_P3_OrderFlow.
Generates all 8 required reports in the reports/ directory.
"""

import os
import sys
import math
import csv
import logging
import statistics
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

# ── Path Setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("btc_validation")

# Silence sizing logs
logging.getLogger("app.risk_manager").setLevel(logging.WARNING)

# ── MT5 Setup ─────────────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.error("MetaTrader5 not available! MT5 connection is required.")
    sys.exit(1)

from app.position_sizer import PositionSizer, BrokerSpec
from strategies.context import StrategyContext
from strategies.signal import StrategySignal
from app.market_data import Bar, VolState
from strategies.prototypes.btc_p3_order_flow import BTCOrderFlowMomentumStrategy

# Constants
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

START_BALANCE = 500.0
RISK_PCT = 1.0
SYMBOL = "BTCUSD"

# BTC broker spec (read from MT5 or fallback)
_BTC_SPEC = BrokerSpec.fallback("BTCUSD")

@dataclass
class ValTrade:
    direction:    str
    entry_time:   datetime
    entry_price:  float
    sl:           float
    tp:           float
    lot:          float
    risk_usd:     float
    reason:       str
    exit_time:    Optional[datetime] = None
    exit_price:   float = 0.0
    pnl:          float = 0.0
    r_multiple:   float = 0.0
    close_reason: str = ""
    # Indicators for regime analysis
    regime_trend: str = "TRENDING"
    regime_vol:   str = "NORMAL"

def fetch_raw_bars(symbol: str, tf: int, count: int) -> List[Dict]:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return []
    bars = []
    for r in rates:
        bars.append({
            "time":        datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
            "open":        float(r["open"]),
            "high":        float(r["high"]),
            "low":         float(r["low"]),
            "close":       float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
        })
    return bars

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df['high'] - df['low']
    high_cp = abs(df['high'] - df['close'].shift())
    low_cp = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

# ── Reusable Simulation Loop ──────────────────────────────────────────────────
def run_btc_simulation(
    raw_m15: List[Dict],
    df_h1: pd.DataFrame,
    precomputed_m15: Optional[pd.DataFrame] = None,
    precomputed_h1: Optional[pd.DataFrame] = None,
    precomputed_bars: Optional[List[Bar]] = None,
    vol_spike_mult: float = 1.8,
    atr_window: int = 14,
    trend_filter_period: int = 50,
    sl_atr_mult: float = 1.5,
    tp_rr: float = 2.0,
    spread_multiplier: float = 1.0,
    slippage_ticks: float = 0.0,
    missed_fill_prob: float = 0.0,
    latency_delay: bool = False,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> List[ValTrade]:
    
    # 1. Create DataFrame for M15 with custom ATR window
    if precomputed_m15 is not None and atr_window == 14:
        df_m15 = precomputed_m15
    else:
        df_m15 = pd.DataFrame(raw_m15)
        df_m15['ema50_m15'] = df_m15['close'].ewm(span=50, adjust=False).mean()
        df_m15['atr_m15'] = calculate_atr(df_m15, atr_window)
    
    # 2. Recompute H1 Trend indicators with custom period
    if precomputed_h1 is not None and trend_filter_period == 50:
        df_h1_local = precomputed_h1
    else:
        df_h1_local = df_h1.copy()
        df_h1_local['ema50'] = df_h1_local['close'].ewm(span=trend_filter_period, adjust=False).mean()
        df_h1_local['ema200'] = df_h1_local['close'].ewm(span=200, adjust=False).mean()

    # Map H1 indicators for fast lookup using zip (much faster than iterrows)
    h1_map = dict(zip(df_h1_local['time'], zip(df_h1_local['ema50'], df_h1_local['ema200'])))

    # Convert df rows to Bar objects (use precomputed if available)
    if precomputed_bars is not None:
        m15_bars_list = precomputed_bars
    else:
        m15_bars_list = []
        for _, r in df_m15.iterrows():
            m15_bars_list.append(Bar(
                time=r['time'], open=r['open'], high=r['high'],
                low=r['low'], close=r['close'], tick_vol=r['tick_volume'],
                spread=0.0, real_vol=0, timeframe=mt5.TIMEFRAME_M15
            ))

    # Initialize strategy
    strat = BTCOrderFlowMomentumStrategy()
    strat.vol_spike_mult = vol_spike_mult
    strat.default_sl_atr_mult = sl_atr_mult
    strat.default_tp_rr = tp_rr

    closed_trades: List[ValTrade] = []
    active_trade: Optional[ValTrade] = None
    bal = START_BALANCE
    warmup = max(200, atr_window * 2)

    # Convert series to lists for O(1) direct memory indexing (pandas speedup)
    times = df_m15['time'].tolist()
    atr_m15 = df_m15['atr_m15'].tolist()
    ema50_m15 = df_m15['ema50_m15'].tolist()

    # Sliced search range for massive walk-forward speedups
    start_idx = warmup
    if start_dt:
        for idx in range(warmup, len(times)):
            if times[idx] >= start_dt:
                start_idx = idx
                break
    end_idx = len(times)
    if end_dt:
        for idx in range(start_idx, len(times)):
            if times[idx] > end_dt:
                end_idx = idx
                break

    for idx in range(start_idx, end_idx):
        t = times[idx]
        
        # Apply start/end date filters
        if start_dt and t < start_dt:
            continue
        if end_dt and t > end_dt:
            continue

        latest_bar = m15_bars_list[idx]
        atr_val = atr_m15[idx]
        ema50_m15_val = ema50_m15[idx]

        # H1 indicators lookup
        h_time = t.replace(minute=0, second=0, microsecond=0)
        h1_vals = h1_map.get(h_time)
        if h1_vals is not None:
            ema50_val, ema200_val = h1_vals
        else:
            # fallback
            prev_rows = df_h1_local[df_h1_local['time'] <= t]
            if len(prev_rows) > 0:
                last_row = prev_rows.iloc[-1]
                ema50_val = float(last_row['ema50'])
                ema200_val = float(last_row['ema200'])
            else:
                continue

        # Volatility regime
        atr_list = atr_m15[max(0, idx-100):idx+1]
        less_equal = sum(1 for x in atr_list if x <= atr_val)
        pct = (less_equal / len(atr_list)) * 100.0 if atr_list else 50.0
        
        vol_regime = "NORMAL"
        if pct < 25: vol_regime = "COMPRESSED"
        elif pct > 75: vol_regime = "EXPANDING"
        vol_state = VolState(percentile=pct, regime=vol_regime)

        ctx = StrategyContext(
            symbol=SYMBOL,
            timestamp=t,
            bars_m15=m15_bars_list[max(0, idx-100):idx+1],
            bars_h1=[],
            atr=0.0,
            atr_m15=atr_val,
            ema50_m15=ema50_m15_val,
            ema50=ema50_val,
            ema200=ema200_val,
            vol_state=vol_state,
            contract_size=CONTRACT_SIZE,
            spread=10.0 * spread_multiplier # simulate spread
        )

        strat.on_bar(ctx)

        # ── Manage Active Trade ───────────────────────────────────────────────
        if active_trade is not None:
            trade = active_trade
            hit_sl = (trade.direction == "LONG"  and latest_bar.low  <= trade.sl) or \
                     (trade.direction == "SHORT" and latest_bar.high >= trade.sl)
            hit_tp = (trade.direction == "LONG"  and latest_bar.high >= trade.tp) or \
                     (trade.direction == "SHORT" and latest_bar.low  <= trade.tp)

            if hit_sl or hit_tp:
                if hit_sl and hit_tp:
                    exit_price = trade.sl
                    close_reason = "SL"
                elif hit_sl:
                    exit_price = trade.sl
                    close_reason = "SL"
                else:
                    exit_price = trade.tp
                    close_reason = "TP"

                # Apply slippage on exit
                if slippage_ticks > 0:
                    slip_amt = slippage_ticks * 0.01 # 1 tick = 0.01
                    if trade.direction == "LONG":
                        exit_price -= slip_amt # worse exit
                    else:
                        exit_price += slip_amt

                diff = exit_price - trade.entry_price
                if trade.direction == "SHORT":
                    diff = -diff

                pnl = diff * CONTRACT_SIZE * trade.lot
                trade.exit_time = t
                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.r_multiple = round(pnl / trade.risk_usd, 3) if trade.risk_usd > 0 else 0.0
                trade.close_reason = close_reason

                bal += pnl
                closed_trades.append(trade)
                active_trade = None
        else:
            # ── Evaluate Entry ────────────────────────────────────────────────
            sig = strat.evaluate(ctx)
            if sig.is_entry and sig.confidence >= 50.0:
                # Missed fill probability check
                if missed_fill_prob > 0.0 and random.random() < missed_fill_prob:
                    continue

                price = latest_bar.close
                
                # Apply entry slippage or delay
                if slippage_ticks > 0 or latency_delay:
                    ticks = slippage_ticks if slippage_ticks > 0 else 2.0
                    slip_amt = ticks * 0.01
                    if sig.direction == "LONG":
                        price += slip_amt # worse entry
                    else:
                        price -= slip_amt

                if sig.direction == "LONG":
                    sl = price - atr_val * sig.sl_atr_mult
                    tp = price + atr_val * sig.sl_atr_mult * sig.tp_rr
                else:
                    sl = price + atr_val * sig.sl_atr_mult
                    tp = price - atr_val * sig.sl_atr_mult * sig.tp_rr

                _sizing = PositionSizer.size(
                    balance=bal,
                    entry=price,
                    stop_loss=sl,
                    tp_price=tp,
                    risk_pct=RISK_PCT,
                    spec=_BTC_SPEC,
                    strategy="BTC_P3_OrderFlow",
                    symbol=SYMBOL,
                    write_csv=False,
                )
                lot  = _sizing.final_lot
                risk = _sizing.expected_loss

                if lot >= _BTC_SPEC.vol_min:
                    reg_trend = "TRENDING" if (ema50_val > ema200_val * 1.0003 or ema50_val < ema200_val * 0.9997) else "RANGING"
                    active_trade = ValTrade(
                        direction=sig.direction,
                        entry_time=t,
                        entry_price=price,
                        sl=sl, tp=tp,
                        lot=lot,
                        risk_usd=risk,
                        reason=sig.reason,
                        regime_trend=reg_trend,
                        regime_vol=vol_regime
                    )

    # Force close final open trade
    if active_trade is not None:
        trade = active_trade
        exit_price = m15_bars_list[-1].close
        diff = exit_price - trade.entry_price
        if trade.direction == "SHORT":
            diff = -diff
        pnl = diff * CONTRACT_SIZE * trade.lot
        trade.exit_time = m15_bars_list[-1].time
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.r_multiple = pnl / trade.risk_usd if trade.risk_usd > 0 else 0.0
        trade.close_reason = "FORCE_CLOSE"
        closed_trades.append(trade)

    return closed_trades

def compute_stats(trades: List[ValTrade]) -> Dict:
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy": 0.0, "net_profit": 0.0, "max_drawdown": 0.0,
            "sharpe": 0.0, "win_streak": 0, "loss_streak": 0, "recovery_days": 0.0
        }
    pnl = [t.pnl for t in trades]
    r_mults = [t.r_multiple for t in trades]
    
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    
    win_rate = len(wins) / len(trades) * 100.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
    exp = statistics.mean(r_mults)
    net_p = sum(pnl)

    # Drawdown profile
    eq = [START_BALANCE]
    for p in pnl:
        eq.append(eq[-1] + p)
        
    peak = eq[0]
    max_dd = 0.0
    peak_idx = 0
    recovery_ticks = 0
    
    for idx, v in enumerate(eq):
        if v > peak:
            peak = v
            peak_idx = idx
        dd = (peak - v) / peak * 100.0
        max_dd = max(max_dd, dd)
        
    # Recovery time: approximate days from peak to new peak
    # Let's find the longest period under peak
    max_recovery_trades = 0
    current_recovery_trades = 0
    peak_val = eq[0]
    for v in eq:
        if v >= peak_val:
            peak_val = v
            max_recovery_trades = max(max_recovery_trades, current_recovery_trades)
            current_recovery_trades = 0
        else:
            current_recovery_trades += 1
    max_recovery_trades = max(max_recovery_trades, current_recovery_trades)
    # 4 M15 bars = 1 hour, 96 bars = 1 day
    recovery_days = (max_recovery_trades / 96.0)

    # Winning / losing streaks
    current_win = 0
    current_loss = 0
    max_win = 0
    max_loss = 0
    for p in pnl:
        if p > 0:
            current_win += 1
            max_loss = max(max_loss, current_loss)
            current_loss = 0
        else:
            current_loss += 1
            max_win = max(max_win, current_win)
            current_win = 0
    max_win = max(max_win, current_win)
    max_loss = max(max_loss, current_loss)

    # Sharpe Ratio (trade returns)
    mean_p = statistics.mean(pnl)
    std_p  = statistics.stdev(pnl) if len(pnl) > 1 else 0.0001
    sharpe = (mean_p / std_p * math.sqrt(252)) if std_p > 0 else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(pf, 2) if pf != float('inf') else 99.0,
        "expectancy": round(exp, 4),
        "net_profit": round(net_p, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sharpe, 3),
        "win_streak": max_win,
        "loss_streak": max_loss,
        "recovery_days": round(recovery_days, 1)
    }

# ── Main Suite Runner ─────────────────────────────────────────────────────────
def run_validation_suite():
    if not mt5.initialize():
        logger.error("MT5 initialize failed!")
        return

    logger.info("Loading BTCUSD data...")
    count_m15 = 80000
    raw_m15 = fetch_raw_bars(SYMBOL, mt5.TIMEFRAME_M15, count_m15)
    
    count_h1 = int(count_m15 / 4) + 1000
    raw_h1 = fetch_raw_bars(SYMBOL, mt5.TIMEFRAME_H1, count_h1)
    mt5.shutdown()

    if not raw_m15 or not raw_h1:
        logger.error("Failed to load historical data!")
        return

    df_h1 = pd.DataFrame(raw_h1)
    df_h1['ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df_h1['ema200'] = df_h1['close'].ewm(span=200, adjust=False).mean()

    # Precompute baseline M15 df and bars
    pre_m15 = pd.DataFrame(raw_m15)
    pre_m15['ema50_m15'] = pre_m15['close'].ewm(span=50, adjust=False).mean()
    pre_m15['atr_m15'] = calculate_atr(pre_m15, 14)

    pre_bars = []
    for _, r in pre_m15.iterrows():
        pre_bars.append(Bar(
            time=r['time'], open=r['open'], high=r['high'],
            low=r['low'], close=r['close'], tick_vol=r['tick_volume'],
            spread=0.0, real_vol=0, timeframe=mt5.TIMEFRAME_M15
        ))

    logger.info("Executing baseline simulation...")
    base_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars)
    m_base = compute_stats(base_trades)
    logger.info(f"Baseline completed: {m_base['total_trades']} trades, Expectancy={m_base['expectancy']:.4f}R")

    # =========================================================================
    # Phase 1 — Walk-Forward Validation
    # =========================================================================
    logger.info("Executing Walk-Forward Validation (6M Train / 3M Validate)...")
    end_time = raw_m15[-1]["time"]
    start_time = raw_m15[200]["time"]
    
    wf_results = []
    wf_offset = 0
    wf_train_len = 180 # days
    wf_val_len = 90
    
    while True:
        train_start = start_time + timedelta(days=wf_offset)
        train_end   = train_start + timedelta(days=wf_train_len)
        val_start   = train_end
        val_end     = val_start + timedelta(days=wf_val_len)
        
        if val_end > end_time:
            break
            
        train_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, start_dt=train_start, end_dt=train_end)
        val_trades   = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, start_dt=val_start, end_dt=val_end)
        
        m_train = compute_stats(train_trades)
        m_val   = compute_stats(val_trades)
        
        wf_results.append({
            "window": len(wf_results) + 1,
            "train_period": f"{train_start.strftime('%Y/%m')}-{train_end.strftime('%Y/%m')}",
            "val_period": f"{val_start.strftime('%Y/%m')}-{val_end.strftime('%Y/%m')}",
            "train_exp": m_train["expectancy"],
            "val_exp": m_val["expectancy"],
            "train_pf": m_train["profit_factor"],
            "val_pf": m_val["profit_factor"],
            "val_dd": m_val["max_drawdown"],
            "val_trades": len(val_trades),
        })
        wf_offset += wf_val_len

    wf_rows = []
    for r in wf_results:
        wf_rows.append(
            f"| Window {r['window']} | {r['train_period']} | {r['val_period']} | "
            f"{r['train_exp']:+.3f}R | {r['val_exp']:+.3f}R | "
            f"{r['train_pf']:.2f} | {r['val_pf']:.2f} | "
            f"{r['val_dd']}% | {r['val_trades']} |"
        )
    wf_rows_str = "\n".join(wf_rows)

    wf_md = f"""# BTCUSD Walk-Forward Validation Report
**Sequential Out-of-Sample Performance Stability (6-Month Train / 3-Month Validate)**

## Rolling Validation Results

| Window | Train Window | Validation Window | Train Exp | Val Exp | Train PF | Val PF | Val DD | Val Trades |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{wf_rows_str}

---

## Stability Verdict
- **Out-of-Sample Consistency**: Evaluates if the strategy maintains positive expectancy across sequential validation segments.
"""
    with open(REPORTS_DIR / "btc_walk_forward.md", "w", encoding="utf-8") as f:
        f.write(wf_md)

    # =========================================================================
    # Phase 2 — Monte Carlo Squeeze
    # =========================================================================
    logger.info("Executing Monte Carlo Squeeze (20,000 runs)...")
    mc_runs = 20000
    r_pool = [t.r_multiple for t in base_trades] if base_trades else [0.0]
    n_trades = len(r_pool)
    
    # Vectorized NumPy bootstrap simulation
    indices = np.random.randint(0, n_trades, size=(mc_runs, n_trades))
    r_samples = np.array(r_pool)[indices]
    
    penalties = np.random.uniform(5.0, 20.0, size=(mc_runs, n_trades))
    missed = np.random.random(size=(mc_runs, n_trades)) < 0.05
    delays = np.random.random(size=(mc_runs, n_trades)) < 0.10
    
    r_act = r_samples.copy()
    r_act[delays] -= 0.10
    
    pnl_matrix = r_act * 50.0 - penalties
    pnl_matrix[missed] = 0.0
    
    balances = START_BALANCE + np.hstack([np.zeros((mc_runs, 1)), np.cumsum(pnl_matrix, axis=1)])
    peaks = np.maximum.accumulate(balances, axis=1)
    drawdowns = (peaks - balances) / peaks * 100.0
    
    max_drawdowns = np.max(drawdowns, axis=1)
    final_balances = balances[:, -1]
    ruin_count = np.sum(np.any(balances < START_BALANCE * 0.5, axis=1))
    
    prob_ruin = ruin_count / mc_runs * 100.0
    worst_expected_dd = np.percentile(max_drawdowns, 95)
    median_return = np.median(final_balances) - START_BALANCE
    ci_95_low = np.percentile(final_balances, 2.5)
    ci_95_high = np.percentile(final_balances, 97.5)
    cvar_95 = np.mean(final_balances[final_balances <= np.percentile(final_balances, 5)])

    mc_md = f"""# BTCUSD Monte Carlo Squeeze Report
**Bootstrap Stress-Testing (20,000 Iterations)**

## Monte Carlo Simulation Metrics

| Parameter | Value |
|:---|---:|
| **Probability of Ruin (50% Account Loss)** | {prob_ruin:.2f}% |
| **Worst Expected Drawdown (95th Percentile)** | {worst_expected_dd:.2f}% |
| **Median Final Return** | ${median_return:+.2f} |
| **95% Confidence Interval (Ending Balance)** | ${ci_95_low:.2f} to ${ci_95_high:.2f} |
| **Conditional Value at Risk (95% CVaR)** | ${cvar_95:.2f} |
"""
    with open(REPORTS_DIR / "btc_monte_carlo.md", "w", encoding="utf-8") as f:
        f.write(mc_md)

    # =========================================================================
    # Phase 3 — Transaction Cost Sensitivity
    # =========================================================================
    logger.info("Executing Transaction Cost Sensitivity...")
    cost_scenarios = [
        ("Normal Spread", 1.0, 0.0),
        ("Spread +25%", 1.25, 0.0),
        ("Spread +50%", 1.50, 0.0),
        ("Spread +100%", 2.0, 0.0),
        ("Spread +200%", 3.0, 0.0),
        ("Slippage 1 Tick", 1.0, 1.0),
        ("Slippage 3 Ticks", 1.0, 3.0),
        ("Slippage 5 Ticks", 1.0, 5.0),
    ]
    
    cost_rows = []
    for name, sp_m, slip in cost_scenarios:
        sc_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, spread_multiplier=sp_m, slippage_ticks=slip)
        m = compute_stats(sc_trades)
        cost_rows.append(
            f"| {name} | {m['total_trades']} | {m['win_rate']}% | "
            f"{m['expectancy']:+.3f}R | {m['profit_factor']:.2f} | "
            f"{m['max_drawdown']}% | ${m['net_profit']:+.2f} |"
        )
    cost_rows_str = "\n".join(cost_rows)

    cost_md = f"""# BTCUSD Transaction Cost Sensitivity Report
**Impact of Spreads and Execution Slippage on Strategy Profitability**

## Cost Stress Testing Matrix

| Scenario | Total Trades | Win Rate | Expectancy | Profit Factor | Max Drawdown | Net Profit |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{cost_rows_str}
"""
    with open(REPORTS_DIR / "btc_cost_sensitivity.md", "w", encoding="utf-8") as f:
        f.write(cost_md)

    # =========================================================================
    # Phase 4 — Parameter Robustness
    # =========================================================================
    logger.info("Executing Parameter Robustness...")
    param_scenarios = [
        # Volume Spike
        ("Vol Spike -30% (1.26)", 1.26, 14, 50, 1.5, 2.0),
        ("Vol Spike -20% (1.44)", 1.44, 14, 50, 1.5, 2.0),
        ("Vol Spike -10% (1.62)", 1.62, 14, 50, 1.5, 2.0),
        ("Vol Spike Baseline (1.80)", 1.80, 14, 50, 1.5, 2.0),
        ("Vol Spike +10% (1.98)", 1.98, 14, 50, 1.5, 2.0),
        ("Vol Spike +20% (2.16)", 2.16, 14, 50, 1.5, 2.0),
        ("Vol Spike +30% (2.34)", 2.34, 14, 50, 1.5, 2.0),
        # ATR Window
        ("ATR Window -30% (10)", 1.80, 10, 50, 1.5, 2.0),
        ("ATR Window -20% (11)", 1.80, 11, 50, 1.5, 2.0),
        ("ATR Window -10% (13)", 1.80, 13, 50, 1.5, 2.0),
        ("ATR Window +10% (15)", 1.80, 15, 50, 1.5, 2.0),
        ("ATR Window +20% (17)", 1.80, 17, 50, 1.5, 2.0),
        ("ATR Window +30% (18)", 1.80, 18, 50, 1.5, 2.0),
        # Trend Filter
        ("Trend Period -30% (35)", 1.80, 14, 35, 1.5, 2.0),
        ("Trend Period -20% (40)", 1.80, 14, 40, 1.5, 2.0),
        ("Trend Period -10% (45)", 1.80, 14, 45, 1.5, 2.0),
        ("Trend Period +10% (55)", 1.80, 14, 55, 1.5, 2.0),
        ("Trend Period +20% (60)", 1.80, 14, 60, 1.5, 2.0),
        ("Trend Period +30% (65)", 1.80, 14, 65, 1.5, 2.0),
        # Stop Loss
        ("SL Mult -30% (1.05)", 1.80, 14, 50, 1.05, 2.0),
        ("SL Mult -20% (1.20)", 1.80, 14, 50, 1.20, 2.0),
        ("SL Mult -10% (1.35)", 1.80, 14, 50, 1.35, 2.0),
        ("SL Mult +10% (1.65)", 1.80, 14, 50, 1.65, 2.0),
        ("SL Mult +20% (1.80)", 1.80, 14, 50, 1.80, 2.0),
        ("SL Mult +30% (1.95)", 1.80, 14, 50, 1.95, 2.0),
        # Take Profit
        ("TP Mult -30% (1.4)", 1.80, 14, 50, 1.5, 1.4),
        ("TP Mult -20% (1.6)", 1.80, 14, 50, 1.5, 1.6),
        ("TP Mult -10% (1.8)", 1.80, 14, 50, 1.5, 1.8),
        ("TP Mult +10% (2.2)", 1.80, 14, 50, 1.5, 2.2),
        ("TP Mult +20% (2.4)", 1.80, 14, 50, 1.5, 2.4),
        ("TP Mult +30% (2.6)", 1.80, 14, 50, 1.5, 2.6),
    ]
    
    param_rows = []
    for name, v_sp, atr_w, tr_p, sl_m, tp_r in param_scenarios:
        sc_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, vol_spike_mult=v_sp, atr_window=atr_w, trend_filter_period=tr_p, sl_atr_mult=sl_m, tp_rr=tp_r)
        m = compute_stats(sc_trades)
        param_rows.append(
            f"| {name} | {m['total_trades']} | {m['win_rate']}% | "
            f"{m['expectancy']:+.3f}R | {m['profit_factor']:.2f} | "
            f"{m['max_drawdown']}% | ${m['net_profit']:+.2f} |"
        )
    param_rows_str = "\n".join(param_rows)

    param_md = f"""# BTCUSD Parameter Robustness Report
**Sensitivity Evaluation of Core Entry and Exit Parameters**

## Parameter Variations Matrix

| Scenario | Total Trades | Win Rate | Expectancy | Profit Factor | Max Drawdown | Net Profit |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{param_rows_str}
"""
    with open(REPORTS_DIR / "btc_parameter_robustness.md", "w", encoding="utf-8") as f:
        f.write(param_md)

    # =========================================================================
    # Phase 5 — Rolling Performance
    # =========================================================================
    logger.info("Executing Rolling Performance...")
    rolling_windows = [30, 60, 90, 180]
    rolling_stats = {}
    duration_days = (end_time - start_time).days
    
    for r_days in rolling_windows:
        stats_list = []
        offset = 0
        while True:
            w_start = start_time + timedelta(days=offset)
            w_end   = w_start + timedelta(days=r_days)
            if w_end > end_time:
                break
            subset = [t for t in base_trades if w_start <= t.entry_time < w_end]
            m = compute_stats(subset)
            stats_list.append(m)
            offset += 15 # step 15 days
            
        exps = [x["expectancy"] for x in stats_list if x["total_trades"] > 0]
        pfs  = [x["profit_factor"] for x in stats_list if x["total_trades"] > 0]
        dds  = [x["max_drawdown"] for x in stats_list if x["total_trades"] > 0]
        wrs  = [x["win_rate"] for x in stats_list if x["total_trades"] > 0]
        
        rolling_stats[r_days] = {
            "avg_exp": np.mean(exps) if exps else 0.0,
            "min_exp": np.min(exps) if exps else 0.0,
            "avg_pf":  np.mean(pfs) if pfs else 0.0,
            "max_dd":  np.max(dds) if dds else 0.0,
            "avg_wr":  np.mean(wrs) if wrs else 0.0,
        }

    roll_rows = []
    for r_days, st in rolling_stats.items():
        roll_rows.append(
            f"| **{r_days} Days** | {st['avg_exp']:+.3f}R (Min: {st['min_exp']:+.3f}R) | "
            f"{st['avg_pf']:.2f} | {st['max_dd']}% | {st['avg_wr']:.1f}% |"
        )
    roll_rows_str = "\n".join(roll_rows)

    roll_md = f"""# BTCUSD Rolling Performance Report
**Expectancy, Profit Factor, and Drawdown Across Rolling Windows**

## Rolling Performance Metrics

| Window Size | Rolling Expectancy (Mean / Min) | Rolling Profit Factor | Max Rolling Drawdown | Rolling Win Rate |
|:---|:---|:---:|:---:|:---:|
{roll_rows_str}
"""
    with open(REPORTS_DIR / "btc_rolling_performance.md", "w", encoding="utf-8") as f:
        f.write(roll_md)

    # =========================================================================
    # Phase 6 — Market Regime Analysis
    # =========================================================================
    logger.info("Executing Market Regime Analysis...")
    regimes_trend = ["TRENDING", "RANGING"]
    regimes_vol = ["HIGH_VOL", "LOW_VOL", "NORMAL"]
    
    reg_rows = []
    for rt in regimes_trend:
        for rv in regimes_vol:
            subset = [t for t in base_trades if t.regime_trend == rt and t.regime_vol == rv]
            metrics = compute_stats(subset)
            avg_trade = metrics["net_profit"] / metrics["total_trades"] if metrics["total_trades"] > 0 else 0.0
            reg_rows.append(
                f"| {rt} + {rv} | {metrics['total_trades']} | {metrics['win_rate']}% | "
                f"{metrics['expectancy']:+.3f}R | {metrics['profit_factor']:.2f} | "
                f"{metrics['max_drawdown']}% | ${avg_trade:+.2f} |"
            )
    reg_rows_str = "\n".join(reg_rows)

    reg_md = f"""# BTCUSD Market Regime Analysis Report
**Strategy Performance Across Trending, Ranging, and Volatility Regimes**

## Performance by Regime

| Regime | Total Trades | Win Rate | Expectancy | Profit Factor | Max Drawdown | Average Trade |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{reg_rows_str}
"""
    with open(REPORTS_DIR / "btc_regime_analysis.md", "w", encoding="utf-8") as f:
        f.write(reg_md)

    # =========================================================================
    # Phase 7 — Equity Curve Analysis
    # =========================================================================
    logger.info("Executing Equity Curve Analysis...")
    # Calculate monthly returns
    df_trades = pd.DataFrame([{
        "time": t.entry_time, "pnl": t.pnl
    } for t in base_trades])
    
    monthly_str_rows = []
    if not df_trades.empty:
        df_trades['month'] = df_trades['time'].dt.to_period('M')
        monthly_pnl = df_trades.groupby('month')['pnl'].sum()
        for month_period, m_pnl in monthly_pnl.items():
            monthly_str_rows.append(f"| {month_period} | ${m_pnl:+,} |")
    monthly_str = "\n".join(monthly_str_rows)

    equity_md = f"""# BTCUSD Equity Curve Analysis Report
**Equity Curve Statistics, Win/Loss Streaks, and Monthly Returns**

## Replay Curve Statistics

| Parameter | Value |
|:---|---:|
| **Longest Winning Streak** | {m_base["win_streak"]} trades |
| **Longest Losing Streak** | {m_base["loss_streak"]} trades |
| **Peak-to-Peak Recovery Time** | {m_base["recovery_days"]} days |
| **Final Net Profit** | ${m_base["net_profit"]:+,} |
| **Max Drawdown** | {m_base["max_drawdown"]}% |

## Monthly Returns Breakdown

| Month | Net Profit |
|:---|---:|
{monthly_str}
"""
    with open(REPORTS_DIR / "btc_equity_analysis.md", "w", encoding="utf-8") as f:
        f.write(equity_md)

    # =========================================================================
    # Phase 8 — Statistical Validation
    # =========================================================================
    logger.info("Executing Statistical Validation...")
    r_multiples = [t.r_multiple for t in base_trades] if base_trades else [0.0]
    n = len(r_multiples)
    mean_exp = np.mean(r_multiples)
    std_exp  = np.std(r_multiples, ddof=1) if n > 1 else 0.0
    
    if n > 1 and std_exp > 0:
        se = std_exp / math.sqrt(n)
        t_stat, p_val = stats.ttest_1samp(r_multiples, 0.0, alternative='greater')
        margin_of_error = se * stats.t.ppf(0.975, df=n-1)
        ci_95_low = mean_exp - margin_of_error
        ci_95_high = mean_exp + margin_of_error
    else:
        se, t_stat, p_val, ci_95_low, ci_95_high = 0.0, 0.0, 1.0, 0.0, 0.0

    # Bootstrap
    boot_means = []
    for _ in range(5000):
        boot_samp = [random.choice(r_multiples) for _ in range(n)] if r_multiples else [0.0]
        boot_means.append(np.mean(boot_samp))
    boot_ci_low = np.percentile(boot_means, 2.5)
    boot_ci_high = np.percentile(boot_means, 97.5)
    prob_exp_gt_zero = sum(1 for x in boot_means if x > 0.0) / 5000 * 100.0

    stat_md = f"""# BTCUSD Statistical Validation Report
**t-Test Significance and Bootstrap Confidence Intervals**

## Statistical Metrics

| Parameter | Value |
|:---|---:|
| **Sample Size (N)** | {n} |
| **Mean Expectancy** | {mean_exp:+.4f} R |
| **Standard Deviation** | {std_exp:.4f} |
| **Standard Error (SE)** | {se:.4f} |
| **t-Statistic** | {t_stat:.4f} |
| **p-value (One-tailed t-test)** | {p_val:.6f} |
| **95% Confidence Interval (t-dist)** | {ci_95_low:+.4f} to {ci_95_high:+.4f} |
| **Bootstrap 95% Confidence Interval** | {boot_ci_low:+.4f} to {boot_ci_high:+.4f} |
| **Probability Expectancy > 0** | {prob_exp_gt_zero:.2f}% |

---

## Verdict
- **Statistical Verdict**: {"✅ STATISTICALLY SIGNIFICANT EDGE" if p_val < 0.05 else "❌ NOT STATISTICALLY SIGNIFICANT"}
"""
    with open(REPORTS_DIR / "btc_statistical_validation.md", "w", encoding="utf-8") as f:
        f.write(stat_md)

    # =========================================================================
    # Phase 9 — Stress Testing
    # =========================================================================
    logger.info("Executing Stress Testing...")
    stress_scenarios = [
        ("Baseline (Normal)", 1.0, 0.0, 0.0, False),
        ("Double Spread (2.0x)", 2.0, 0.0, 0.0, False),
        ("5-tick Slippage", 1.0, 5.0, 0.0, False),
        ("20% Missed Trades", 1.0, 0.0, 0.20, False),
        ("Latency Delay (Execution delay)", 1.0, 0.0, 0.0, True),
    ]
    
    stress_rows = []
    for name, sp_m, slip, miss_p, lat_d in stress_scenarios:
        sc_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, spread_multiplier=sp_m, slippage_ticks=slip, missed_fill_prob=miss_p, latency_delay=lat_d)
        m = compute_stats(sc_trades)
        stress_rows.append(
            f"| {name} | {m['total_trades']} | {m['win_rate']}% | "
            f"{m['expectancy']:+.3f}R | {m['profit_factor']:.2f} | "
            f"{m['max_drawdown']}% | ${m['net_profit']:+.2f} |"
        )
    stress_rows_str = "\n".join(stress_rows)

    stress_md = f"""# BTCUSD Stress Testing Report
**Performance Under Extreme Spreads, Slippage, and Missing Trades**

## Stress Test Performance

| Scenario | Total Trades | Win Rate | Expectancy | Profit Factor | Max Drawdown | Net Profit |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{stress_rows_str}
"""
    with open(REPORTS_DIR / "btc_stress_test.md", "w", encoding="utf-8") as f:
        f.write(stress_md)

    # =========================================================================
    # Phase 10 — Strategy Certification
    # =========================================================================
    logger.info("Executing Strategy Certification scorecard...")
    rule_exp_ok    = m_base["expectancy"] >= 0.10
    rule_pf_ok     = m_base["profit_factor"] >= 1.20
    rule_dd_ok     = m_base["max_drawdown"] < 12.0
    rule_ruin_ok   = prob_ruin < 5.0
    rule_trades_ok = m_base["total_trades"] >= 1000
    
    # Stable walk-forward: check if any validation expectancy went negative
    wf_stable = all(r["val_exp"] > 0.0 for r in wf_results)
    
    # Stress robust: expectancy under 5-tick slippage >= 0.02R
    slip_5_trades = run_btc_simulation(raw_m15, df_h1, precomputed_m15=pre_m15, precomputed_h1=df_h1, precomputed_bars=pre_bars, slippage_ticks=5.0)
    m_slip_5 = compute_stats(slip_5_trades)
    rule_stress_ok = m_slip_5["expectancy"] >= 0.02

    score = 0
    if rule_exp_ok:    score += 15
    if rule_pf_ok:     score += 15
    if rule_dd_ok:     score += 15
    if rule_ruin_ok:   score += 15
    if rule_trades_ok: score += 15
    if wf_stable:      score += 15
    if rule_stress_ok: score += 10

    cert_passed = (
        rule_exp_ok and rule_pf_ok and rule_dd_ok and 
        rule_ruin_ok and rule_trades_ok and wf_stable and rule_stress_ok
    )

    decision = "Approved for Production Deployment" if cert_passed else "Continue Research"

    cert_md = f"""# BTCUSD Strategy Certification Report
**BTC_P3_OrderFlow Production Readiness Scorecard**

## Certification scorecard

| Requirement | Threshold | Value | Status |
|:---|:---|:---:|:---:|
| **Expectancy** | Expectancy $\ge$ 0.10 R | {m_base["expectancy"]:+.4f} R | {"✅ Pass" if rule_exp_ok else "❌ Fail"} |
| **Profit Factor** | PF $\ge$ 1.20 | {m_base["profit_factor"]:.2f} | {"✅ Pass" if rule_pf_ok else "❌ Fail"} |
| **Drawdown Control** | Max DD < 12% | {m_base["max_drawdown"]}% | {"✅ Pass" if rule_dd_ok else "❌ Fail"} |
| **Minimum Sample Size** | N $\ge$ 1000 | {m_base["total_trades"]} | {"✅ Pass" if rule_trades_ok else "❌ Fail"} |
| **Monte Carlo Risk** | Prob. of Ruin < 5% | {prob_ruin:.2f}% | {"✅ Pass" if rule_ruin_ok else "❌ Fail"} |
| **Walk-Forward Stability** | All Out-of-Sample Exp > 0 | {"Stable" if wf_stable else "Unstable"} | {"✅ Pass" if wf_stable else "❌ Fail"} |
| **Stress Test Robustness** | 5-tick Slip Exp $\ge$ 0.02R | {m_slip_5["expectancy"]:+.3f}R | {"✅ Pass" if rule_stress_ok else "❌ Fail"} |

## Final Certification Decision

> **Production Readiness Score**: **{score}/100**
> **Final Recommendation**: **{decision}**
"""
    with open(REPORTS_DIR / "btc_strategy_certification.md", "w", encoding="utf-8") as f:
        f.write(cert_md)

    # Copy files to brain directory
    for name in [
        "btc_walk_forward.md", "btc_monte_carlo.md", "btc_stress_test.md",
        "btc_parameter_robustness.md", "btc_regime_analysis.md",
        "btc_equity_analysis.md", "btc_statistical_validation.md",
        "btc_strategy_certification.md", "btc_cost_sensitivity.md",
        "btc_rolling_performance.md"
    ]:
        try:
            import shutil
            shutil.copy2(str(REPORTS_DIR / name), str(ROOT.parent / "brain" / "86515f4f-c227-440d-8805-95d41e87d7aa" / name))
        except Exception:
            pass

    logger.info("========================================= ")
    logger.info("   BTCUSD CERTIFICATION BACKTEST COMPLETE ")
    logger.info("   All reports written to reports/        ")
    logger.info("========================================= ")

if __name__ == "__main__":
    run_validation_suite()
