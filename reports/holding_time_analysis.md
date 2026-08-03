# Module 7 — Holding Time Analysis

Simulates entering at each bar close and measuring return at each holding horizon.
Return is normalised to ATR. Sharpe computed across all entry points.

## Aggregate Holding Time Statistics (All Symbols)

| Hold Period | Avg Return (R) | Win % | Sharpe | Std Dev |
|:---|---:|---:|---:|---:|
| 5 min  (1 bar) | +0.0121 | 50.5% | +0.014 | 0.8851 |
| 15 min (1 bar) | +0.0121 | 50.5% | +0.014 | 0.8851 |
| 30 min (2 bars) | +0.0231 | 50.6% | +0.014 | 1.6605 |
| 1 hr   (4 bars) | +0.0422 | 50.5% | +0.013 | 3.3579 |
| 2 hr   (8 bars) | +0.0711 | 50.4% | +0.010 | 7.2790 |
| 4 hr   (16 bars) | +0.1052 | 50.5% | +0.006 | 16.7042 |
| 8 hr   (32 bars) | +0.1739 | 50.7% | +0.005 | 38.1590 |
| 1 day  (96 bars) | +3.0257 | 50.7% | +0.023 | 130.0794 |

## Per-Symbol Holding Time Breakdown

### BTCUSD

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | +0.0031 | 49.6% | +0.003 |
| 15 min (1 bar) | +0.0031 | 49.6% | +0.003 |
| 30 min (2 bars) | +0.0060 | 49.7% | +0.003 |
| 1 hr   (4 bars) | +0.0138 | 49.7% | +0.003 |
| 2 hr   (8 bars) | +0.0298 | 49.7% | +0.003 |
| 4 hr   (16 bars) | +0.0719 | 49.7% | +0.003 |
| 8 hr   (32 bars) | +0.1799 | 50.4% | +0.004 |
| 1 day  (96 bars) | +7.0329 | 51.2% | +0.045 |
> *Optimal hold for BTCUSD: **1 day  (96 bars)** (Sharpe +0.045)*

### XAUUSD

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | -0.0070 | 49.6% | -0.009 |
| 15 min (1 bar) | -0.0070 | 49.6% | -0.009 |
| 30 min (2 bars) | -0.0140 | 49.5% | -0.010 |
| 1 hr   (4 bars) | -0.0283 | 49.8% | -0.011 |
| 2 hr   (8 bars) | -0.0592 | 49.7% | -0.012 |
| 4 hr   (16 bars) | -0.1264 | 50.1% | -0.012 |
| 8 hr   (32 bars) | -0.2826 | 50.3% | -0.013 |
| 1 day  (96 bars) | -1.7840 | 48.8% | -0.023 |
> *Optimal hold for XAUUSD: **5 min  (1 bar)** (Sharpe -0.009)*

### EURUSD

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | +0.0561 | 52.8% | +0.055 |
| 15 min (1 bar) | +0.0561 | 52.8% | +0.055 |
| 30 min (2 bars) | +0.1072 | 53.2% | +0.053 |
| 1 hr   (4 bars) | +0.1937 | 53.3% | +0.045 |
| 2 hr   (8 bars) | +0.3060 | 53.4% | +0.031 |
| 4 hr   (16 bars) | +0.3446 | 53.3% | +0.014 |
| 8 hr   (32 bars) | +0.2060 | 53.9% | +0.003 |
| 1 day  (96 bars) | +6.3095 | 55.0% | +0.030 |
> *Optimal hold for EURUSD: **5 min  (1 bar)** (Sharpe +0.055)*

### GBPUSD

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | +0.0049 | 50.4% | +0.006 |
| 15 min (1 bar) | +0.0049 | 50.4% | +0.006 |
| 30 min (2 bars) | +0.0093 | 50.3% | +0.006 |
| 1 hr   (4 bars) | +0.0165 | 50.1% | +0.005 |
| 2 hr   (8 bars) | +0.0292 | 50.3% | +0.005 |
| 4 hr   (16 bars) | +0.0552 | 50.0% | +0.004 |
| 8 hr   (32 bars) | +0.1763 | 50.7% | +0.006 |
| 1 day  (96 bars) | +3.5973 | 50.9% | +0.038 |
> *Optimal hold for GBPUSD: **1 day  (96 bars)** (Sharpe +0.038)*

### USDJPY

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | +0.0303 | 51.7% | +0.034 |
| 15 min (1 bar) | +0.0303 | 51.7% | +0.034 |
| 30 min (2 bars) | +0.0613 | 51.7% | +0.036 |
| 1 hr   (4 bars) | +0.1249 | 51.7% | +0.037 |
| 2 hr   (8 bars) | +0.2702 | 51.6% | +0.037 |
| 4 hr   (16 bars) | +0.6364 | 51.6% | +0.037 |
| 8 hr   (32 bars) | +1.6528 | 51.8% | +0.041 |
| 1 day  (96 bars) | +7.6467 | 52.5% | +0.051 |
> *Optimal hold for USDJPY: **1 day  (96 bars)** (Sharpe +0.051)*

### NAS100

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | -0.0195 | 49.0% | -0.026 |
| 15 min (1 bar) | -0.0195 | 49.0% | -0.026 |
| 30 min (2 bars) | -0.0398 | 48.7% | -0.031 |
| 1 hr   (4 bars) | -0.0815 | 48.6% | -0.034 |
| 2 hr   (8 bars) | -0.1702 | 48.1% | -0.036 |
| 4 hr   (16 bars) | -0.3682 | 48.0% | -0.038 |
| 8 hr   (32 bars) | -0.8613 | 47.6% | -0.041 |
| 1 day  (96 bars) | -2.9328 | 47.2% | -0.047 |
> *Optimal hold for NAS100: **5 min  (1 bar)** (Sharpe -0.026)*

### US30

| Hold Period | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| 5 min  (1 bar) | +0.0167 | 50.6% | +0.020 |
| 15 min (1 bar) | +0.0167 | 50.6% | +0.020 |
| 30 min (2 bars) | +0.0313 | 50.8% | +0.020 |
| 1 hr   (4 bars) | +0.0561 | 50.5% | +0.018 |
| 2 hr   (8 bars) | +0.0921 | 50.2% | +0.014 |
| 4 hr   (16 bars) | +0.1229 | 50.5% | +0.008 |
| 8 hr   (32 bars) | +0.1462 | 50.0% | +0.004 |
| 1 day  (96 bars) | +1.3102 | 49.6% | +0.013 |
> *Optimal hold for US30: **30 min (2 bars)** (Sharpe +0.020)*

## Key Findings

- **Best holding period**: `1 day  (96 bars)` — Sharpe +0.023
- **Worst holding period**: `8 hr   (32 bars)` — Sharpe +0.005
- Random walk hypothesis predicts Sharpe ≈ 0. Significant deviations indicate edge.
