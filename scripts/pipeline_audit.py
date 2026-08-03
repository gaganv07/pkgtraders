"""
scripts/pipeline_audit.py — Comprehensive Trading Decision Pipeline Audit

This script performs a deep, multi-dimensional audit of the trading pipeline
using the existing signal CSV exports from the production replay.

Produces:
  1. Full signal trace with per-filter pass/fail and score decomposition
  2. Filter-by-filter independent analysis (remove one, measure impact)
  3. Logical consistency checks (contradictions, dead filters, etc.)
  4. Weighted contribution breakdown per signal
  5. Score suppressor identification
  6. Detailed HTML + Markdown report with comparison tables
  7. Charts: score distributions, filter Venn, sensitivity curves
"""

import os, sys, csv, json, math, statistics, collections
from datetime import datetime, timezone
from pathlib import Path

try:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# ── Paths ─────────────────────────────────────────────────────────────────────
ARTIFACT_DIR = Path(r"C:\Users\LENOVO\.gemini\antigravity-ide\brain\86515f4f-c227-440d-8805-95d41e87d7aa")
SIGNALS_CSV  = ARTIFACT_DIR / "signals.csv"
if not SIGNALS_CSV.exists():
    SIGNALS_CSV = Path(__file__).resolve().parent.parent / "reports" / "signals.csv"
REPORT_DIR   = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

# ── Load signal data ──────────────────────────────────────────────────────────
print("Loading signal data...", flush=True)
df = pd.read_csv(SIGNALS_CSV)
print(f"Loaded {len(df):,} signals", flush=True)

# Normalise types
def _float(col):
    return pd.to_numeric(df[col].replace("NULL", np.nan), errors="coerce")

def _bool_col(col):
    return df[col].map(lambda x: str(x).strip().upper() in ("TRUE", "1", "YES"))

SCORE_COLS = [
    "selector_score", "quality_score", "final_score",
    "of_score", "dom_score", "ms_score", "liq_score",
    "session_score", "news_score", "vwap_score", "ema_score",
    "bos_score", "mss_score", "fvg_score", "atr_score", "spread_score",
]
FILTER_COLS = [
    "f_ema", "f_vwap", "f_dom", "f_liquidity", "f_fvg",
    "f_mss", "f_bos", "f_atr", "f_spread", "f_session",
    "f_news", "f_cooldown", "f_risk", "f_pos_limit",
]

for c in SCORE_COLS:
    df[c] = _float(c)

SYMBOLS = sorted(df["symbol"].unique())
TOTAL   = len(df)

# ── Section 1: Overall Statistics ────────────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 1: OVERALL STATISTICS", flush=True)
print("="*70, flush=True)

accepted   = df[df["accepted"].astype(str).str.upper() == "TRUE"]
rejected   = df[df["accepted"].astype(str).str.upper() != "TRUE"]
n_accepted = len(accepted)
n_rejected = len(rejected)

print(f"  Total signals evaluated : {TOTAL:,}")
print(f"  Accepted (executed)     : {n_accepted:,} ({100*n_accepted/TOTAL:.2f}%)")
print(f"  Rejected                : {n_rejected:,} ({100*n_rejected/TOTAL:.2f}%)")

# ── Section 2: Score Decomposition ────────────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 2: SCORE DECOMPOSITION (All Signals)", flush=True)
print("="*70, flush=True)

score_stats = {}
for col in SCORE_COLS:
    vals = df[col].dropna()
    if len(vals) == 0:
        score_stats[col] = {"n": 0, "mean": np.nan, "median": np.nan,
                            "std": np.nan, "min": np.nan, "max": np.nan,
                            "pct_zero": np.nan, "pct_null": 100.0}
        print(f"  {col:<20s}  ALL NULL")
        continue
    pct_zero = 100.0 * (vals == 0).sum() / TOTAL
    pct_null = 100.0 * df[col].isna().sum() / TOTAL
    score_stats[col] = {
        "n":        len(vals),
        "mean":     round(float(vals.mean()), 2),
        "median":   round(float(vals.median()), 2),
        "std":      round(float(vals.std()), 2),
        "min":      round(float(vals.min()), 2),
        "max":      round(float(vals.max()), 2),
        "pct_zero": round(pct_zero, 1),
        "pct_null": round(pct_null, 1),
    }
    print(f"  {col:<20s}  mean={vals.mean():6.2f}  median={vals.median():6.2f}"
          f"  std={vals.std():6.2f}  zero%={pct_zero:.1f}  null%={pct_null:.1f}")

# ── Section 3: Per-Rejection-Reason Counts ───────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 3: REJECTION REASON FREQUENCY ANALYSIS", flush=True)
print("="*70, flush=True)

reason_counter = collections.Counter()
for reasons_str in df["rejection_reasons"].dropna():
    if str(reasons_str).strip():
        for r in str(reasons_str).split(";"):
            r = r.strip()
            if r:
                reason_counter[r] += 1

