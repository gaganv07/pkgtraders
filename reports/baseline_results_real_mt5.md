# Baseline Performance Metrics (PARTIAL VALIDATION)

> [!WARNING]
> **PARTIAL VALIDATION NOTICE**: This report is a partial validation because 15 out of 21 required datasets are missing. Performance metrics reflect only the available symbols.

## BUY Model Baseline Comparison
| Heuristic Model | Accuracy | Precision | Recall | F1 Score | Brier Score |
|---|---|---|---|---|---|
| Random | 0.5020 | 0.4819 | 0.5007 | 0.4912 | 0.3320 |
| Always BUY | 0.4800 | 0.4800 | 1.0000 | 0.6486 | 0.5200 |
| Trend Continuation | 0.4969 | 0.4779 | 0.5197 | 0.4979 | 0.3418 |
| Mean Reversion | 0.5082 | 0.4761 | 0.2445 | 0.3231 | 0.3351 |

## SELL Model Baseline Comparison
| Heuristic Model | Accuracy | Precision | Recall | F1 Score | Brier Score |
|---|---|---|---|---|---|
| Random | 0.5008 | 0.4919 | 0.5039 | 0.4978 | 0.3342 |
| Always SELL | 0.4910 | 0.4910 | 1.0000 | 0.6586 | 0.5090 |
| Trend Continuation | 0.5009 | 0.4915 | 0.4785 | 0.4849 | 0.3395 |
| Mean Reversion | 0.5052 | 0.4934 | 0.2913 | 0.3663 | 0.3369 |
