# Bookmap Feature Importance Analysis

## Machine Learning Feature Ranking & Correlation Matrix

| Feature | Importance Weight | Correlation | Mutual Information | Predictive Rank |
| :--- | :---: | :---: | :---: | :---: |
| **Depth Imbalance** | **18.4%** | `+0.42` | `0.182` | **Rank 1** |
| **Liquidity Walls Size** | **15.2%** | `+0.38` | `0.154` | **Rank 2** |
| **Iceberg Orders** | **12.6%** | `+0.35` | `0.128` | **Rank 3** |
| **Volume Absorption** | **10.1%** | `+0.29` | `0.105` | **Rank 4** |
| **Heatmap Confluence** | **9.8%** | `+0.27` | `0.098` | **Rank 5** |

**Dataset Retraining Policy:** Production model replacement disabled. Retraining checkpoint threshold: 500 completed trades or 5,000 evaluated setups.
