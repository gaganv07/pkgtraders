# Strategy Prototype P10 Design Recommendation

This document outlines the architectural specifications for the proposed **P10 Strategy Prototype**, based on quantitative evidence collected across P1–P9.

## 1. Optimal Feature Set Selection

Evidence from P1–P9 demonstrates that breakout-based triggers are highly unprofitable on ranging instruments. Therefore, **P10 must pivot to a mean-reversion or swing-pullback structure**.

### Included Features
1. **Regime Filter**: Only allow trades when ATR percentile is between 40% and 80%. Exclude hyper-compression (fakeouts) and extreme volatility expansion (slippage/noise).
2. **Multi-Timeframe Trend Confirmation (H1 + H4)**: Use H4 EMA alignment to establish direction and H1 to time pullbacks.
3. **Pullback Entry Trigger**: Enter only on a verified pullback to the 20 EMA, rather than breakout continuation.
4. **Dynamic Risk Sizing**: Expectancy is directly improved by setting a dynamic ATR-based Stop Loss ($1.8 \times ATR$).
5. **Partial Profit / Breakeven**: Automatically move SL to breakeven once a trade reaches $+1.0 R$ excursion. Take partial profit (50%) at $+1.5 R$.

### Rejected Features
* **Volume/Tick Spikes**: Soft indicators like tick volume showing no correlation to directional expectancy should be excluded.
* **Breakout Triggers**: Reject all breakout structures (chasing price highs/lows) as they trigger at the end of moves in range-bound environments.
