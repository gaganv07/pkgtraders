# Confusion Matrices (Threshold = 0.5)

## BUY Model
| | Predicted Positive | Predicted Negative |
|---|---|---|
| **Actual Positive** | True Positive: 25288 | False Negative: 13726 |
| **Actual Negative** | False Positive: 8795 | True Negative: 39579 |

## SELL Model
| | Predicted Positive | Predicted Negative |
|---|---|---|
| **Actual Positive** | True Positive: 27670 | False Negative: 13710 |
| **Actual Negative** | False Positive: 9241 | True Negative: 36767 |

## Precision at Confidence Thresholds
**BUY Model**
- P >= 0.50: 0.74195346653757
- Count >= 0.50: 34083
- P >= 0.55: 0.7819747955490012
- Count >= 0.55: 29836
- P >= 0.60: 0.8183816562440781
- Count >= 0.60: 26385
- P >= 0.65: 0.8520141222510528
- Count >= 0.65: 23509
- P >= 0.70: 0.8827397001087933
- Count >= 0.70: 21141
- P >= 0.75: 0.910477804852209
- Count >= 0.75: 18878
- P >= 0.80: 0.9338357464989319
- Count >= 0.80: 16852

**SELL Model**
- P >= 0.50: 0.7496410284197123
- Count >= 0.50: 36911
- P >= 0.55: 0.7884419787332408
- Count >= 0.55: 32445
- P >= 0.60: 0.8201655640608223
- Count >= 0.60: 28871
- P >= 0.65: 0.8515582708220555
- Count >= 0.65: 25862
- P >= 0.70: 0.878344031361737
- Count >= 0.70: 23213
- P >= 0.75: 0.906475517024265
- Count >= 0.75: 20647
- P >= 0.80: 0.9291627830473161
- Count >= 0.80: 18239