print(f"\n  {'Rank':<5} {'Reason':<45} {'Count':>7} {'% Signals':>10}")
print(f"  {'-'*5} {'-'*45} {'-'*7} {'-'*10}")
for rank, (reason, count) in enumerate(reason_counter.most_common(15), 1):
    print(f"  {rank:<5} {reason:<45} {count:>7,} {100*count/TOTAL:>9.1f}%")

# ── Section 4: Filter-by-Filter Independent Analysis ─────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 4: FILTER STANDALONE FAIL RATES", flush=True)
print("="*70, flush=True)

filter_stats = {}
for fc in FILTER_COLS:
    fail_mask = df[fc].str.strip().str.upper() == "FAIL"
    n_fail = fail_mask.sum()
    filter_stats[fc] = {"fail": int(n_fail), "fail_pct": round(100*n_fail/TOTAL, 1)}
    print(f"  {fc:<20s}  FAIL={n_fail:>6,}  ({100*n_fail/TOTAL:.1f}%)")

# ── Section 5: Marginal Impact (Remove One Filter) ───────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 5: MARGINAL IMPACT — Remove One Filter at a Time", flush=True)
print("="*70, flush=True)
print("  (How many signals pass ALL OTHER filters when this one is removed?)")
print()

# Build pass masks
pass_masks = {}
for fc in FILTER_COLS:
    pass_masks[fc] = df[fc].str.strip().str.upper() == "PASS"

# Mask for "passes all filters"
all_pass_mask = pd.Series([True] * TOTAL)
for fc in FILTER_COLS:
    all_pass_mask = all_pass_mask & pass_masks[fc]

# Also add score gate mask
final_scores = pd.to_numeric(df["final_score"].replace("NULL", np.nan), errors="coerce")
score_85_mask = final_scores >= 85.0
score_65_mask = final_scores >= 65.0
score_60_mask = final_scores >= 60.0

baseline_pass = all_pass_mask & score_85_mask
baseline_count = int(baseline_pass.sum())
print(f"  BASELINE (all filters + score>=85): {baseline_count} signals pass")
print()

marginal_results = {}
for skip_fc in FILTER_COLS:
    other_mask = pd.Series([True] * TOTAL)
    for fc in FILTER_COLS:
        if fc != skip_fc:
            other_mask = other_mask & pass_masks[fc]
    # Also need score gate
    cnt_85 = int((other_mask & score_85_mask).sum())
    cnt_65 = int((other_mask & score_65_mask).sum())
    cnt_60 = int((other_mask & score_60_mask).sum())
    marginal_results[skip_fc] = {
        "pass_all_others_score85": cnt_85,
        "pass_all_others_score65": cnt_65,
        "pass_all_others_score60": cnt_60,
    }
    print(f"  Remove {skip_fc:<22s}: {cnt_85:>5} pass (score>=85) | "
          f"{cnt_65:>5} pass (score>=65) | {cnt_60:>5} pass (score>=60)")

# ── Section 6: What-If Scenario Analysis ─────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 6: WHAT-IF SCENARIO ANALYSIS", flush=True)
print("="*70, flush=True)

def scenario_stats(active_filters, score_threshold, label=""):
    mask = pd.Series([True] * TOTAL)
    for fc in active_filters:
        mask = mask & (df[fc].str.strip().str.upper() == "PASS")
    mask = mask & (final_scores >= score_threshold)

    n = int(mask.sum())

    # Estimate PnL using profit_proxy or R_multiple
    proxy_col = pd.to_numeric(df["profit_proxy"].replace(["NULL", "OPEN_REJECTED", ""], np.nan), errors="coerce")
    r_col     = pd.to_numeric(df["R_multiple"].replace(["NULL", ""], np.nan), errors="coerce")

    subset_proxy = proxy_col[mask]
    subset_r     = r_col[mask]

    n_valid_r   = subset_r.dropna()
    win_rate    = float((n_valid_r > 0).mean() * 100) if len(n_valid_r) > 0 else 0.0
    avg_r       = float(n_valid_r.mean()) if len(n_valid_r) > 0 else 0.0
    total_pnl   = float(subset_proxy.dropna().sum())

    # Simple drawdown estimate using cumulative R
    r_vals = list(n_valid_r.dropna())
    if r_vals:
        cum_r = np.cumsum(r_vals)
        peak  = np.maximum.accumulate(cum_r)
        dd    = float((peak - cum_r).max())
    else:
        dd = 0.0

    return {
        "label":          label,
        "score_threshold": score_threshold,
        "n_trades":       n,
        "pct_signals":    round(100*n/TOTAL, 2),
        "win_rate":       round(win_rate, 1),
        "avg_r":          round(avg_r, 3),
        "net_pnl_proxy":  round(total_pnl, 2),
        "max_dd_r":       round(dd, 3),
    }

