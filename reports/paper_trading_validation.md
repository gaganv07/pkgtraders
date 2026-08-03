# Paper Trading Validation Report: Recalibrated Engine
**MT5 Demo Account Paper Trading Performance Analysis**
*Generated: 2026-06-24 13:10 UTC*

---

## 1. Executive Summary

This report documents the performance of the trade quality scoring engine in **Paper Trading Mode** over a 15-day chronological live market simulation (evaluating all symbols: `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `NAS100`, `US30`).

During this phase, the bot was configured as follows:
- `USE_RECALIBRATED_SCORING = True` (Recalibrated scoring active and executing trades)
- `SHADOW_MODE = False` (Trades actively routed to broker/MT5 client)
- **Trading Account**: MT5 Demo account (zero real capital risk)
- **Starting Balance**: $10,000.00
- **Scoring Threshold**: 65.0 (Moderate threshold recommended by final tuning phase)

### Deployment Recommendation

> [!WARNING]
> **Final Recommendation: NOT READY FOR LIVE DEPLOYMENT**
> While the safety guardrails and hard risk controls performed flawlessly, the recalibrated strategy did not achieve profitability. It suffered 5 consecutive losses on June 17, triggering the **consecutive-loss circuit breaker** which safely halted all trading to protect account equity. The strategy finished with a net loss of **-$515.84 (-5.16%)** over the 2-week period. We recommend retaining the strategy in a non-live state and optimizing the soft indicators or introducing regime-based threshold scaling before any live capital allocation.

---

## 2. Key Performance Metrics

| Metric | Target | Actual Paper Outcome | Status |
| :--- | :--- | :---: | :---: |
| **Total Trades** | 50 trades or 2 weeks | 19 trades (2 weeks complete) | ✅ Complete |
| **Win Rate** | > 20% | 26.32% (5 Wins / 14 Losses) | ✅ Passed |
| **Loss Rate** | - | 73.68% | - |
| **Gross Profit** | - | $195.26 | - |
| **Gross Loss** | - | $711.10 | - |
| **Profit Factor** | > 1.00 | 0.275 | ❌ Failed |
| **Net PnL** | Positive | -$515.84 | ❌ Failed |
| **Expectancy (R)** | Positive R | -0.456 R | ❌ Failed |
| **Average Quality Score** | - | 74.33 | - |
| **Average Holding Time** | - | 92.2 minutes (1.54 hours) | - |
| **Max Drawdown** | < 10% | 5.16% | ✅ Passed (Circuit breaker active) |

---

## 3. Comparison of Phases

| Metric | A/B Validation (Expected) | Shadow Validation (Expected) | Actual Paper Outcome |
| :--- | :---: | :---: | :---: |
| **Signal Volume** | 22,274 | 873 | 928 |
| **Executed Trades** | 82 (at 65.0 threshold) | 163 (at 65.0 threshold) | 19 |
| **Win Rate (%)** | 20.73% | N/A (No fills simulated) | 26.32% |
| **Profit Factor** | 1.13 | N/A | 0.275 |
| **Expectancy (R)** | +0.1392 R | N/A | -0.456 R |
| **Max Drawdown (%)** | 10.08% | 0.0% (Zero capital risk) | 5.16% |
| **Net PnL ($)** | +$492.34 (scaled) | $0.00 | -$515.84 |

---

## 4. Execution Highlights & Discrepancies

### 1. The Shadow vs. Paper Discrepancy (163 vs. 19 Trades)
In **Shadow Mode**, the recalibrated scoring engine appeared to accept **163 signals**. However, in **Paper Trading**, only **19 trades** were executed. This major difference is due to:
- **Active Position Cap**: The system has a strict limit of 3 maximum open positions. In paper trading, when 3 positions are open, all subsequent signals are rejected (`Position Limit.... FAIL`). In shadow mode, no trades are actually filled, so the active position count was always 0, leading to a false sense of high trade frequency.
- **Consecutive-Loss Circuit Breaker**: On June 17, the strategy hit 5 consecutive losses. This activated the `Circuit breaker active` hard veto. From June 17 through June 24, all 451 subsequent trade signals were rejected by this block. In shadow mode, since trade outcomes are not realized, the consecutive-loss count was never incremented, and the circuit breaker was never triggered.

### 2. Slippage & Fills
- **Slippage**: Simulated at 0.0 pips. Fill prices matched the exact tick arrival prices.
- **Fills**: Fills were instantaneous upon tick processing, with zero broker rejection.
- **Latency**: Sub-millisecond tick matching.

### 3. Spread Statistics
- Spreads were tightly controlled.
- Only 7 signals out of 928 were rejected by the max spread filter (`Spread Filter.... FAIL`), showing that during active trading hours, spread levels were within acceptable bounds.

---

## 5. Hard Safeguard & Risk Control Audits

The system's risk safeguards were evaluated and performed as follows:

- **Daily Drawdown (3% limit)**: **PASSED**. Daily loss never exceeded the 3% account balance limit on any single day.
- **Account Drawdown (10% limit)**: **PASSED**. Total account drawdown peaked at 5.16%, well below the 10.0% limit.
- **Consecutive-Loss Circuit Breaker (5 limit)**: **PASSED & TRIGGERED**. On June 17, the bot recorded its 5th consecutive loss:
  1. `2026-06-15 11:30`: USDJPY SHORT -> Loss (-1.00R)
  2. `2026-06-16 11:30`: USDJPY SHORT -> Loss (-1.00R)
  3. `2026-06-16 14:45`: NAS100 LONG -> Loss (-1.16R)
  4. `2026-06-17 07:00`: XAUUSD LONG -> Loss (-1.01R)
  5. `2026-06-17 08:30`: XAUUSD LONG -> Loss (-1.01R)
  
  The risk manager correctly set `self._circuit_broken = True`, stopping all live trade routing. This successfully protected the account from further losses in the second week.
- **Cooldown After Loss**: **PASSED**. The bot successfully enforced a cooldown period (e.g. 15 minutes) after every loss before considering new setups on the same symbol.
- **News Blackout**: **PASSED**. No trades were taken during high-impact news windows.
- **Position Limit**: **PASSED**. Max open positions never exceeded 3.

---

## 6. Recommendations & Next Steps

1. **Do Not Go Live**: The strategy should remain disabled for live execution on real funds.
2. **Review Consecutive Losses**: The 5 consecutive loss streak occurred across multiple symbols (`USDJPY`, `NAS100`, `XAUUSD`) in a short time window. This indicates a high correlation between symbols during periods of dollar strength/weakness.
3. **Correlation-Aware Risk Management**: Add logic to the risk manager to limit exposure to highly correlated symbols or restrict trading when multiple pairs are moving in the same direction.
4. **Scoring Model Calibration**: The recalibrated weights shifted scores up, but the threshold of 65.0 allowed too many low-expectancy trades. We should explore dynamic thresholding based on the current market regime or further optimize soft indicator parameters.
