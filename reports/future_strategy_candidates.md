# Future Strategy Candidates — Research Phase 3 Planning

> These are research-driven strategy **concepts** directly suggested by Phase 2 evidence.
> No strategy code exists yet. This document is a design brief for Phase 3.

---

## Candidate 1 — Regime-Gated Session Momentum
**Evidence base**: Session analysis + regime detection modules

- Enter only during OVERLAP/LONDON session
- Only when regime = STRONG_TREND or EXPANSION
- Direction = EMA alignment direction
- Target: 1R exit, 0.8R stop
- Rationale: Combines the two strongest filters from Phase 2 into one gate

---

## Candidate 2 — ATR Expansion Momentum
**Evidence base**: ATR analysis module

- Wait for ATR percentile to cross from below 40% to above 60% within 3 bars
- Enter in direction of the expansion candle
- Target: 1.5R, stop: 1R
- Rationale: ATR expansion predicts follow-through in the direction of the move

---

## Candidate 3 — VWAP Mean Reversion
**Evidence base**: Mean reversion study module

- Enter when price deviates >1.5R from VWAP
- Counter-trend entry toward VWAP
- Target: VWAP level, stop: deviation + 0.5R
- Rationale: >75% return probability at +10 bars for 1–2R VWAP deviation

---

## Candidate 4 — False Breakout Fade
**Evidence base**: Breakout study module

- Detect breakout of 10-bar prior high/low
- If price closes back inside within 2 bars → fade entry
- Direction: against the breakout
- Target: 50% retracement of the false break, stop: breakout extreme
- Rationale: Failed breakouts show rapid reversal behaviour

---

## Candidate 5 — Shallow Pullback Continuation
**Evidence base**: Pullback study module

- After impulse move ≥1.5R, wait for 0–25% pullback
- Enter in original impulse direction
- Target: 1R, stop: 50% of impulse
- Rationale: 0–25% pullbacks show highest continuation probability

---

## Candidate 6 — Optimal Hold Period System
**Evidence base**: Holding time analysis module

- Enter at session open (London), exit after optimal hold period per symbol
- No dynamic exit — pure time-based exit
- Rationale: Certain hold periods show above-random Sharpe on specific symbols

---

## Candidate 7 — Liquidity Sweep Reversal
**Evidence base**: Pattern mining module

- Detect liquidity sweep: wick beyond prior high/low with close reversal
- Enter opposite to the sweep direction
- Target: 1R from swept level, stop: wick extreme
- Rationale: Liquidity sweeps show directional bias in subsequent bars

---

## Candidate 8 — Compression Breakout
**Evidence base**: Regime detection + pattern mining

- Detect 3+ consecutive bars with body < 30% of ATR (COMPRESSION regime)
- Enter on the first expansion bar after compression
- Direction = expansion bar direction
- Target: 2R, stop: midpoint of compression range
- Rationale: Compression consistently precedes expansion across all symbols

---

## Candidate 9 — High-Tradeability Symbol Focus
**Evidence base**: Symbol analysis module

- Restrict trading to the top 3 symbols by tradeability score
- Apply best session and regime filters on those symbols only
- Rationale: Concentrating on the best-behaved symbols reduces noise

---

## Candidate 10 — Feature-Ranked Multi-Condition Entry
**Evidence base**: Feature correlation module

- Only use features with |r| > 0.05 and p < 0.05 in entry conditions
- Remove all features with |r| < 0.02 (no edge)
- Build entry score from: ATR percentile + Session + Regime + EMA alignment
- Enter only when composite score exceeds threshold
- Rationale: Data-driven feature selection replaces assumption-driven scoring

---

## Implementation Priority

| Priority | Candidate | Reasoning |
|:---|:---|:---|
| 1 | Candidate 3 (VWAP Mean Reversion) | Highest statistical significance from MR study |
| 2 | Candidate 1 (Regime-Gated Session Momentum) | Combines two strongest Phase 2 filters |
| 3 | Candidate 7 (Liquidity Sweep Reversal) | Pattern with most significant p-value |
| 4 | Candidate 4 (False Breakout Fade) | Exploits confirmed false breakout behaviour |
| 5 | Candidate 5 (Shallow Pullback Continuation) | Cleanest continuation edge |

> **Note**: All candidates must be formally backtested, walk-forward validated, and 
> Monte Carlo tested before any production consideration.