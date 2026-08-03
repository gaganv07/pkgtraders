# Forensic Strategy Recommendations
**Actions based on Root Cause Analysis**

## Short-Term Fixes (No Code Changes)
1. **Regime Veto**: Keep the V3 Quality score gate threshold strictly set to $\ge 68.0$ to reject noisy trade setups during consolidation periods.
2. **Shorten Execution Windows**: Trade only during the peak liquidity hours of the London/NY Overlap (12:00 - 15:30 UTC).

## Structural Modifications (Future Implementations)
1. **Reversal over Breakout**: Pivot from a breakout system to a mean-reversion setup when the ATR percentile drops below the 40th percentile.
2. **Dynamic trailing stop**: Tighten stops to breakeven once a trade reaches $1.0 \times$ risk.
