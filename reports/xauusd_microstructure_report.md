# XAUUSD (Gold) Market Microstructure & Bookmap Audit Report

**Generated At:** 2026-08-07T08:43:42.326683+00:00  
**Specialized Asset:** Gold Spot / US Dollar (`XAUUSD`)  

## 1. Session Volatility & Liquidity Window Analysis

- **Asian Session Consolidation Range:** `145.0 pips` average
- **London Session Open Volatility Multiplier:** `1.65x` baseline
- **New York Session Open Volatility Multiplier:** `1.85x` baseline
- **London-NY Overlap Volatility Peak:** `2.10x` **(Optimal Trading Window)**
- **COMEX Gold Futures Correlation:** `94.0%`

## 2. Institutional Wyckoff & Smart Money Concepts (SMC)

- **Post-Stop Sweep Reversal Probability:** `72.0%` *(High probability when liquidity grab occurs before entry)*
- **Bookmap Order Book Wall Absorption Success Rate:** `68.0%`
- **Passive Wall Stacking & Pulling Detection:** `ENABLED 🟢`

## 3. Recommended XAUUSD Execution Policy

1. **Focus Execution:** Prioritize entries during **12:30 PM IST (07:00 UTC) London Open** and **06:00 PM IST (12:30 UTC) NY Open**.
2. **Spread Protection:** Enforce strict spread ratio cap ($\le 1.5x$) during Asian session close (21:00-22:00 UTC).
3. **Liquidity Sweep Rule:** Grant bonus quality points to setups occurring directly after an Asian range high/low sweep.