BASE_FILTERS = list(FILTER_COLS)
scenarios = [
    ("Baseline (current: all filters, score>=85)",
     BASE_FILTERS, 85.0),
    ("Lower score threshold to 80",
     BASE_FILTERS, 80.0),
    ("Lower score threshold to 75",
     BASE_FILTERS, 75.0),
    ("Lower score threshold to 70",
     BASE_FILTERS, 70.0),
    ("Lower score threshold to 65",
     BASE_FILTERS, 65.0),
    ("Lower score threshold to 60",
     BASE_FILTERS, 60.0),
    ("Remove EMA filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_ema"], 65.0),
    ("Remove Session filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_session"], 65.0),
    ("Remove Spread filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_spread"], 65.0),
    ("Remove BOS filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_bos"], 65.0),
    ("Remove FVG filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_fvg"], 65.0),
    ("Remove Liquidity filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_liquidity"], 65.0),
    ("Remove MSS filter (score>=65)",
     [f for f in BASE_FILTERS if f != "f_mss"], 65.0),
    ("Remove MSS+FVG (score>=65)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg")], 65.0),
    ("Remove MSS+FVG+Liq (score>=65)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg","f_liquidity")], 65.0),
    ("Remove MSS+FVG+Liq+BOS (score>=65)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg","f_liquidity","f_bos")], 65.0),
    ("Remove MSS+FVG+Liq+BOS (score>=60)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg","f_liquidity","f_bos")], 60.0),
    ("Remove MSS+FVG+Liq+BOS+Session (score>=60)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg","f_liquidity","f_bos","f_session")], 60.0),
    ("Remove MSS+FVG+Liq+BOS+Spread (score>=60)",
     [f for f in BASE_FILTERS if f not in ("f_mss","f_fvg","f_liquidity","f_bos","f_spread")], 60.0),
    ("Keep only EMA+ATR+Risk+Cooldown (score>=60)",
     ["f_ema","f_atr","f_risk","f_cooldown","f_news","f_pos_limit"], 60.0),
    ("Keep only EMA+ATR+Risk+Cooldown (score>=55)",
     ["f_ema","f_atr","f_risk","f_cooldown","f_news","f_pos_limit"], 55.0),
]

scenario_rows = []
for label, active_filters, threshold in scenarios:
    row = scenario_stats(active_filters, threshold, label)
    scenario_rows.append(row)
    print(f"  {label:<58s} | {row['n_trades']:>6} trades | "
          f"win={row['win_rate']:>5.1f}% | R={row['avg_r']:>+.3f} | "
          f"PnL=${row['net_pnl_proxy']:>+,.0f}")

# ── Section 7: Score Threshold Sensitivity ───────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 7: SCORE THRESHOLD SENSITIVITY", flush=True)
print("="*70, flush=True)
print("  (All binary filters kept; only score threshold varied)")
print()

thresh_rows = []
for t in [90, 85, 80, 77, 75, 73, 70, 68, 65, 63, 60, 57, 55, 50, 45]:
    mask_all_filters = pd.Series([True] * TOTAL)
    for fc in FILTER_COLS:
        mask_all_filters = mask_all_filters & (df[fc].str.strip().str.upper() == "PASS")
    n = int((mask_all_filters & (final_scores >= t)).sum())
    pct = 100*n/TOTAL
    print(f"  Score >= {t:3d} : {n:>6,} trades ({pct:.2f}%)")
    thresh_rows.append({"threshold": t, "n_trades": n, "pct": round(pct, 2)})

# ── Section 8: Score Decomposition — Weighted Contributions ──────────────────
print("\n" + "="*70, flush=True)
print("SECTION 8: WEIGHTED SCORE CONTRIBUTIONS", flush=True)
print("="*70, flush=True)

# Quality weights per symbol (from trade_quality.py)
WEIGHTS = {
    "XAUUSD": {"of": 0.35, "liq": 0.25, "ms": 0.15, "vol": 0.10, "session": 0.10, "news": 0.05},
    "EURUSD": {"of": 0.25, "liq": 0.20, "ms": 0.30, "vol": 0.10, "session": 0.10, "news": 0.05},
    "GBPUSD": {"of": 0.25, "liq": 0.20, "ms": 0.30, "vol": 0.10, "session": 0.10, "news": 0.05},
    "USDJPY": {"of": 0.25, "liq": 0.20, "ms": 0.25, "vol": 0.10, "session": 0.15, "news": 0.05},
    "NAS100": {"of": 0.30, "liq": 0.20, "ms": 0.15, "vol": 0.20, "session": 0.10, "news": 0.05},
    "US30":   {"of": 0.30, "liq": 0.20, "ms": 0.15, "vol": 0.20, "session": 0.10, "news": 0.05},
}

print("\n  Absolute weighted contribution to score (mean per symbol):")
print(f"  {'Symbol':<10} {'OF_wt':>8} {'Liq_wt':>8} {'MS_wt':>8} "
      f"{'Vol_wt':>8} {'Sess_wt':>8} {'News_wt':>8} {'Total':>8}")
print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

