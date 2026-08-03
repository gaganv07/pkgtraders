import sys, os
from collections import Counter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.p10_validation import _synthetic_bars
from strategies.prototypes.p10_hybrid_edge import P10HybridEdgeStrategy
from app.market_data import MultiSymbolMarketData, TF_M5, TF_M15, TF_H1
from strategies.context import StrategyContext
from datetime import datetime, timezone, timedelta

bars = _synthetic_bars("BTCUSD", 20)
msd = MultiSymbolMarketData(["BTCUSD"])
md = msd.get("BTCUSD")

strat = P10HybridEdgeStrategy()
reasons = Counter()

now = datetime.now(timezone.utc)
replay_start = now - timedelta(days=15)

# Load warm-up
wb_h1 = [b for b in bars[TF_H1] if b["time"] < replay_start]
wb_m15 = [b for b in bars[TF_M15] if b["time"] < replay_start]
wb_m5 = [b for b in bars[TF_M5] if b["time"] < replay_start]
md.load_bars(TF_H1, wb_h1)
md.load_bars(TF_M15, wb_m15)
md.load_bars(TF_M5, wb_m5)

for step in bars[TF_M15]:
    if step["time"] < replay_start: continue
    
    # Simple push (mocking timeline)
    md.push_bar(TF_M15, step)
    
    vol_st = md.volatility
    atr = md.atr(TF_M15) or md.atr(TF_M5) or 1.0

    ctx = StrategyContext(
        timestamp=step["time"], symbol="BTCUSD",
        bars_m15=md.bars(TF_M15), bars_h1=md.bars(TF_H1), bars_m5=md.bars(TF_M5),
        atr=atr, atr_m15=md.atr(TF_M15) or atr, vwap=md.vwap(), vwap_slope=md.vwap_slope(),
        ema50=md.ema50(TF_H1), ema200=md.ema200(TF_H1), ema50_m15=md.ema50(TF_M15),
        vol_state=vol_st
    )
    
    
    strat.on_bar(ctx)
    sig = strat.evaluate(ctx)
    reasons[sig.reason] += 1
    if sig.reason == "Missing ATR/VWAP":
        print(f"DEBUG: atr={atr}, vwap={ctx.vwap}, m15_len={len(strat._m15_highs)}, ema50={strat._ema50}")


print("Rejection Reasons:")
for r, count in reasons.most_common():
    print(f"  {count}: {r}")
