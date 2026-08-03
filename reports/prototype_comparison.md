# BTCUSD Strategy Prototype Comparison
**Extended Historical Backtest Performance Across 5 New Modular Entry Engines**

## Performance Scorecard

| Rank | Strategy | Trades (N) | Win Rate | Expectancy | Profit Factor | Max Drawdown | Sharpe Ratio | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **BTC_P3_OrderFlow** | 2392 | 35.2% | +0.0560R | 1.08 | 18.87% | 0.564 | ✅ PASS |
| 2 | **BTC_P4_BreakRetest** | 1099 | 33.39% | +0.0002R | 0.99 | 29.95% | -0.070 | ✅ PASS |
| 3 | **BTC_P1_MSSSweep** | 1628 | 32.56% | -0.0243R | 0.96 | 41.49% | -0.319 | ❌ REJECT |
| 4 | **BTC_P5_Volatility** | 620 | 27.74% | -0.0290R | 0.95 | 24.96% | -0.336 | ❌ REJECT |
| 5 | **BTC_P2_Pullback** | 1524 | 27.62% | -0.0331R | 0.95 | 34.4% | -0.374 | ❌ REJECT |

---

## Strategy Logic Breakdowns

### 1. Market Structure Shift + Liquidity Sweep (BTC_P1_MSSSweep)
- **Concept**: Captures market reversal points on liquidity sweeps below/above key swing points.
- **Entry Trigger**: Sweep of 20-bar M15 high/low followed by a reversal close (MSS) in the direction of the H1 trend (EMA50 > EMA200).
- **SL/TP**: SL at swing extreme, TP at 2.0R.

### 2. Pullback Trend Continuation (BTC_P2_Pullback)
- **Concept**: Enters trend retracements at moving average support/resistance.
- **Entry Trigger**: Price touches M15 EMA50 and forms a prominent rejection wick (wick size $\ge$ 1.2x body) aligned with the H1 trend structure.
- **SL/TP**: SL below pullback low, TP at 2.5R.

### 3. Volume Delta / Order Flow Momentum (BTC_P3_OrderFlow)
- **Concept**: Capitalizes on heavy institutional volume breakouts.
- **Entry Trigger**: Breakout candle with volume expansion $\ge$ 1.8x the 20-bar average tick volume and body size $\ge$ 1.0x ATR.
- **SL/TP**: SL at 1.5x ATR, TP at 2.0R.

### 4. Break-Retest Structure (BTC_P4_BreakRetest)
- **Concept**: Trades breakout confirmations at horizontal support/resistance levels.
- **Entry Trigger**: Close above/below a stable 50-bar S/R level, followed by a pullback retest and a confirming reversal candle.
- **SL/TP**: SL beyond retest low/high, TP at 2.0R.

### 5. Volatility Squeeze Breakout (BTC_P5_Volatility)
- **Concept**: Exploits compression-expansion cycles.
- **Entry Trigger**: Bollinger Bandwidth contracts into the 25th percentile of its 100-bar history, followed by a breakout close outside the bands in the H1 trend direction.
- **SL/TP**: SL at 1.5x ATR, TP at 2.5R.