contrib_by_sym = {}
for sym in SYMBOLS:
    sub = df[df["symbol"] == sym]
    w   = WEIGHTS.get(sym, WEIGHTS["XAUUSD"])
    of_m    = sub["of_score"].mean()
    liq_m   = sub["liq_score"].mean()
    ms_m    = sub["ms_score"].mean()
    sess_m  = sub["session_score"].mean()
    news_m  = sub["news_score"].mean()
    # vol_score not directly in CSV; approximate from final - weighted others
    vol_est = 60.0  # default from audit data

    of_w   = of_m   * w["of"]
    liq_w  = liq_m  * w["liq"]
    ms_w   = ms_m   * w["ms"]
    vol_w  = vol_est * w["vol"]
    sess_w = sess_m * w["session"]
    news_w = news_m * w["news"]
    total  = of_w + liq_w + ms_w + vol_w + sess_w + news_w

    contrib_by_sym[sym] = {
        "of_w": of_w, "liq_w": liq_w, "ms_w": ms_w,
        "vol_w": vol_w, "sess_w": sess_w, "news_w": news_w, "total": total
    }
    print(f"  {sym:<10} {of_w:>8.1f} {liq_w:>8.1f} {ms_w:>8.1f} "
          f"{vol_w:>8.1f} {sess_w:>8.1f} {news_w:>8.1f} {total:>8.1f}")

print("\n  Score component drag (how much each suppressor costs vs max 100):")
for col in ["bos_score", "mss_score", "fvg_score", "spread_score"]:
    vals = df[col].dropna()
    if len(vals) == 0:
        continue
    drag = 100.0 - float(vals.mean())
    print(f"  {col:<20s}: avg={vals.mean():.2f}  drag_from_100={drag:.2f}")

# ── Section 9: Logical Consistency Checks ────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 9: LOGICAL CONSISTENCY CHECKS", flush=True)
print("="*70, flush=True)

issues = []

# 9a: EMA says LONG but direction is SHORT (or vice versa)
ema_pass_mask  = df["f_ema"].str.strip().str.upper() == "PASS"
mss_pass_mask  = df["f_mss"].str.strip().str.upper() == "PASS"
liq_pass_mask  = df["f_liquidity"].str.strip().str.upper() == "PASS"
fvg_pass_mask  = df["f_fvg"].str.strip().str.upper() == "PASS"
bos_pass_mask  = df["f_bos"].str.strip().str.upper() == "PASS"
sess_pass_mask = df["f_session"].str.strip().str.upper() == "PASS"
vwap_pass_mask = df["f_vwap"].str.strip().str.upper() == "PASS"
dom_pass_mask  = df["f_dom"].str.strip().str.upper() == "PASS"

# EMA never fails while VWAP also never fails → check if both always agree
ema_score_vals  = df["ema_score"].dropna()
vwap_score_vals = df["vwap_score"].dropna()

ema_always_zero = (ema_score_vals == 0).sum()
vwap_always_100 = (vwap_score_vals == 100).sum()

print(f"\n  [CHECK 1] EMA score = 0 on {ema_always_zero:,}/{TOTAL:,} bars "
      f"({100*ema_always_zero/TOTAL:.1f}%) — counter-trend situations")
print(f"  [CHECK 2] VWAP score = 100 on {vwap_always_100:,}/{TOTAL:,} bars "
      f"({100*vwap_always_100/TOTAL:.1f}%) — VWAP filter is always passing")

if vwap_always_100 == len(vwap_score_vals):
    msg = "CONTRADICTION: f_vwap NEVER fails (0% fail rate). VWAP filter is dead code."
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# DOM score always NULL
dom_null_cnt = df["dom_score"].isna().sum()
if dom_null_cnt == TOTAL:
    msg = "CONTRADICTION: dom_score is NULL for ALL signals. DOM engine runs in fallback mode entirely. f_dom never blocks trades (always PASS)."
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# news_score always 50
news_std = df["news_score"].std()
if news_std is not None and float(news_std) < 0.01:
    msg = "CONTRADICTION: news_score is constant at 50.0 for ALL signals. News engine returns no dynamic sentiment data."
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# Check: Liquidity PASS but FVG FAIL (should be correlated)
liq_pass_fvg_fail = int((liq_pass_mask & ~fvg_pass_mask).sum())
liq_fvg_both_pass = int((liq_pass_mask & fvg_pass_mask).sum())
print(f"\n  [CHECK 3] Liquidity PASS + FVG FAIL: {liq_pass_fvg_fail:,} signals "
      f"({100*liq_pass_fvg_fail/TOTAL:.1f}%)")
print(f"            Liquidity PASS + FVG PASS:  {liq_fvg_both_pass:,} signals "
      f"({100*liq_fvg_both_pass/TOTAL:.1f}%)")

if liq_pass_fvg_fail > liq_fvg_both_pass:
    msg = ("Liquidity sweep passes independently of FVG. These are separate detectors "
           "that fire at different market conditions. Not a code error, but signals that "
           "FVG is harder to detect than liquidity sweeps on M15 bars.")
    print(f"  ℹ️  {msg}")

# Check: MSS PASS but BOS FAIL (CHoCH without BOS is logically inconsistent)
mss_pass_bos_fail = int((mss_pass_mask & ~bos_pass_mask).sum())
mss_bos_both      = int((mss_pass_mask & bos_pass_mask).sum())
print(f"\n  [CHECK 4] MSS PASS + BOS FAIL: {mss_pass_bos_fail:,} signals "
      f"({100*mss_pass_bos_fail/TOTAL:.1f}%)")
