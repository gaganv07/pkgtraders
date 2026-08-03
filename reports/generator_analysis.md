# Synthetic Generator Audit

## Hypothesis
The machine learning model achieved 74% out-of-sample accuracy not by discovering a genuine market edge, but by reverse-engineering the regime-state logic of the synthetic data generator.

## Return Autocorrelation (Drift)
- **Lag 1 Autocorrelation**: 0.9090
- **Lag 5 Autocorrelation**: 0.8438
- **Lag 10 Autocorrelation**: 0.7597

*Analysis*: Real financial markets typically have near-zero lag-1 return autocorrelation. A high value here indicates persistent deterministic drift programmed into the generator.

## Volatility Clustering
- **Lag 1 Abs Return AC**: 0.8916
- **Lag 10 Abs Return AC**: 0.7357

## Trend Persistence
- **Mean Consecutive Directional Bars**: 4.16
- **Maximum Consecutive Streak**: 293
- **% of streaks > 10 bars**: 3.55%

## Conclusion
The synthetic generator explicitly programs `trend_up` and `trend_down` regimes lasting 20-100 bars with directional Gaussian drift. Because the ML model takes trailing indicators (RSI, EMA gap) as inputs, it perfectly classifies the current underlying synthetic regime state. Since the state persists for tens of bars, predicting the next 20 bars becomes a trivial mathematical exercise.

This strongly supports the hypothesis that the 74% out-of-sample accuracy is a **synthetic artifact**.
