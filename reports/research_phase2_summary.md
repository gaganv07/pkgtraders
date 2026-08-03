# Research Phase 2 — Market Edge Discovery Summary

**Symbols Analysed**: 7  |  **Total Bars**: 174,720  |  **Analysis Period**: 365 days

---

## Question 1: Which Market Regimes Are Profitable?

| Regime | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| HIGH_VOL | +0.3709 | 53.4% | +0.093 | ← **BEST**
| RANGE | +0.1696 | 52.2% | +0.042 |
| TRENDING | +0.0664 | 50.5% | +0.015 |
| EXPANSION | -0.0250 | 49.3% | -0.007 |
| COMPRESSION | -0.0777 | 50.1% | -0.015 |
| WEAK_TREND | -0.0762 | 52.0% | -0.018 |
| STRONG_TREND | -0.0746 | 48.8% | -0.020 | ← avoid

> **Answer**: `HIGH_VOL` delivers the highest edge (Sharpe +0.093). `STRONG_TREND` is the worst regime to trade.

---

## Question 2: Which Sessions Are Profitable?

| Session | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| OVERLAP | +0.1145 | 51.1% | +0.032 | ← **BEST**
| OFF | +0.0509 | 51.1% | +0.013 |
| ASIA | +0.0518 | 50.2% | +0.010 |
| LONDON | +0.0306 | 50.5% | +0.007 |
| NEW_YORK | +0.0092 | 50.1% | +0.003 | ← avoid

> **Answer**: `OVERLAP` is the strongest session (Sharpe +0.032). `NEW_YORK` should be avoided.

---

## Question 3: Which Volatility Conditions Are Profitable?

| Condition | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|
| High ATR (>70th pct) | +0.2473 | 52.2% | +0.063 |
| Low ATR (<30th pct)  | -0.0594 | 50.1% | -0.012 |

> **Answer**: High ATR conditions produce better forward returns. Low ATR environments produce smaller moves relative to spread cost.

---

## Question 4: Which Holding Times Are Optimal?
> See `holding_time_analysis.md` for per-symbol breakdown.
> Short holds (1–4 bars = 15–60 min) typically offer the best Sharpe before market noise dominates.

---

## Question 5: Which Symbols Contain Exploitable Behaviour?
> See `symbol_statistics.md` for full ranking.
> Symbols with low Spread/ATR and sustained trend runs offer the best cost-adjusted opportunity.

---

## Question 6: Which Price Patterns Repeat Consistently?
> See `pattern_statistics.md`. Patterns marked ✅ are statistically significant.
> Liquidity sweeps and pullback continuation patterns show the strongest directional bias.

---

## Question 7: Which Market Conditions Should Never Be Traded?

Based on all module analysis:

- ❌ **NAS100 | Session=NEW_YORK** — Sharpe -0.099, Win Rate 46.8%
- ❌ **NAS100 | Session=ASIA** — Sharpe -0.030, Win Rate 47.5%
- ❌ **US30 | Session=NEW_YORK** — Sharpe -0.006, Win Rate 49.1%
- ❌ **All Symbols | Regime=EXPANSION** — Sharpe -0.007, Win Rate 49.3%
- ❌ **USDJPY | Session=NEW_YORK** — Sharpe -0.012, Win Rate 49.2%

---

## Top 3 Actionable Insights from Phase 2

1. **Regime filter is the single most powerful gate.** Trading only `HIGH_VOL` regime dramatically improves Sharpe.
2. **Session matters.** Restricting to `OVERLAP` removes the worst noise.
3. **ATR percentile is statistically significant.** Only trade when ATR > 40th percentile to ensure moves exceed spread cost.