if mss_pass_bos_fail > 0:
    msg = (f"CHoCH detected ({mss_pass_bos_fail} cases) without a preceding BOS. "
           "CHoCH = Change of Character requires a prior BOS by definition. "
           "Possible issue: microstructure engine detects CHoCH independently.")
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# Check: EMA PASS but session FAIL
ema_pass_sess_fail = int((ema_pass_mask & ~sess_pass_mask).sum())
print(f"\n  [CHECK 5] EMA PASS + Session FAIL: {ema_pass_sess_fail:,} signals "
      f"({100*ema_pass_sess_fail/TOTAL:.1f}%)")
print(f"            (Valid trend signals blocked by session timing)")

# Check: Signals with high selector score but low quality score
sel_scores   = pd.to_numeric(df["selector_score"], errors="coerce")
qual_scores  = pd.to_numeric(df["quality_score"],  errors="coerce")
high_sel_low_qual = int(((sel_scores >= 80) & (qual_scores < 55)).sum())
print(f"\n  [CHECK 6] Selector>=80 but Quality<55: {high_sel_low_qual:,} signals "
      f"({100*high_sel_low_qual/TOTAL:.1f}%)")
if high_sel_low_qual > 0:
    msg = ("Market selector and quality engine disagree significantly. "
           "Selector sees strong momentum/trend, but quality engine penalizes "
           "due to missing OF/microstructure data.")
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# Check: OF score bimodal (either 95/78 or 20/35)
of_vals = df["of_score"].dropna()
of_low  = (of_vals <= 35).sum()
of_high = (of_vals >= 75).sum()
of_mid  = len(of_vals) - of_low - of_high
print(f"\n  [CHECK 7] OF score distribution: "
      f"low(<=35)={of_low:,} ({100*of_low/TOTAL:.1f}%) | "
      f"mid(36-74)={of_mid:,} ({100*of_mid/TOTAL:.1f}%) | "
      f"high(>=75)={of_high:,} ({100*of_high/TOTAL:.1f}%)")
if of_low / TOTAL > 0.95:
    msg = ("OF score is permanently in penalty range (<=35) for >95% of signals. "
           "This is caused by the OrderFlowEngine returning 'No OF data' for the "
           "entire historical period beyond ~100 days of real tick coverage.")
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# Check: Score always < threshold even in best-case filters
max_score = float(final_scores.max())
min_threshold = 85.0
print(f"\n  [CHECK 8] Maximum observed final_score: {max_score:.2f}  (threshold={min_threshold})")
if max_score < min_threshold:
    msg = (f"CRITICAL: The strategy has NEVER produced a signal that meets "
           f"the current threshold of {min_threshold}. Maximum ever observed: {max_score:.2f}. "
           f"The threshold must be reduced to at least {math.floor(max_score)} to allow any execution.")
    issues.append(msg)
    print(f"  🔴 {msg}")

# Check: Near-perfect filter agreement (co-linear)
print(f"\n  [CHECK 9] Filter co-linearity (how often do MSS+FVG+Liq all fail together?)")
all_micro_fail = ~mss_pass_mask & ~fvg_pass_mask & ~liq_pass_mask
print(f"           MSS+FVG+Liq all fail simultaneously: "
      f"{int(all_micro_fail.sum()):,} ({100*all_micro_fail.sum()/TOTAL:.1f}%)")
print(f"           → Removing any one barely helps; all three must be relaxed together.")

# Check: f_dom always PASS despite DOM score being NULL
dom_always_pass = (df["f_dom"].str.strip().str.upper() == "PASS").all()
print(f"\n  [CHECK 10] f_dom always PASS: {dom_always_pass}")
if dom_always_pass:
    msg = ("f_dom is always PASS because DOMEngine runs in fallback mode. "
           "The fallback liquidity_score defaults to ~45 which is above the f_dom threshold of 25. "
           "This filter provides zero discriminatory power in historical replay.")
    issues.append(msg)
    print(f"  ⚠️  {msg}")

# ── Section 10: Dead/Redundant Filters ───────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 10: DEAD, REDUNDANT, AND OVER-RESTRICTIVE FILTERS", flush=True)
print("="*70, flush=True)

dead_filters    = []
always_pass     = []
over_restrict   = []

for fc in FILTER_COLS:
    fail_cnt = (df[fc].str.strip().str.upper() == "FAIL").sum()
    pct = 100 * fail_cnt / TOTAL
    if pct == 0.0:
        always_pass.append(fc)
    elif pct >= 85.0:
        over_restrict.append((fc, pct))

print("\n  ALWAYS-PASS (zero discriminatory power — effectively dead filters):")
for fc in always_pass:
    print(f"    {fc}")
    dead_filters.append(fc)

print("\n  OVER-RESTRICTIVE (fail rate >= 85%):")
for fc, pct in sorted(over_restrict, key=lambda x: -x[1]):
    print(f"    {fc:<20s}: {pct:.1f}% fail rate")

