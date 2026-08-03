# strategies/prototypes/__init__.py
from strategies.prototypes.p1_market_auction import MarketAuctionStrategy
from strategies.prototypes.p2_order_flow_imbalance import OrderFlowImbalanceStrategy
from strategies.prototypes.p3_liquidity_sweep_reversal import LiquiditySweepReversalStrategy
from strategies.prototypes.p4_opening_range_breakout import OpeningRangeBreakoutStrategy
from strategies.prototypes.p5_vwap_mean_reversion import VWAPMeanReversionStrategy
from strategies.prototypes.p6_trend_pullback import TrendPullbackStrategy
from strategies.prototypes.p7_volatility_expansion import VolatilityExpansionStrategy
from strategies.prototypes.p8_orb_v2 import OpeningRangeBreakoutV2Strategy
from strategies.prototypes.p9_adaptive_breakout import AdaptiveBreakoutStrategy

# New BTCUSD strategies
from strategies.prototypes.btc_p1_mss_sweep import BTCMSSSweepStrategy
from strategies.prototypes.btc_p2_pullback import BTCPullbackStrategy
from strategies.prototypes.btc_p3_order_flow import BTCOrderFlowMomentumStrategy
from strategies.prototypes.btc_p4_break_retest import BTCBreakRetestStrategy
from strategies.prototypes.btc_p5_volatility import BTCVolatilitySqueezeStrategy

ALL_STRATEGIES = [
    MarketAuctionStrategy,
    OrderFlowImbalanceStrategy,
    LiquiditySweepReversalStrategy,
    OpeningRangeBreakoutStrategy,
    VWAPMeanReversionStrategy,
    TrendPullbackStrategy,
    VolatilityExpansionStrategy,
    OpeningRangeBreakoutV2Strategy,   # P8: forensics-backed ORB redesign
    AdaptiveBreakoutStrategy,         # P9: forensics-backed Adaptive Breakout
]

BTC_STRATEGIES = [
    BTCMSSSweepStrategy,
    BTCPullbackStrategy,
    BTCOrderFlowMomentumStrategy,
    BTCBreakRetestStrategy,
    BTCVolatilitySqueezeStrategy,
]

__all__ = [
    "MarketAuctionStrategy",
    "OrderFlowImbalanceStrategy",
    "LiquiditySweepReversalStrategy",
    "OpeningRangeBreakoutStrategy",
    "VWAPMeanReversionStrategy",
    "TrendPullbackStrategy",
    "VolatilityExpansionStrategy",
    "OpeningRangeBreakoutV2Strategy",
    
    "BTCMSSSweepStrategy",
    "BTCPullbackStrategy",
    "BTCOrderFlowMomentumStrategy",
    "BTCBreakRetestStrategy",
    "BTCVolatilitySqueezeStrategy",
    "AdaptiveBreakoutStrategy",
    
    "ALL_STRATEGIES",
    "BTC_STRATEGIES",
]
