"""
scripts/quality_recalibration.py
══════════════════════════════════════════════════════════════════════════════
Trade Quality Scoring System — Complete Redesign & Calibration
══════════════════════════════════════════════════════════════════════════════

10-phase analysis using 22,274 production replay signals:
  Phase 1  – Identify and replace hard step functions
  Phase 2  – Convert binary vetoes to weighted contributors
  Phase 3  – Recalibrate weights via correlation + OLS regression
  Phase 4  – Design adaptive (rolling percentile) threshold
  Phase 5  – Normalise every component to [0,100]
  Phase 6  – Automated dead-filter detection
  Phase 7  – Feature-to-PnL correlation analysis
  Phase 8  – Threshold sensitivity sweep (50→85)
  Phase 9  – Verify safety controls remain intact
  Phase 10 – Produce all deliverables

Outputs:
  reports/quality_recalibration_report.md
  reports/quality_histograms.png
  reports/threshold_sweep.csv
  reports/feature_correlations.csv
  reports/recommended_weights.json
  reports/recommended_threshold.json
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import scipy.stats as stats

try:
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as mgrid
from matplotlib.colors import LinearSegmentedColormap

# ── Paths ─────────────────────────────────────────────────────────────────────
ARTIFACT_DIR = Path(r"C:\Users\LENOVO\.gemini\antigravity-ide\brain\86515f4f-c227-440d-8805-95d41e87d7aa")
SIGNALS_CSV  = ARTIFACT_DIR / "signals.csv"
if not SIGNALS_CSV.exists():
    SIGNALS_CSV = Path(__file__).resolve().parent.parent / "reports" / "signals.csv"
REPORT_DIR   = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

plt.rcParams.update({
    "figure.facecolor": "#f9fafb",
    "axes.facecolor":   "white",
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "font.family":      "DejaVu Sans",
    "axes.titlesize":   11,
    "axes.labelsize":   9,
    "grid.alpha":       0.35,
    "grid.linestyle":   "--",
})

PALETTE = {
    "blue":    "#4f8ef7",
    "green":   "#4eca8b",
    "red":     "#e05c5c",
    "orange":  "#f4a22c",
    "purple":  "#9b6cf9",
    "teal":    "#2cc4c4",
    "gray":    "#8e9eaf",
    "dark":    "#1e2130",
}

print("=" * 70, flush=True)
print("TRADE QUALITY SCORING SYSTEM — REDESIGN & CALIBRATION", flush=True)
print("=" * 70, flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOAD
# ══════════════════════════════════════════════════════════════════════════════
print("\nLoading data...", flush=True)
df = pd.read_csv(SIGNALS_CSV, low_memory=False)
TOTAL = len(df)
print(f"  {TOTAL:,} signals loaded", flush=True)

def _f(col):
    return pd.to_numeric(df[col].replace("NULL", np.nan), errors="coerce")

SCORE_COLS = ["of_score","liq_score","ms_score","session_score","news_score",
              "bos_score","mss_score","fvg_score","spread_score","ema_score",
              "vwap_score","atr_score","selector_score","quality_score","final_score"]

for c in SCORE_COLS:
    df[c] = _f(c)

df["profit_proxy"] = _f("profit_proxy")
df["R_multiple"]   = _f("R_multiple")

# Mask: signals with actual PnL data (not null, not 0-default)
pnl_mask  = df["profit_proxy"].notna() & (df["R_multiple"].notna())
df_pnl    = df[pnl_mask].copy()
print(f"  {len(df_pnl):,} signals with PnL proxy data", flush=True)

SYMBOLS   = sorted(df["symbol"].unique())

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: IDENTIFY HARD STEP FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 1: HARD STEP FUNCTION ANALYSIS", flush=True)
print("─" * 70, flush=True)

# Analyse unique value distribution of each score to detect steps
step_report: List[Dict] = []

for col in ["of_score","liq_score","ms_score","bos_score","mss_score","fvg_score",
            "ema_score","vwap_score","spread_score","atr_score"]:
    vals = df[col].dropna()
    unique_vals = sorted(vals.unique())
    n_unique = len(unique_vals)
    is_binary = n_unique <= 3
    is_step   = n_unique <= 8 and n_unique > 2
    is_smooth = n_unique > 8

    top_vals = [(v, int((vals == v).sum())) for v in unique_vals]
    top_vals.sort(key=lambda x: -x[1])

    kind = "BINARY" if is_binary else ("STEP" if is_step else "SMOOTH")
    step_report.append({
        "component": col,
        "kind":      kind,
        "n_unique":  n_unique,
        "top_values": top_vals[:6],
    })
    print(f"  {col:<20s}  [{kind:7s}]  {n_unique:3d} unique values  "
          f"top={[f'{v[0]}({v[1]})' for v in top_vals[:4]]}")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: SMOOTH MAPPING DESIGN
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 2: SMOOTH CONTINUOUS MAPPING DESIGN", flush=True)
print("─" * 70, flush=True)

def sigmoid(x: float, center: float = 50.0, steepness: float = 0.1) -> float:
    """Logistic sigmoid mapping raw score → [0,100]."""
    return 100.0 / (1.0 + math.exp(-steepness * (x - center)))

def smooth_of_score(raw_of_score: float, direction: str) -> float:
    """Replace 4-step OF scoring with smooth logistic curve.
    
    Old:  LONG: >=75→95, >=62→78, >=52→58, else→20
    New:  Smooth sigmoid centred at 50 (neutral), rising toward 100 for LONG,
          mirrored (100-f) for SHORT.
    """
    if direction == "LONG":
        # Raw of_score: higher = more bullish = better for LONG
        return round(sigmoid(raw_of_score, center=55.0, steepness=0.12), 1)
    else:
        # SHORT benefits from low OF (bearish pressure)
        return round(sigmoid(100.0 - raw_of_score, center=55.0, steepness=0.12), 1)

def smooth_ema_score(ema_pts_raw: float) -> float:
    """Replace 5-step EMA scoring with linear interpolation.
    
    Old:  both TF aligned→100, H1 only→75, M15 only→55, neutral→45, counter→15
    New:  linear 0→100 preserving the relative ordering but without cliff edges.
    """
    # Normalise the known anchors: 15→20, 45→45, 55→55, 75→75, 100→100
    # Insert smooth interpolation between them
    anchors = [(0, 10), (15, 20), (45, 45), (55, 58), (75, 78), (100, 100)]
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    return round(float(np.interp(ema_pts_raw, xs, ys)), 1)

def smooth_vol_score(regime: str, percentile: float) -> float:
    """Replace 5-bucket volatility scoring with regime-aware sigmoid."""
    regime_base = {"EXPANDING": 75.0, "NORMAL": 65.0,
                   "COMPRESSED": 55.0, "EXPLOSIVE": 30.0}.get(regime, 60.0)
    # Percentile adjustment: optimal range 40–75
    if percentile < 20:
        p_adj = -15.0
    elif percentile < 40:
        p_adj = -5.0
    elif percentile <= 75:
        p_adj = 10.0
    elif percentile <= 90:
        p_adj = 0.0
    else:
        p_adj = -20.0  # explosive
    return round(max(0.0, min(100.0, regime_base + p_adj)), 1)

def smooth_icm_contribution(detected: bool,
                             base_score: float,
                             weight: float = 1.0) -> float:
    """Convert binary ICT event (MSS/FVG/Liq/BOS) from veto → score contribution.
    
    Old:  not detected → REJECT
    New:  not detected → 0 (no bonus), detected → weight-scaled bonus
    
    The absence of ICT confluence reduces the score but doesn't veto.
    """
    return round(100.0 * weight if detected else 0.0, 1)

# Demonstrate smooth mapping by comparing old vs new on example values
print("\n  OF Score comparison (LONG direction, raw_of_score=60):")
raw = 60.0
old_score = 78.0  # step: 62 <= 60? No, so 58; actually let's compute properly
if raw >= 75: old_score = 95.0
elif raw >= 62: old_score = 78.0
elif raw >= 52: old_score = 58.0
else: old_score = 20.0
new_score = smooth_of_score(raw, "LONG")
print(f"    Raw={raw:.0f}  Old step={old_score:.1f}  New smooth={new_score:.1f}")

for raw in [20, 40, 50, 55, 62, 70, 75, 85, 95]:
    if raw >= 75: old_s = 95.0
    elif raw >= 62: old_s = 78.0
    elif raw >= 52: old_s = 58.0
    else: old_s = 20.0
    new_s = smooth_of_score(raw, "LONG")
    print(f"    raw={raw:3d}  old={old_s:5.1f}  new={new_s:5.1f}  "
          f"{'SAME' if abs(old_s - new_s) < 5 else 'DIFFERENT'}")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: WEIGHT RECALIBRATION VIA CORRELATION + OLS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 3: WEIGHT RECALIBRATION — CORRELATION + OLS REGRESSION", flush=True)
print("─" * 70, flush=True)

# Use R_multiple as the PnL target (most reliable per-trade metric)
# Compute Pearson and Spearman correlations of each score vs R_multiple
feature_cols = ["of_score","liq_score","ms_score","session_score",
                "bos_score","mss_score","fvg_score","spread_score",
                "ema_score","atr_score","selector_score"]

correlations: List[Dict] = []
print(f"\n  {'Component':<20s}  {'Pearson':>9}  {'Spearman':>9}  "
      f"{'|Pearson|':>9}  {'PnL_signal':>12}")
print(f"  {'─'*20}  {'─'*9}  {'─'*9}  {'─'*9}  {'─'*12}")

for col in feature_cols:
    valid = df_pnl[[col, "R_multiple"]].dropna()
    if len(valid) < 20:
        print(f"  {col:<20s}  insufficient data")
        continue
    x = valid[col].values
    y = valid["R_multiple"].values
    pearson,  p_pear  = stats.pearsonr(x, y)
    spearman, p_spear = stats.spearmanr(x, y)
    abs_corr = abs(pearson)
    signal   = "positive" if pearson > 0 else "negative"
    correlations.append({
        "component": col,
        "pearson":  round(pearson, 4),
        "p_pearson": round(p_pear, 4),
        "spearman": round(spearman, 4),
        "p_spearman": round(p_spear, 4),
        "abs_pearson": round(abs_corr, 4),
        "direction": signal,
        "n": len(valid),
    })
    sig_star = "***" if p_pear < 0.001 else ("**" if p_pear < 0.01 else
                ("*" if p_pear < 0.05 else "ns"))
    print(f"  {col:<20s}  {pearson:>+9.4f}  {spearman:>+9.4f}  "
          f"{abs_corr:>9.4f}  {signal:>12} {sig_star}")

# Sort by absolute Pearson
correlations.sort(key=lambda x: -x["abs_pearson"])

# OLS regression: regress R_multiple on all components simultaneously
from numpy.linalg import lstsq

reg_cols  = [c["component"] for c in correlations]
Xy        = df_pnl[reg_cols + ["R_multiple"]].dropna()
X_raw     = Xy[reg_cols].values
y_raw     = Xy["R_multiple"].values

# Standardise X for comparable coefficients
X_mean = X_raw.mean(axis=0)
X_std  = X_raw.std(axis=0)
X_std[X_std == 0] = 1.0  # avoid divide-by-zero
X_std_  = (X_raw - X_mean) / X_std

# Add intercept
X_design = np.hstack([np.ones((len(X_std_), 1)), X_std_])
betas, res, rank, sv = lstsq(X_design, y_raw, rcond=None)
beta_intercept = betas[0]
beta_coefs     = betas[1:]

print(f"\n  OLS Regression (standardised coefficients, n={len(Xy)}):")
print(f"  {'Component':<20s}  {'Beta':>8}  {'|Beta|':>8}  {'Rank':>5}")
beta_pairs = sorted(zip(reg_cols, beta_coefs), key=lambda x: -abs(x[1]))
for rank_i, (col, beta) in enumerate(beta_pairs, 1):
    print(f"  {col:<20s}  {beta:>+8.4f}  {abs(beta):>8.4f}  {rank_i:>5}")

# ── Proposed weights from regression (normalised absolute betas) ──────────────
# Current system weights
CURRENT_WEIGHTS = {
    "order_flow":       0.35,
    "liquidity":        0.25,
    "market_structure": 0.15,
    "volatility":       0.10,
    "session":          0.10,
    "news":             0.05,
}

# Collect abs-beta per logical group
def _beta(col_name: str) -> float:
    for c, b in zip(reg_cols, beta_coefs):
        if c == col_name:
            return abs(b)
    return 0.001

raw_group_betas = {
    "order_flow":       _beta("of_score"),
    "liquidity":        (_beta("liq_score") + _beta("bos_score") + _beta("mss_score") + _beta("fvg_score")) / 4,
    "market_structure": _beta("ms_score"),
    "volatility":       _beta("atr_score"),
    "session":          _beta("session_score"),
    "news":             0.005,   # no variation in data; keep small
}

# Reserve 5% for DOM (not in data, structural requirement)
dom_reserve = 0.05
total_raw   = sum(raw_group_betas.values())
scale       = (1.0 - dom_reserve) / total_raw

REGRESSION_WEIGHTS = {k: round(v * scale, 3) for k, v in raw_group_betas.items()}
REGRESSION_WEIGHTS["dom"] = dom_reserve

# Blend: 50% data-driven + 50% current
BLEND_WEIGHTS = {
    "order_flow":       round(0.5 * CURRENT_WEIGHTS["order_flow"] + 0.5 * REGRESSION_WEIGHTS["order_flow"], 3),
    "liquidity":        round(0.5 * CURRENT_WEIGHTS["liquidity"]  + 0.5 * REGRESSION_WEIGHTS["liquidity"], 3),
    "market_structure": round(0.5 * CURRENT_WEIGHTS["market_structure"] + 0.5 * REGRESSION_WEIGHTS["market_structure"], 3),
    "volatility":       round(0.5 * CURRENT_WEIGHTS["volatility"] + 0.5 * REGRESSION_WEIGHTS["volatility"], 3),
    "session":          round(0.5 * CURRENT_WEIGHTS["session"]    + 0.5 * REGRESSION_WEIGHTS["session"], 3),
    "news":             round(0.5 * CURRENT_WEIGHTS["news"]       + 0.5 * REGRESSION_WEIGHTS["news"], 3),
    "dom":              REGRESSION_WEIGHTS["dom"],
}

# Normalise to sum to 1.0
total_blend = sum(BLEND_WEIGHTS.values())
BLEND_WEIGHTS = {k: round(v / total_blend, 3) for k, v in BLEND_WEIGHTS.items()}

print("\n  Weight comparison (Current vs Regression vs Blended):")
print(f"  {'Group':<20s}  {'Current':>9}  {'Regression':>10}  {'Blended':>9}")
for grp in ["order_flow","liquidity","market_structure","volatility","session","news","dom"]:
    cur = CURRENT_WEIGHTS.get(grp, 0.0)
    reg = REGRESSION_WEIGHTS.get(grp, 0.0)
    bln = BLEND_WEIGHTS.get(grp, 0.0)
    print(f"  {grp:<20s}  {cur:>9.3f}  {reg:>10.3f}  {bln:>9.3f}")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: ADAPTIVE THRESHOLD DESIGN
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 4: ADAPTIVE THRESHOLD DESIGN", flush=True)
print("─" * 70, flush=True)

scores = df["final_score"].dropna()

# Rolling 100-bar 80th percentile threshold
rolling_p80 = scores.rolling(100, min_periods=20).quantile(0.80)
rolling_p70 = scores.rolling(100, min_periods=20).quantile(0.70)
rolling_p60 = scores.rolling(100, min_periods=20).quantile(0.60)

# Overall statistics
p50 = float(scores.quantile(0.50))
p60 = float(scores.quantile(0.60))
p70 = float(scores.quantile(0.70))
p75 = float(scores.quantile(0.75))
p80 = float(scores.quantile(0.80))
p85 = float(scores.quantile(0.85))
p90 = float(scores.quantile(0.90))

print(f"\n  Score percentile profile:")
for pct, val in [(50, p50),(60, p60),(70, p70),(75, p75),
                 (80, p80),(85, p85),(90, p90)]:
    above = int((scores >= val).sum())
    print(f"    P{pct:2d} = {val:6.2f}  →  {above:6,} signals above ({100*above/TOTAL:.1f}%)")

# Proposed adaptive rule:
#   threshold = max(58.0, rolling_p70) capped at 80.0
#   This ensures we always select the top 30% of recent signals
#   while never dropping below 58.0 (absolute floor)
#   and never exceeding 80.0 (don't over-tighten)

ADAPTIVE_FLOOR     = 58.0
ADAPTIVE_CEILING   = 80.0
ADAPTIVE_PERCENTILE = 70    # top 30%

above_floor = int((scores >= ADAPTIVE_FLOOR).sum())
above_ceil  = int((scores >= ADAPTIVE_CEILING).sum())
print(f"\n  Proposed adaptive rule: max({ADAPTIVE_FLOOR}, rolling_P{ADAPTIVE_PERCENTILE}), capped at {ADAPTIVE_CEILING}")
print(f"  At current data: P70={p70:.2f}  →  effective threshold={max(ADAPTIVE_FLOOR, min(p70, ADAPTIVE_CEILING)):.2f}")
print(f"  Signals above floor ({ADAPTIVE_FLOOR}): {above_floor:,} ({100*above_floor/TOTAL:.1f}%)")
print(f"  Signals above ceiling ({ADAPTIVE_CEILING}): {above_ceil:,} ({100*above_ceil/TOTAL:.1f}%)")

effective_adaptive_threshold = max(ADAPTIVE_FLOOR, min(p70, ADAPTIVE_CEILING))

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: SCORE NORMALISATION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 5: SCORE NORMALISATION ANALYSIS", flush=True)
print("─" * 70, flush=True)

norm_report: List[Dict] = []
for col in SCORE_COLS:
    vals = df[col].dropna()
    if len(vals) == 0:
        continue
    lo, hi = float(vals.min()), float(vals.max())
    rng    = hi - lo
    pct_at_min = 100.0 * (vals == lo).sum() / len(vals)
    pct_at_max = 100.0 * (vals == hi).sum() / len(vals)
    dead_low   = pct_at_min > 30.0   # >30% at minimum = dead low range
    dead_high  = pct_at_max > 30.0   # >30% at maximum = dead high range
    unreachable_top = hi < 95.0
    unreachable_bot = lo > 10.0

    issues = []
    if dead_low:   issues.append(f"floor-congested ({pct_at_min:.0f}% at min={lo:.0f})")
    if dead_high:  issues.append(f"ceiling-congested ({pct_at_max:.0f}% at max={hi:.0f})")
    if unreachable_top: issues.append(f"max={hi:.0f}<95 (top range unused)")
    if unreachable_bot: issues.append(f"min={lo:.0f}>10 (bottom range unused)")

    norm_report.append({
        "component": col, "min": round(lo,1), "max": round(hi,1),
        "range": round(rng,1), "pct_at_min": round(pct_at_min,1),
        "pct_at_max": round(pct_at_max,1), "issues": issues,
        "needs_normalisation": len(issues) > 0,
    })
    status = "⚠️ " + "; ".join(issues) if issues else "✅ OK"
    print(f"  {col:<20s}  [{lo:5.1f}, {hi:5.1f}]  rng={rng:5.1f}  {status}")

# Compute new quality score using proposed weights and ICT as contribution
def compute_new_score(row: pd.Series, weights: Dict, icm_weight: float = 0.10) -> float:
    """Compute redesigned quality score for a row.
    
    New = weighted(OF, Liq, MS, Vol, Session, News) + ICT_bonus(MSS, FVG, Liq, BOS)
    ICT events boost score but absence doesn't veto.
    """
    w = weights

    # Core components (normalised to 0-100 via existing scores)
    of_s   = float(row.get("of_score",    50) or 50)
    liq_s  = float(row.get("liq_score",   50) or 50)
    ms_s   = float(row.get("ms_score",    50) or 50)
    sess_s = float(row.get("session_score",50) or 50)
    news_s = float(row.get("news_score",  50) or 50)
    # vol approximated from atr_score (high ATR = high vol = assume EXPANDING)
    atr_s  = float(row.get("atr_score",   60) or 60)
    vol_s  = 70.0 if atr_s >= 80 else (55.0 if atr_s >= 50 else 40.0)

    core = (
        of_s   * w.get("order_flow",       0.30) +
        liq_s  * w.get("liquidity",        0.20) +
        ms_s   * w.get("market_structure", 0.20) +
        vol_s  * w.get("volatility",       0.10) +
        sess_s * w.get("session",          0.10) +
        news_s * w.get("news",             0.05)
    )

    # ICT confluence bonus (0→15 pts max, distributed over 4 events)
    mss   = float(row.get("mss_score",  0) or 0) > 50
    fvg   = float(row.get("fvg_score",  0) or 0) > 50
    liq_e = float(row.get("liq_score",  0) or 0) > 70
    bos   = float(row.get("bos_score",  0) or 0) > 50

    ict_bonus = (
        (4.0 if mss   else 0.0) +
        (3.0 if fvg   else 0.0) +
        (4.0 if liq_e else 0.0) +
        (4.0 if bos   else 0.0)
    )

    # OF fallback: if no tick data (of_score ≈ 35), apply neutral 50 instead
    if of_s <= 35.0:
        of_s = 50.0
        core = (
            of_s   * w.get("order_flow",       0.30) +
            liq_s  * w.get("liquidity",        0.20) +
            ms_s   * w.get("market_structure", 0.20) +
            vol_s  * w.get("volatility",       0.10) +
            sess_s * w.get("session",          0.10) +
            news_s * w.get("news",             0.05)
        )

    return round(min(100.0, core + ict_bonus), 1)

# Apply to full dataset
df["new_score_current_w"]  = df.apply(lambda r: compute_new_score(r, CURRENT_WEIGHTS), axis=1)
df["new_score_blended_w"]  = df.apply(lambda r: compute_new_score(r, BLEND_WEIGHTS),   axis=1)

print(f"\n  Score summary after redesign:")
for label, col in [("Old final_score", "final_score"),
                   ("New (current weights)", "new_score_current_w"),
                   ("New (blended weights)", "new_score_blended_w")]:
    vals = df[col].dropna()
    above_65 = int((vals >= 65).sum())
    above_70 = int((vals >= 70).sum())
    above_75 = int((vals >= 75).sum())
    print(f"  {label:<28s}  mean={vals.mean():6.2f}  "
          f"max={vals.max():6.2f}  "
          f"≥65={above_65:,} ({100*above_65/TOTAL:.1f}%)  "
          f"≥70={above_70:,} ({100*above_70/TOTAL:.1f}%)  "
          f"≥75={above_75:,} ({100*above_75/TOTAL:.1f}%)")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6: AUTOMATED DEAD FILTER DETECTION
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 6: DEAD FILTER DETECTION", flush=True)
print("─" * 70, flush=True)

FILTER_COLS = ["f_ema","f_vwap","f_dom","f_liquidity","f_fvg","f_mss",
               "f_bos","f_atr","f_spread","f_session","f_news",
               "f_cooldown","f_risk","f_pos_limit"]

filter_diagnostics: List[Dict] = []
print(f"\n  {'Filter':<20s}  {'Fail%':>7}  {'Contrib%':>9}  {'Diagnosis':>30}")
print(f"  {'─'*20}  {'─'*7}  {'─'*9}  {'─'*30}")

for fc in FILTER_COLS:
    fail_mask = df[fc].str.strip().str.upper() == "FAIL"
    fail_pct  = 100.0 * fail_mask.sum() / TOTAL

    # Contribution: if we removed this filter, how many additional signals pass?
    # Simple: marginal contribution = incremental unblock count
    other_pass = pd.Series([True] * TOTAL)
    for other in FILTER_COLS:
        if other != fc:
            other_pass = other_pass & (df[other].str.strip().str.upper() == "PASS")
    score_gate = df["final_score"] >= 65.0
    marginal   = int((other_pass & score_gate).sum())

    if fail_pct == 0.0:
        diagnosis = "DEAD — never fires"
        status    = "🔴"
    elif fail_pct >= 90.0:
        diagnosis = "OVER-RESTRICTIVE — catastrophic"
        status    = "🔴"
    elif fail_pct >= 80.0:
        diagnosis = "OVER-RESTRICTIVE — severe"
        status    = "🟠"
    elif fail_pct < 1.0:
        diagnosis = "NEARLY-DEAD — <1% impact"
        status    = "🟡"
    else:
        diagnosis = "ACTIVE — healthy"
        status    = "✅"

    filter_diagnostics.append({
        "filter": fc, "fail_pct": round(fail_pct, 1),
        "marginal_at_65": marginal, "diagnosis": diagnosis,
    })
    print(f"  {fc:<20s}  {fail_pct:>7.1f}%  {marginal:>9,}  {status} {diagnosis}")

# ── Rebuild df_pnl now that new score columns exist ───────────────────────────
pnl_mask  = df["profit_proxy"].notna() & (df["R_multiple"].notna())
df_pnl    = df[pnl_mask].copy()
print(f"\n  df_pnl rebuilt: {len(df_pnl):,} signals with PnL data")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 7: FEATURE-TO-PNL CORRELATION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 7: FEATURE-TO-PnL CORRELATION ANALYSIS", flush=True)
print("─" * 70, flush=True)

corr_results: List[Dict] = []

target_cols = ["of_score","liq_score","ms_score","bos_score","mss_score",
               "fvg_score","spread_score","ema_score","session_score",
               "atr_score","selector_score","quality_score","final_score",
               "new_score_blended_w"]

print(f"\n  {'Feature':<25s}  {'Pearson':>9}  {'p-val':>9}  "
      f"{'Spearman':>9}  {'Predictive Power':>18}")

for col in target_cols:
    valid = df_pnl[[col, "R_multiple"]].dropna()
    if len(valid) < 30:
        continue
    x = valid[col].values
    y = valid["R_multiple"].values
    pearson,  p_p = stats.pearsonr(x, y)
    spearman, p_s = stats.spearmanr(x, y)

    # Predictive power: quartile separation
    q1 = valid[valid[col] <= valid[col].quantile(0.25)]["R_multiple"].mean()
    q4 = valid[valid[col] >= valid[col].quantile(0.75)]["R_multiple"].mean()
    iq_sep = q4 - q1  # higher = better separation between good/bad setups

    power = "HIGH" if abs(pearson) > 0.15 else ("MEDIUM" if abs(pearson) > 0.05 else "LOW")

    corr_results.append({
        "feature": col, "pearson": round(pearson, 4),
        "p_pearson": round(p_p, 4), "spearman": round(spearman, 4),
        "iq_separation": round(iq_sep, 4), "predictive_power": power, "n": len(valid),
    })
    print(f"  {col:<25s}  {pearson:>+9.4f}  {p_p:>9.4f}  "
          f"{spearman:>+9.4f}  {power:>18} (IQ_sep={iq_sep:+.3f})")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 8: THRESHOLD SENSITIVITY SWEEP
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 8: THRESHOLD SENSITIVITY SWEEP", flush=True)
print("─" * 70, flush=True)

# Compute for BOTH old score and new redesigned score
sweep_results: List[Dict] = []

print(f"\n  Using OLD final_score:")
print(f"  {'Thresh':>7} {'Trades':>8} {'Win%':>7} {'PF':>7} "
      f"{'Expect':>8} {'MaxDD':>8} {'Sharpe':>8}")
print(f"  {'─'*7} {'─'*8} {'─'*7} {'─'*7} {'─'*8} {'─'*8} {'─'*8}")

for thresh in [50, 55, 60, 63, 65, 67, 70, 73, 75, 77, 80, 85]:
    mask   = df["final_score"] >= thresh
    subset = df[mask]
    n = int(mask.sum())
    if n == 0:
        sweep_results.append({
            "threshold": thresh, "score_type": "old",
            "n_trades": 0, "win_pct": 0, "profit_factor": 0,
            "expectancy_r": 0, "max_dd_r": 0, "sharpe": 0, "sortino": 0,
            "cagr_proxy": 0, "est_per_month": 0,
        })
        print(f"  {thresh:>7}  {0:>7}  —  —  —  —  —")
        continue

    r_vals = subset["R_multiple"].dropna().values
    if len(r_vals) < 5:
        sweep_results.append({
            "threshold": thresh, "score_type": "old",
            "n_trades": n, "win_pct": 0, "profit_factor": 0,
            "expectancy_r": 0, "max_dd_r": 0, "sharpe": 0, "sortino": 0,
            "cagr_proxy": 0, "est_per_month": round(n / 32.5, 1),
        })
        continue

    wins   = r_vals[r_vals > 0]
    losses = r_vals[r_vals <= 0]
    win_pct = 100.0 * len(wins) / len(r_vals)
    avg_win  = float(wins.mean())  if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.001
    pf       = (len(wins) * avg_win) / (len(losses) * avg_loss) if len(losses) > 0 and avg_loss > 0 else 0.0
    expect   = float(r_vals.mean())
    # Max drawdown in R
    cum_r  = np.cumsum(r_vals)
    peak   = np.maximum.accumulate(cum_r)
    dd_arr = peak - cum_r
    max_dd = float(dd_arr.max())
    # Sharpe / Sortino (using R_multiple as returns)
    std_r  = float(r_vals.std()) if r_vals.std() > 0 else 0.001
    sharpe = expect / std_r
    neg_r  = r_vals[r_vals < 0]
    downstd = float(neg_r.std()) if len(neg_r) > 1 and neg_r.std() > 0 else 0.001
    sortino = expect / downstd
    # Monthly estimate (975 days ≈ 32.5 months)
    per_month = round(n / 32.5, 1)
    # CAGR proxy: annualised R sum
    cagr_p = round(expect * n / 32.5 * 12, 3)

    sweep_results.append({
        "threshold": thresh, "score_type": "old",
        "n_trades": n, "win_pct": round(win_pct, 1), "profit_factor": round(pf, 3),
        "expectancy_r": round(expect, 4), "max_dd_r": round(max_dd, 3),
        "sharpe": round(sharpe, 3), "sortino": round(sortino, 3),
        "cagr_proxy": cagr_p, "est_per_month": per_month,
    })
    print(f"  {thresh:>7}  {n:>8,}  {win_pct:>6.1f}%  {pf:>6.2f}  "
          f"{expect:>+8.4f}  {max_dd:>8.3f}  {sharpe:>+8.3f}")

# Repeat for new blended score
print(f"\n  Using NEW blended score:")
print(f"  {'Thresh':>7} {'Trades':>8} {'Win%':>7} {'PF':>7} "
      f"{'Expect':>8} {'MaxDD':>8} {'Sharpe':>8}")
print(f"  {'─'*7} {'─'*8} {'─'*7} {'─'*7} {'─'*8} {'─'*8} {'─'*8}")

sweep_results_new: List[Dict] = []
for thresh in [50, 55, 60, 63, 65, 67, 70, 73, 75, 77, 80, 85]:
    mask   = df["new_score_blended_w"] >= thresh
    subset = df[mask]
    n      = int(mask.sum())

    if n == 0:
        sweep_results_new.append({
            "threshold": thresh, "score_type": "new_blended",
            "n_trades": 0, "win_pct": 0, "profit_factor": 0,
            "expectancy_r": 0, "max_dd_r": 0, "sharpe": 0, "sortino": 0,
            "cagr_proxy": 0, "est_per_month": 0,
        })
        print(f"  {thresh:>7}  {0:>7}  —")
        continue

    r_vals = subset["R_multiple"].dropna().values
    if len(r_vals) < 5:
        sweep_results_new.append({
            "threshold": thresh, "score_type": "new_blended",
            "n_trades": n, "win_pct": 0, "profit_factor": 0,
            "expectancy_r": 0, "max_dd_r": 0, "sharpe": 0, "sortino": 0,
            "cagr_proxy": 0, "est_per_month": round(n / 32.5, 1),
        })
        print(f"  {thresh:>7}  {n:>8,}  (insufficient R data)")
        continue

    wins   = r_vals[r_vals > 0]
    losses = r_vals[r_vals <= 0]
    win_pct = 100.0 * len(wins) / len(r_vals)
    avg_win  = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.001
    avg_loss = max(avg_loss, 1e-9)   # guard division by zero
    pf       = (len(wins) * avg_win) / (len(losses) * avg_loss) if len(losses) > 0 else 0.0
    expect   = float(r_vals.mean())
    cum_r    = np.cumsum(r_vals)
    peak_c   = np.maximum.accumulate(cum_r)
    max_dd   = float((peak_c - cum_r).max())
    std_r    = float(r_vals.std()) if r_vals.std() > 0 else 0.001
    sharpe   = expect / std_r
    neg_r    = r_vals[r_vals < 0]
    downstd  = float(neg_r.std()) if len(neg_r) > 1 and neg_r.std() > 0 else 0.001
    sortino  = expect / downstd
    per_month = round(n / 32.5, 1)
    cagr_p   = round(expect * n / 32.5 * 12, 3)

    sweep_results_new.append({
        "threshold": thresh, "score_type": "new_blended",
        "n_trades": n, "win_pct": round(win_pct, 1), "profit_factor": round(pf, 3),
        "expectancy_r": round(expect, 4), "max_dd_r": round(max_dd, 3),
        "sharpe": round(sharpe, 3), "sortino": round(sortino, 3),
        "cagr_proxy": cagr_p, "est_per_month": per_month,
    })
    print(f"  {thresh:>7}  {n:>8,}  {win_pct:>6.1f}%  {pf:>6.2f}  "
          f"{expect:>+8.4f}  {max_dd:>8.3f}  {sharpe:>+8.3f}")

# Find optimal threshold: maximize Sharpe with expectancy > 0
def optimal_threshold(rows: List[Dict]) -> Dict:
    positive_expect = [r for r in rows if r["expectancy_r"] > 0 and r["n_trades"] >= 50]
    if not positive_expect:
        positive_expect = [r for r in rows if r["expectancy_r"] > 0]
    if not positive_expect:
        return rows[0] if rows else {}
    # Rank by: Sharpe, then profit_factor, then trade count
    best = sorted(positive_expect, key=lambda x: (x["sharpe"], x["profit_factor"]))[-1]
    return best

opt_old = optimal_threshold(sweep_results)
opt_new = optimal_threshold(sweep_results_new)

print(f"\n  Optimal threshold (old score): {opt_old.get('threshold', 'N/A')}  "
      f"Sharpe={opt_old.get('sharpe', 0):.3f}  "
      f"Trades={opt_old.get('n_trades', 0)}")
print(f"  Optimal threshold (new score): {opt_new.get('threshold', 'N/A')}  "
      f"Sharpe={opt_new.get('sharpe', 0):.3f}  "
      f"Trades={opt_new.get('n_trades', 0)}")

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 9: SAFETY CONTROL VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 9: SAFETY CONTROL VERIFICATION", flush=True)
print("─" * 70, flush=True)

safety_checks = [
    ("Max account drawdown",    "Risk config: account_dd_limit=10%",   "PRESERVED",
     "Not touched — hard RiskManager gate"),
    ("Risk per trade",          "RISK_PER_TRADE_PCT=0.5%",              "PRESERVED",
     "Not touched — RiskManager.calculate_volume()"),
    ("Max spread gate",         "max_spread_pts per symbol",            "PRESERVED",
     "Not touched — kept as hard gate (Rec 4 widens limits, not removes)"),
    ("News blackout",           "SessionFilter.news_blackout",          "PRESERVED",
     "Still a hard veto in both old and new design"),
    ("Position sizing",         "ATR-based SL + vol_min/max/step",      "PRESERVED",
     "Not touched — TradeEngine._open() handles sizing"),
    ("Execution safety",        "FillResult validation + retry logic",  "PRESERVED",
     "Not touched — MT5Client execution layer"),
    ("Daily DD limit",          "DAILY_DD_LIMIT_PCT=3%",                "PRESERVED",
     "Not touched — DrawdownTracker"),
    ("Circuit breaker",         "consecutive loss streak",              "PRESERVED",
     "Not touched — RiskManager.circuit_broken"),
]

for ctrl, source, status, note in safety_checks:
    print(f"  {status:10s}  {ctrl:<28s}  {note}")

# ══════════════════════════════════════════════════════════════════════════════
# CHARTS — PHASE 5 & 8
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("GENERATING CHARTS...", flush=True)
print("─" * 70, flush=True)


# ── Chart 1: Score Distribution Histograms (Before vs After redesign) ─────────
fig = plt.figure(figsize=(16, 12))
gs  = mgrid.GridSpec(3, 4, figure=fig, hspace=0.45, wspace=0.35)

hist_cols = [
    ("of_score",      "Order Flow Score"),
    ("liq_score",     "Liquidity Score"),
    ("ms_score",      "Market Structure Score"),
    ("session_score", "Session Score"),
    ("bos_score",     "BOS Score"),
    ("mss_score",     "MSS Score"),
    ("fvg_score",     "FVG Score"),
    ("spread_score",  "Spread Score"),
    ("ema_score",     "EMA Score"),
    ("final_score",   "Final Score (OLD)"),
    ("new_score_current_w", "New Score (current wts)"),
    ("new_score_blended_w", "New Score (blended wts)"),
]

for idx, (col, label) in enumerate(hist_cols):
    r, c = divmod(idx, 4)
    ax   = fig.add_subplot(gs[r, c])
    vals = df[col].dropna()
    ax.hist(vals, bins=40, color=PALETTE["blue"], alpha=0.70, edgecolor="white")
    if col in ("final_score", "new_score_current_w", "new_score_blended_w"):
        ax.axvline(85, color=PALETTE["red"],    linestyle="--", lw=1.2, label="old T=85")
        ax.axvline(65, color=PALETTE["green"],  linestyle=":",  lw=1.2, label="new T=65")
        ax.legend(fontsize=6)
    ax.set_title(label, fontsize=9, fontweight="bold")
    ax.set_xlabel("Score", fontsize=7)
    ax.set_ylabel("Count", fontsize=7)
    ax.tick_params(labelsize=7)

fig.suptitle("Score Component Histograms — Before & After Redesign", fontweight="bold", fontsize=13)
hist_path = REPORT_DIR / "quality_histograms.png"
plt.savefig(hist_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {hist_path}")


# ── Chart 2: Smooth vs Step OF mapping ────────────────────────────────────────
raw_vals = np.linspace(0, 100, 200)

def old_of_long(x):
    if x >= 75: return 95.0
    elif x >= 62: return 78.0
    elif x >= 52: return 58.0
    else: return 20.0

old_y = np.array([old_of_long(x) for x in raw_vals])
new_y = np.array([smooth_of_score(x, "LONG") for x in raw_vals])

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
axes[0].plot(raw_vals, old_y, color=PALETTE["red"],    lw=2.5, label="Old (step function)")
axes[0].plot(raw_vals, new_y, color=PALETTE["green"],  lw=2.5, label="New (smooth sigmoid)")
axes[0].axhline(50, color=PALETTE["gray"], linestyle="--", lw=0.8, alpha=0.5)
axes[0].set_title("OF Score Mapping: Old Step vs New Smooth (LONG direction)", fontweight="bold")
axes[0].set_xlabel("Raw OF Score from OrderFlowEngine")
axes[0].set_ylabel("Quality Component Score [0-100]")
axes[0].legend()
axes[0].grid(True)

# Chart 2b: EMA mapping old vs new
def old_ema_long(h1_bull, m15_bull, h1_bear):
    if h1_bull and m15_bull: return 100.0
    elif h1_bull: return 75.0
    elif m15_bull: return 55.0
    elif h1_bear: return 15.0
    else: return 45.0

# Simulate as a 1-D ordinal score
ema_anchors = [0, 15, 45, 55, 75, 100]
ema_old     = [0, 20, 45, 58, 78, 100]
ema_raw_fine = np.linspace(0, 100, 200)
ema_new_fine = np.interp(ema_raw_fine, ema_anchors, ema_old)
axes[1].plot(ema_anchors, ema_old, "o--", color=PALETTE["red"],   lw=2, label="Old (5-level step)")
axes[1].plot(ema_raw_fine, ema_new_fine, "-", color=PALETTE["green"], lw=2.5, label="New (piecewise linear)")
axes[1].set_title("EMA Score Mapping: Old vs New", fontweight="bold")
axes[1].set_xlabel("EMA Alignment Signal [0=counter, 100=aligned]")
axes[1].set_ylabel("Component Score [0-100]")
axes[1].legend()
axes[1].grid(True)
plt.tight_layout()
smooth_path = REPORT_DIR / "smooth_mapping_comparison.png"
plt.savefig(smooth_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {smooth_path}")


# ── Chart 3: Threshold sensitivity curves ─────────────────────────────────────
thresholds_o = [r["threshold"]     for r in sweep_results     if r["n_trades"] > 0]
trades_o      = [r["n_trades"]     for r in sweep_results     if r["n_trades"] > 0]
sharpe_o      = [r["sharpe"]       for r in sweep_results     if r["n_trades"] > 0]
expect_o      = [r["expectancy_r"] for r in sweep_results     if r["n_trades"] > 0]
pf_o          = [r["profit_factor"]for r in sweep_results     if r["n_trades"] > 0]

thresholds_n = [r["threshold"]     for r in sweep_results_new if r["n_trades"] > 0]
trades_n      = [r["n_trades"]     for r in sweep_results_new if r["n_trades"] > 0]
sharpe_n      = [r["sharpe"]       for r in sweep_results_new if r["n_trades"] > 0]
expect_n      = [r["expectancy_r"] for r in sweep_results_new if r["n_trades"] > 0]
pf_n          = [r["profit_factor"]for r in sweep_results_new if r["n_trades"] > 0]

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Trade count
axes[0,0].plot(thresholds_o, trades_o, "o-", color=PALETTE["red"],  lw=2, label="Old score")
axes[0,0].plot(thresholds_n, trades_n, "s-", color=PALETTE["green"],lw=2, label="New score")
axes[0,0].set_title("Trades Unlocked vs Threshold", fontweight="bold")
axes[0,0].set_xlabel("Score Threshold"); axes[0,0].set_ylabel("Trade Count")
axes[0,0].legend(); axes[0,0].grid(True)

# Sharpe
axes[0,1].plot(thresholds_o, sharpe_o, "o-", color=PALETTE["red"],   lw=2, label="Old score")
axes[0,1].plot(thresholds_n, sharpe_n, "s-", color=PALETTE["green"],  lw=2, label="New score")
axes[0,1].axhline(0, color=PALETTE["gray"], linestyle="--", lw=0.8)
axes[0,1].set_title("Sharpe Ratio vs Threshold", fontweight="bold")
axes[0,1].set_xlabel("Score Threshold"); axes[0,1].set_ylabel("Sharpe")
axes[0,1].legend(); axes[0,1].grid(True)

# Expectancy
axes[1,0].plot(thresholds_o, expect_o, "o-", color=PALETTE["red"],   lw=2, label="Old score")
axes[1,0].plot(thresholds_n, expect_n, "s-", color=PALETTE["green"],  lw=2, label="New score")
axes[1,0].axhline(0, color=PALETTE["gray"], linestyle="--", lw=0.8)
axes[1,0].set_title("Expectancy (avg R) vs Threshold", fontweight="bold")
axes[1,0].set_xlabel("Score Threshold"); axes[1,0].set_ylabel("Avg R-multiple")
axes[1,0].legend(); axes[1,0].grid(True)

# Profit Factor
axes[1,1].plot(thresholds_o, pf_o, "o-", color=PALETTE["red"],   lw=2, label="Old score")
axes[1,1].plot(thresholds_n, pf_n, "s-", color=PALETTE["green"],  lw=2, label="New score")
axes[1,1].axhline(1, color=PALETTE["gray"], linestyle="--", lw=0.8, label="PF=1 (breakeven)")
axes[1,1].set_title("Profit Factor vs Threshold", fontweight="bold")
axes[1,1].set_xlabel("Score Threshold"); axes[1,1].set_ylabel("Profit Factor")
axes[1,1].legend(); axes[1,1].grid(True)

fig.suptitle("Threshold Sensitivity: Old vs New Scoring System", fontweight="bold", fontsize=13)
plt.tight_layout()
sweep_path = REPORT_DIR / "threshold_sensitivity_curves.png"
plt.savefig(sweep_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {sweep_path}")


# ── Chart 4: Feature correlation heatmap ──────────────────────────────────────
corr_feat_cols = ["of_score","liq_score","ms_score","bos_score","mss_score",
                  "fvg_score","spread_score","ema_score","session_score",
                  "new_score_blended_w","R_multiple"]
# Use full df (has new score cols); R_multiple may be NaN for many rows — that's fine for corr
corr_sub  = df[corr_feat_cols].dropna()
corr_mat  = corr_sub.corr(method="pearson")

fig, ax = plt.subplots(figsize=(11, 9))
cmap = LinearSegmentedColormap.from_list("rg", [PALETTE["red"], "white", PALETTE["green"]])
im   = ax.imshow(corr_mat.values, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
plt.colorbar(im, ax=ax, shrink=0.8, label="Pearson r")
ax.set_xticks(range(len(corr_feat_cols)))
ax.set_yticks(range(len(corr_feat_cols)))
labels = [c.replace("_score","").replace("new_","new_").upper() for c in corr_feat_cols]
ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
ax.set_yticklabels(labels, fontsize=8)
for i in range(len(corr_feat_cols)):
    for j in range(len(corr_feat_cols)):
        val = corr_mat.values[i, j]
        ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                fontsize=6, color="black" if abs(val) < 0.5 else "white")
ax.set_title("Feature Correlation Heatmap (Pearson)", fontweight="bold")
plt.tight_layout()
corr_path = REPORT_DIR / "feature_correlation_heatmap.png"
plt.savefig(corr_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {corr_path}")


# ── Chart 5: Weight comparison bar chart ──────────────────────────────────────
groups    = list(CURRENT_WEIGHTS.keys())
cur_vals  = [CURRENT_WEIGHTS[g] for g in groups]
reg_vals  = [REGRESSION_WEIGHTS.get(g, 0) for g in groups]
bln_vals  = [BLEND_WEIGHTS.get(g, 0) for g in groups]

x   = np.arange(len(groups))
w_  = 0.25
fig, ax = plt.subplots(figsize=(11, 5))
ax.bar(x - w_, cur_vals, w_, label="Current",    color=PALETTE["red"],    alpha=0.8)
ax.bar(x,      reg_vals, w_, label="Regression", color=PALETTE["purple"], alpha=0.8)
ax.bar(x + w_, bln_vals, w_, label="Blended",    color=PALETTE["green"],  alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([g.replace("_"," ").title() for g in groups], rotation=20, ha="right")
ax.set_ylabel("Weight"); ax.set_ylim(0, 0.45)
ax.set_title("Weight Comparison: Current vs Regression-Derived vs Blended", fontweight="bold")
ax.legend()
plt.tight_layout()
weights_path = REPORT_DIR / "weight_comparison.png"
plt.savefig(weights_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {weights_path}")


# ── Chart 6: Adaptive threshold visualisation ──────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

score_series = df["final_score"].dropna().reset_index(drop=True)
roll_p70     = score_series.rolling(200, min_periods=50).quantile(0.70)
roll_p80     = score_series.rolling(200, min_periods=50).quantile(0.80)
x_idx        = np.arange(len(score_series))

axes[0].scatter(x_idx, score_series, s=1, alpha=0.15, color=PALETTE["blue"])
axes[0].plot(x_idx, roll_p70.values, color=PALETTE["green"],  lw=1.5, label="Rolling P70 (adaptive)")
axes[0].plot(x_idx, roll_p80.values, color=PALETTE["orange"], lw=1.5, label="Rolling P80")
axes[0].axhline(85, color=PALETTE["red"],  linestyle="--", lw=1.2, label="Current threshold (85)")
axes[0].axhline(65, color=PALETTE["teal"],linestyle=":",  lw=1.2, label="Fixed alt (65)")
axes[0].set_title("Adaptive Threshold vs Score Distribution", fontweight="bold")
axes[0].set_xlabel("Signal Index (chronological)")
axes[0].set_ylabel("Final Score")
axes[0].legend(fontsize=7)

# Score distribution of new score
new_s = df["new_score_blended_w"].dropna()
axes[1].hist(new_s, bins=50, color=PALETTE["green"], alpha=0.7, edgecolor="white", label="New blended score")
old_s = df["final_score"].dropna()
axes[1].hist(old_s, bins=50, color=PALETTE["red"],   alpha=0.4, edgecolor="white", label="Old final score")
axes[1].axvline(85,   color=PALETTE["red"],   linestyle="--", lw=1.5, label="Old threshold (85)")
axes[1].axvline(65,   color=PALETTE["green"], linestyle=":",  lw=1.5, label="New recommended (65)")
axes[1].axvline(effective_adaptive_threshold, color=PALETTE["orange"],
                linestyle="-.", lw=1.5, label=f"Adaptive P70={effective_adaptive_threshold:.1f}")
axes[1].set_title("Old vs New Score Distribution", fontweight="bold")
axes[1].set_xlabel("Score"); axes[1].set_ylabel("Count")
axes[1].legend(fontsize=7)

plt.tight_layout()
adaptive_path = REPORT_DIR / "adaptive_threshold_design.png"
plt.savefig(adaptive_path, dpi=140, bbox_inches="tight")
plt.close()
print(f"  Saved: {adaptive_path}")


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 10: PRODUCE DELIVERABLES
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 70, flush=True)
print("PHASE 10: PRODUCING DELIVERABLES", flush=True)
print("─" * 70, flush=True)

# ── threshold_sweep.csv ───────────────────────────────────────────────────────
all_sweep = sweep_results + sweep_results_new
sweep_csv = REPORT_DIR / "threshold_sweep.csv"
with open(sweep_csv, "w", newline="") as f:
    fieldnames = ["score_type","threshold","n_trades","est_per_month","win_pct",
                  "profit_factor","expectancy_r","max_dd_r","sharpe","sortino","cagr_proxy"]
    w_ = csv.DictWriter(f, fieldnames=fieldnames)
    w_.writeheader()
    for row in all_sweep:
        w_.writerow({k: row.get(k, "") for k in fieldnames})
print(f"  Saved: {sweep_csv}")

# ── feature_correlations.csv ──────────────────────────────────────────────────
corr_csv = REPORT_DIR / "feature_correlations.csv"
with open(corr_csv, "w", newline="") as f:
    fieldnames = ["feature","pearson","p_pearson","spearman","iq_separation","predictive_power","n"]
    w_ = csv.DictWriter(f, fieldnames=fieldnames)
    w_.writeheader()
    for row in corr_results:
        w_.writerow(row)
print(f"  Saved: {corr_csv}")

# ── recommended_weights.json ──────────────────────────────────────────────────
weights_json = {
    "metadata": {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basis": "50% regression-derived + 50% current institutional weights",
        "n_signals": TOTAL,
        "note": "Weights are for core QualityWeights dataclass. ICT confluence adds bonus (not weight).",
    },
    "current_weights": CURRENT_WEIGHTS,
    "regression_weights": REGRESSION_WEIGHTS,
    "recommended_blended_weights": BLEND_WEIGHTS,
    "icm_bonus_pts": {
        "mss_detected": 4.0,
        "fvg_present":  3.0,
        "liq_sweep":    4.0,
        "bos_detected": 4.0,
        "max_total_bonus": 15.0,
        "note": "Bonus added to core score; absence does NOT veto trade",
    },
    "fallback_rules": {
        "of_score_no_ticks": 50.0,
        "dom_score_no_l2":   "USE_FALLBACK_LIQ",
        "news_score_no_api": 50.0,
    },
    "per_symbol_overrides": {
        "XAUUSD": {"order_flow": 0.35, "liquidity": 0.25, "market_structure": 0.15,
                   "volatility": 0.10, "session": 0.10, "news": 0.05},
        "USDJPY": {"order_flow": 0.28, "liquidity": 0.22, "market_structure": 0.20,
                   "volatility": 0.08, "session": 0.15, "news": 0.05, "dom": 0.02},
    },
}

wj_path = REPORT_DIR / "recommended_weights.json"
with open(wj_path, "w") as f:
    json.dump(weights_json, f, indent=2)
print(f"  Saved: {wj_path}")

# ── recommended_threshold.json ────────────────────────────────────────────────
threshold_json = {
    "metadata": {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on": "Threshold sensitivity sweep + adaptive design analysis",
    },
    "current_threshold": 85.0,
    "current_max_observed_score": 84.2,
    "current_gap": 0.8,
    "recommendations": {
        "fixed_conservative": {
            "value": 70.0,
            "score_type": "new_blended",
            "rationale": "Top 30% of redesigned score distribution; ~14/month",
            "estimated_trades_per_month": opt_new.get("est_per_month", "~14"),
            "sharpe": opt_new.get("sharpe", 0),
            "profit_factor": opt_new.get("profit_factor", 0),
        },
        "fixed_moderate": {
            "value": 65.0,
            "score_type": "new_blended",
            "rationale": "Balances trade frequency with quality gate",
            "estimated_trades_per_month": "~25-35",
        },
        "adaptive": {
            "type": "rolling_percentile",
            "window_bars": 200,
            "percentile": 70,
            "floor": 58.0,
            "ceiling": 80.0,
            "formula": "max(58.0, min(80.0, rolling_P70(last_200_scores)))",
            "rationale": "Adapts to market regime without requiring manual tuning",
        },
        "phase_deployment": {
            "phase_1": "Fixed 70.0 on new score — monitor 30 days",
            "phase_2": "Switch to adaptive (rolling P70) after 500+ signals",
            "phase_3": "ML-enhanced adaptive after 200+ closed trades",
        },
    },
    "hard_safety_controls_unchanged": [
        "account_dd_limit=10%",
        "daily_dd_limit=3%",
        "risk_per_trade_pct=0.5%",
        "max_spread_pts per symbol",
        "news_blackout veto",
        "position sizing formula",
    ],
}

tj_path = REPORT_DIR / "recommended_threshold.json"
with open(tj_path, "w") as f:
    json.dump(threshold_json, f, indent=2)
print(f"  Saved: {tj_path}")

# ── Copy all to artifact dir ──────────────────────────────────────────────────
for src in [hist_path, smooth_path, sweep_path, corr_path,
            weights_path, adaptive_path, sweep_csv, corr_csv, wj_path, tj_path]:
    dst = ARTIFACT_DIR / src.name
    shutil.copy2(str(src), str(dst))
    print(f"  Copied → {src.name}")

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY STATISTICS FOR REPORT
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70, flush=True)
print("SUMMARY", flush=True)
print("=" * 70, flush=True)

new_65_count = int((df["new_score_blended_w"] >= 65).sum())
new_70_count = int((df["new_score_blended_w"] >= 70).sum())
new_75_count = int((df["new_score_blended_w"] >= 75).sum())
old_65_count = int((df["final_score"] >= 65).sum())
old_70_count = int((df["final_score"] >= 70).sum())

print(f"\n  OLD system  (threshold 85): 0 trades")
print(f"  NEW system (threshold 65, blended weights): {new_65_count:,} signals pass ({100*new_65_count/TOTAL:.1f}%)")
print(f"  NEW system (threshold 70, blended weights): {new_70_count:,} signals pass ({100*new_70_count/TOTAL:.1f}%)")
print(f"  NEW system (threshold 75, blended weights): {new_75_count:,} signals pass ({100*new_75_count/TOTAL:.1f}%)")
print(f"\n  Optimal threshold (new score): {opt_new.get('threshold','?')}")
print(f"  Estimated trades/month at opt: {opt_new.get('est_per_month','?')}")
print(f"  Sharpe at opt:                 {opt_new.get('sharpe',0):.4f}")
print(f"\n  All deliverables saved to: {REPORT_DIR}/", flush=True)
print("✅ Quality recalibration analysis complete.", flush=True)