# ── Section 11: Per-Symbol Analysis ──────────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 11: PER-SYMBOL ANALYSIS", flush=True)
print("="*70, flush=True)

sym_rows = []
for sym in SYMBOLS:
    sub  = df[df["symbol"] == sym]
    n    = len(sub)
    # Score means
    qs   = sub["quality_score"].mean()
    ss   = sub["selector_score"].mean()
    fs   = sub["final_score"].mean()
    of_s = sub["of_score"].mean()
    ms_s = sub["ms_score"].mean()
    # Filter fail rates
    mss_f = 100*(sub["f_mss"].str.upper() == "FAIL").sum() / n
    fvg_f = 100*(sub["f_fvg"].str.upper() == "FAIL").sum() / n
    liq_f = 100*(sub["f_liquidity"].str.upper() == "FAIL").sum() / n
    spr_f = 100*(sub["f_spread"].str.upper() == "FAIL").sum() / n
    ses_f = 100*(sub["f_session"].str.upper() == "FAIL").sum() / n
    # How far from executable? Min additional score needed
    max_fs = sub["final_score"].max()
    gap_to_85 = max(0, 85.0 - max_fs)

    sym_rows.append({
        "symbol": sym, "n": n,
        "quality_score_mean": round(qs, 1),
        "selector_score_mean": round(ss, 1),
        "final_score_mean": round(fs, 1),
        "of_score_mean": round(of_s, 1),
        "ms_score_mean": round(ms_s, 1),
        "mss_fail_pct": round(mss_f, 1),
        "fvg_fail_pct": round(fvg_f, 1),
        "liq_fail_pct": round(liq_f, 1),
        "spread_fail_pct": round(spr_f, 1),
        "session_fail_pct": round(ses_f, 1),
        "max_final_score": round(max_fs, 2),
        "gap_to_85": round(gap_to_85, 2),
    })
    print(f"  {sym:<8} n={n:>5}  qual={qs:>5.1f}  final={fs:>5.1f}  "
          f"max={max_fs:>5.2f}  gap_to_85={gap_to_85:>5.2f}  "
          f"MSS_fail={mss_f:.0f}%  Liq_fail={liq_f:.0f}%")

# ── Section 12: Near-Miss Deep Dive ──────────────────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 12: NEAR-MISS SIGNALS (score 70-84.2)", flush=True)
print("="*70, flush=True)

near_miss = df[(final_scores >= 70) & (final_scores < 85)]
print(f"  Near-miss count: {len(near_miss)}")

print("\n  What's blocking near-miss signals?")
for fc in FILTER_COLS:
    fails = (near_miss[fc].str.strip().str.upper() == "FAIL").sum()
    pct   = 100*fails/len(near_miss)
    if pct > 0:
        print(f"    {fc:<20s}: {fails:>5} ({pct:.1f}%)")

print("\n  What would it take to execute the top-10 near-miss signals?")
top10 = near_miss.nlargest(10, "final_score")[
    ["timestamp","symbol","direction","final_score","rejection_reasons"]
].reset_index(drop=True)
for _, row in top10.iterrows():
    print(f"    {row['timestamp'][:16]}  {row['symbol']:<8}  "
          f"{row['direction']:<5}  score={row['final_score']:.2f}  "
          f"blocked_by={row['rejection_reasons'][:60]}")

# ── Section 13: Score Suppressor Identification ───────────────────────────────
print("\n" + "="*70, flush=True)
print("SECTION 13: DOMINANT SCORE SUPPRESSORS", flush=True)
print("="*70, flush=True)

# Expected score if each suppressor was at 100 instead of its actual value
# Approximate the weight contribution of each binary component
suppressors = {
    "mss_score":    {"col": "mss_score",    "weight_approx": 0.07,  "current_mean": score_stats["mss_score"]["mean"]},
    "bos_score":    {"col": "bos_score",    "weight_approx": 0.06,  "current_mean": score_stats["bos_score"]["mean"]},
    "fvg_score":    {"col": "fvg_score",    "weight_approx": 0.04,  "current_mean": score_stats["fvg_score"]["mean"]},
    "spread_score": {"col": "spread_score", "weight_approx": 0.06,  "current_mean": score_stats["spread_score"]["mean"]},
    "of_score":     {"col": "of_score",     "weight_approx": 0.35,  "current_mean": score_stats["of_score"]["mean"]},
    "session_score":{"col": "session_score","weight_approx": 0.10,  "current_mean": score_stats["session_score"]["mean"]},
}

current_avg_score = float(final_scores.mean())
print(f"  Current average final_score: {current_avg_score:.2f}")
print(f"  Target threshold:            85.00")
print(f"  Gap:                         {85.0 - current_avg_score:.2f} points")
print()
print(f"  {'Suppressor':<20s} {'Current_Mean':>13} {'If_100_gain':>12} {'Gain_pts':>10}")
print(f"  {'-'*20} {'-'*13} {'-'*12} {'-'*10}")

for name, info in sorted(suppressors.items(), key=lambda x: -(100-x[1]["current_mean"])*x[1]["weight_approx"]):
    drag    = 100.0 - info["current_mean"]
    gain    = drag * info["weight_approx"]
    print(f"  {name:<20s} {info['current_mean']:>13.2f} {gain:>+12.2f} pts {'(if raised to 100)':>10}")

