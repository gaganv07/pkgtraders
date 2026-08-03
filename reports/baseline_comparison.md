# Baseline Model Comparison

## BUY Model Baselines
| Model | Accuracy | Precision | Recall | F1 Score |
|---|---|---|---|---|
| **Logistic Regression (Phase 4)** | **0.7423** | **0.7420** | **0.6482** | **0.6919** |
| Random | 0.5006 | 0.4707 | 0.4998 | 0.4848 |
| Always BUY | 0.4702 | 0.4702 | 1.0000 | 0.6396 |
| Trend Continuation (EMA) | 0.6589 | 0.6253 | 0.6849 | 0.6538 |
| Mean Reversion (VWAP) | 0.3786 | 0.1247 | 0.0534 | 0.0748 |
| RSI Momentum | 0.7122 | 0.6772 | 0.7413 | 0.7078 |

## SELL Model Baselines
| Model | Accuracy | Precision | Recall | F1 Score |
|---|---|---|---|---|
| **Logistic Regression (Phase 4)** | **0.7374** | **0.7496** | **0.6687** | **0.7069** |
| Random | 0.5006 | 0.4406 | 0.4988 | 0.4679 |
| Always SELL | 0.4402 | 0.4402 | 1.0000 | 0.6113 |
| Trend Continuation (EMA) | 0.6629 | 0.6063 | 0.6680 | 0.6357 |
| Mean Reversion (VWAP) | 0.3825 | 0.1223 | 0.0652 | 0.0850 |
| RSI Momentum | 0.7142 | 0.6591 | 0.7266 | 0.6912 |

## Conclusion
If the dumb 'Trend Continuation (EMA)' heuristic achieves similar accuracy (>70%) to the Logistic Regression model, it conclusively proves the ML model is just exploiting the synthetic data's massive trend autocorrelation, rather than discovering a complex multi-factor edge.
