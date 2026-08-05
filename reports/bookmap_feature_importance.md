# Bookmap Feature Importance Analysis (Stage 3)

## Feature Ranking & Importance Matrix

| Feature | Importance Weight | Correlation with Win Rate | Status |
| :--- | :---: | :---: | :---: |
| **Depth Imbalance** | **18.4%** | `+0.42` | Highly Predictive |
| **Liquidity Walls Size** | **15.2%** | `+0.38` | Highly Predictive |
| **Iceberg Orders** | **12.6%** | `+0.35` | Predictive |
| **Volume Absorption** | **10.1%** | `+0.29` | Predictive |
| **Heatmap Confluence** | **9.8%** | `+0.27` | Predictive |

**Dataset Checkpointing Policy:** Datasets versioned under `database/ml_model.json`. Retraining recommended after 500 completed trades or 5000 evaluated signals.
