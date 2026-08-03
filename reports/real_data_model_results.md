# Logistic Regression Model Results (PARTIAL VALIDATION)

> [!WARNING]
> **PARTIAL VALIDATION NOTICE**: This report is a partial validation because 15 out of 21 required datasets are missing. Performance metrics reflect only the available symbols.

## Out-Of-Sample (Test Split) Performance
| Model | Accuracy | Precision | Recall | F1 Score | Brier Score |
|---|---|---|---|---|---|
| BUY Model (Logistic Regression) | 0.5109 | 0.4784 | 0.2101 | 0.2920 | 0.2496 |
| SELL Model (Logistic Regression) | 0.5107 | 0.5042 | 0.2049 | 0.2914 | 0.2500 |

## Confusion Matrices
### BUY Model
- True Positive (TP): 6791
- False Positive (FP): 7404
- True Negative (TN): 27608
- False Negative (FN): 25527

### SELL Model
- True Positive (TP): 6773
- False Positive (FP): 6660
- True Negative (TN): 27610
- False Negative (FN): 26287

## Probability Calibration
### BUY Model Calibration
| Bin | Count | Mean Predicted Prob | Actual Frequency |
|---|---|---|---|
| 0.3-0.4 | 4 | 0.3977 | 0.7500 |
| 0.4-0.5 | 53131 | 0.4807 | 0.4804 |
| 0.5-0.6 | 14195 | 0.5067 | 0.4784 |

### SELL Model Calibration
| Bin | Count | Mean Predicted Prob | Actual Frequency |
|---|---|---|---|
| 0.4-0.5 | 53897 | 0.4788 | 0.4877 |
| 0.5-0.6 | 13433 | 0.5088 | 0.5042 |
