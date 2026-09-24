# Candidate Machine Learning Model Benchmark Report

**Generated At:** 2026-09-24T15:43:52.774452+00:00  
**Candidate Model:** `XGBoost_Candidate_v1` (v3.1_candidate)  

## Benchmark Metrics

| Metric | Candidate Model Value | Baseline Production Model | Variance |
| :--- | :---: | :---: | :---: |
| **Accuracy** | `64.4%` | `50.0%` | **+14.4%** |
| **Precision** | `67.6%` | `50.0%` | **+17.6%** |
| **Recall** | `63.1%` | `50.0%` | **+13.1%** |
| **F1-Score** | `65.3%` | `50.0%` | **+15.3%** |
| **Profit Factor** | `1.59` | `1.42` | **+0.17** |
| **p-Value (Significance)** | `0.054` | `0.05` | `Not Significant Yet` |

## Deployment Gate Evaluation

- **500 Completed Trades Gate:** `IN PROGRESS 🔄 (96/500 Trades)`
- **5000 Evaluated Signals Gate:** `IN PROGRESS 🔄 (1440/5000 Signals)`
- **Statistical Significance Gate:** `IN PROGRESS 🔄`

**Recommendation:** **`CONTINUE RESEARCH SHADOW MODE (96/500 trades accumulated)`**  
*(Policy: Production model database/ml_model.json remains 100% untouched until all deployment gates pass).*
