# Realism Study

## Hypothesis
If the ML model's 74% accuracy was genuinely discovering a robust market edge, it should degrade gracefully as realism increases. If it collapses to 50% (random), the model was exclusively exploiting the predictable mathematical artifacts of the naive synthetic generator.

## Modifications to Generator
- **Trend Persistence**: Reduced from 20-100 bars down to 5-20 bars.
- **Drift Strength**: Reduced by 75%.
- **Noise**: Added massive Gaussian noise component to price action, creating choppy spikes.
- **Shocks**: Added random 10% chance of a gap event at regime transitions.

## Results (BUY_EDGE)
| Model | Accuracy | Precision | Recall | F1 Score |
|---|---|---|---|---|
| **Logistic Regression (Naive Synthetic)** | 0.7423 | 0.7420 | 0.6482 | 0.6919 |
| **Logistic Regression (Realistic Synthetic)** | 0.5282 | 0.5149 | 0.2010 | 0.2892 |
| **Random Guess** | 0.4987 | 0.4761 | 0.5002 | 0.4879 |

## Conclusion
The model's performance collapsed completely to near-random levels when applied to a realistic price series. This confirms beyond a doubt that the 'edge' discovered in Phase 4 was entirely a synthetic artifact caused by generating auto-correlated trend walks. The ML model is **NOT** ready for live trading.