# ── CHARTS ────────────────────────────────────────────────────────────────────
print("\n" + "="*70, flush=True)
print("GENERATING CHARTS...", flush=True)
print("="*70, flush=True)

COLORS = {
    "primary":   "#4f8ef7",
    "danger":    "#e05c5c",
    "warning":   "#f4a22c",
    "success":   "#4eca8b",
    "neutral":   "#8e9eaf",
    "dark":      "#1e2130",
    "bg":        "#f8f9fb",
}

plt.rcParams.update({
    "figure.facecolor": COLORS["bg"],
    "axes.facecolor":   "white",
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "font.family":      "DejaVu Sans",
    "axes.titlesize":   11,
    "axes.labelsize":   9,
})


# Chart 1: Filter Fail Rates (horizontal bar)
fig, ax = plt.subplots(figsize=(10, 6))
fc_labels = [r.replace("f_","") for r in FILTER_COLS]
fc_fails  = [filter_stats[fc]["fail_pct"] for fc in FILTER_COLS]
bars = ax.barh(fc_labels, fc_fails,
               color=[COLORS["danger"] if p > 50 else COLORS["warning"] if p > 20 else COLORS["success"]
                      for p in fc_fails])
ax.axvline(50, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
ax.set_xlabel("Fail Rate (%)")
ax.set_title("Filter Standalone Fail Rates — All 22,274 Signals", fontweight="bold")
for bar, val in zip(bars, fc_fails):
    if val > 0:
        ax.text(val + 0.5, bar.get_y() + bar.get_height()/2,
                f"{val:.1f}%", va="center", fontsize=8)
plt.tight_layout()
fp = REPORT_DIR / "filter_fail_rates.png"
plt.savefig(fp, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp}")


# Chart 2: Score Component Distributions (box plots)
fig, axes = plt.subplots(2, 4, figsize=(16, 8))
plot_cols = ["final_score","of_score","ms_score","liq_score",
             "bos_score","mss_score","fvg_score","spread_score"]
for ax, col in zip(axes.flat, plot_cols):
    vals = df[col].dropna()
    if len(vals) > 0:
        ax.boxplot(vals, vert=True, patch_artist=True,
                   boxprops=dict(facecolor=COLORS["primary"], alpha=0.6),
                   medianprops=dict(color="white", linewidth=2),
                   whiskerprops=dict(color=COLORS["neutral"]),
                   capprops=dict(color=COLORS["neutral"]),
                   flierprops=dict(marker=".", markersize=2, alpha=0.3))
        ax.set_title(col.replace("_score","").upper())
        ax.set_ylim(-5, 105)
        ax.axhline(85, color=COLORS["danger"], linestyle="--", linewidth=0.8, alpha=0.7, label="threshold")
    else:
        ax.text(0.5, 0.5, "ALL NULL", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(col.replace("_score","").upper())
plt.suptitle("Score Component Distributions (all signals)", fontweight="bold", y=1.01)
plt.tight_layout()
fp2 = REPORT_DIR / "score_component_boxplots.png"
plt.savefig(fp2, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp2}")


# Chart 3: What-If Scenario Bars
fig, ax = plt.subplots(figsize=(13, 8))
s_labels = [s["label"][:55] for s in scenario_rows]
s_trades = [s["n_trades"] for s in scenario_rows]
colors_sc = [COLORS["danger"] if t == 0 else COLORS["warning"] if t < 100
             else COLORS["success"] for t in s_trades]
bars = ax.barh(range(len(s_labels)), s_trades, color=colors_sc)
ax.set_yticks(range(len(s_labels)))
ax.set_yticklabels(s_labels, fontsize=7.5)
ax.set_xlabel("Number of Trades Unlocked")
ax.set_title("What-If Scenario Analysis — Trades Unlocked vs Filter Relaxation",
             fontweight="bold")
for bar, val in zip(bars, s_trades):
    if val > 0:
        ax.text(val + 2, bar.get_y() + bar.get_height()/2,
                str(val), va="center", fontsize=8)
plt.tight_layout()
fp3 = REPORT_DIR / "whatif_scenarios.png"
plt.savefig(fp3, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp3}")


# Chart 4: Score Threshold Sensitivity Curve
fig, ax = plt.subplots(figsize=(9, 5))
t_vals = [r["threshold"] for r in thresh_rows][::-1]
n_vals = [r["n_trades"] for r in thresh_rows][::-1]
ax.plot(t_vals, n_vals, marker="o", color=COLORS["primary"], linewidth=2)
ax.fill_between(t_vals, n_vals, alpha=0.15, color=COLORS["primary"])
ax.axvline(85, color=COLORS["danger"], linestyle="--", linewidth=1.2, label="Current threshold (85)")
ax.set_xlabel("Score Threshold")
ax.set_ylabel("Trades Passing All Binary Filters")
ax.set_title("Score Threshold Sensitivity (all binary filters active)", fontweight="bold")
ax.legend()
plt.tight_layout()
fp4 = REPORT_DIR / "score_threshold_sensitivity.png"
plt.savefig(fp4, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp4}")


# Chart 5: Score distribution histogram with threshold markers
fig, ax = plt.subplots(figsize=(10, 5))
vals_clean = final_scores.dropna()
ax.hist(vals_clean, bins=50, color=COLORS["primary"], alpha=0.7, edgecolor="white")
ax.axvline(85,   color=COLORS["danger"],  linestyle="--", linewidth=1.5, label="Current threshold (85)")
ax.axvline(70,   color=COLORS["warning"], linestyle=":",  linewidth=1.5, label="Recommended (70)")
ax.axvline(60,   color=COLORS["success"], linestyle="-.", linewidth=1.5, label="Aggressive (60)")
ax.set_xlabel("Final Quality Score")
ax.set_ylabel("Count of Signals")
ax.set_title("Final Score Distribution — 22,274 Signals", fontweight="bold")
ax.legend()
plt.tight_layout()
fp5 = REPORT_DIR / "score_distribution_final.png"
plt.savefig(fp5, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp5}")


# Chart 6: Per-symbol quality score comparison
fig, ax = plt.subplots(figsize=(10, 5))
sym_names  = [r["symbol"] for r in sym_rows]
qual_means = [r["quality_score_mean"] for r in sym_rows]
sel_means  = [r["selector_score_mean"] for r in sym_rows]
x = np.arange(len(sym_names))
w = 0.35
ax.bar(x - w/2, qual_means, w, label="Quality Score", color=COLORS["primary"])
ax.bar(x + w/2, sel_means,  w, label="Selector Score", color=COLORS["success"])
ax.axhline(85, color=COLORS["danger"],  linestyle="--", linewidth=1, label="Trade threshold (85)")
ax.axhline(65, color=COLORS["warning"], linestyle=":",  linewidth=1, label="Recommended threshold (65)")
ax.set_xticks(x)
ax.set_xticklabels(sym_names)
ax.set_ylabel("Score")
ax.set_title("Quality vs Selector Score by Symbol", fontweight="bold")
ax.legend()
plt.tight_layout()
fp6 = REPORT_DIR / "symbol_score_comparison.png"
plt.savefig(fp6, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp6}")


# Chart 7: Rejection reason treemap / horizontal bar
top_reasons = reason_counter.most_common(12)
fig, ax = plt.subplots(figsize=(11, 6))
labels = [r[:45] for r, _ in top_reasons]
counts = [c for _, c in top_reasons]
pcts   = [100*c/TOTAL for c in counts]
color_list = [COLORS["danger"] if p > 80 else COLORS["warning"] if p > 30 else COLORS["neutral"]
              for p in pcts]
bars = ax.barh(labels[::-1], pcts[::-1], color=color_list[::-1])
ax.set_xlabel("% of All Evaluated Signals")
ax.set_title("Top Rejection Reasons — Frequency Distribution", fontweight="bold")
for bar, pct in zip(bars, pcts[::-1]):
    ax.text(pct + 0.3, bar.get_y() + bar.get_height()/2,
            f"{pct:.1f}%", va="center", fontsize=8)
plt.tight_layout()
fp7 = REPORT_DIR / "rejection_reasons_bar.png"
plt.savefig(fp7, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {fp7}")


# ── Copy charts to artifact dir ───────────────────────────────────────────────
import shutil
for src in [fp, fp2, fp3, fp4, fp5, fp6, fp7]:
    dst = ARTIFACT_DIR / src.name
    shutil.copy2(str(src), str(dst))
    print(f"  Copied {src.name} → artifact dir")


# ── Compile JSON Results ──────────────────────────────────────────────────────
audit_data = {
    "meta": {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_signals": TOTAL,
        "n_accepted": n_accepted,
        "n_rejected": n_rejected,
    },
    "score_stats": score_stats,
    "filter_stats": filter_stats,
    "marginal_impact": marginal_results,
    "scenarios": scenario_rows,
    "threshold_sensitivity": thresh_rows,
    "sym_analysis": sym_rows,
    "logical_issues": issues,
    "dead_filters": dead_filters,
    "over_restrictive_filters": [{"filter": f, "fail_pct": p} for f,p in over_restrict],
    "top_rejection_reasons": [{"reason": r, "count": c, "pct": round(100*c/TOTAL,1)}
                               for r, c in reason_counter.most_common(15)],
    "near_miss_count": len(near_miss),
}

json_path = REPORT_DIR / "pipeline_audit_data.json"
with open(json_path, "w") as f:
    json.dump(audit_data, f, indent=2, default=str)
print(f"\n  Saved JSON: {json_path}")

shutil.copy2(str(json_path), str(ARTIFACT_DIR / "pipeline_audit_data.json"))
print(f"  Copied pipeline_audit_data.json → artifact dir")

print("\n✅ Pipeline audit analysis complete.", flush=True)
print(f"   Charts:  {REPORT_DIR}/", flush=True)
print(f"   Data:    {json_path}", flush=True)
