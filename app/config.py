"""
app/config.py — Centralised Configuration

All settings loaded from .env, exposed as typed dataclasses.
Multi-asset upgrade: adds SymbolConfig roster, MarketSelectorConfig,
and PerformanceConfig.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

logger = logging.getLogger(__name__)


def _s(k: str, d: str = "") -> str:
    return os.getenv(k, d).strip()

def _f(k: str, d: float) -> float:
    try: return float(os.getenv(k, str(d)))
    except ValueError: return d

def _i(k: str, d: int) -> int:
    try: return int(os.getenv(k, str(d)))
    except ValueError: return d

def _b(k: str, d: bool) -> bool:
    v = os.getenv(k, str(d)).strip().lower()
    return v in ("true", "1", "yes")

def _list(k: str, d: str = "") -> List[str]:
    raw = os.getenv(k, d).strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── Recalibration Switches and Dynamic Config Loading ──────────────────────────
USE_RECALIBRATED_SCORING = _b("USE_RECALIBRATED_SCORING", False)
SHADOW_MODE = _b("SHADOW_MODE", True)

# ── V3 Scoring (forensics-backed redesign) ─────────────────────────────────────
# Set USE_V3_SCORING=true in .env to activate the V3 engine.
# V3 is additive — legacy/recalibrated code paths remain intact.
USE_V3_SCORING = _b("USE_V3_SCORING", False)
# Hard veto if ATR percentile is below this value (0-100).
# Prevents tight-stop traps in low-volatility environments.
V3_MIN_ATR_PERCENTILE = _f("V3_MIN_ATR_PERCENTILE", 25.0)

RECOMMENDED_WEIGHTS = {}
RECOMMENDED_THRESHOLD = {}

_weights_path = _ROOT / "reports" / "recommended_weights.json"
_threshold_path = _ROOT / "reports" / "recommended_threshold.json"

if USE_RECALIBRATED_SCORING or SHADOW_MODE:
    try:
        loaded_w = False
        loaded_t = False
        if _weights_path.exists():
            with open(_weights_path, "r") as f:
                RECOMMENDED_WEIGHTS = json.load(f)
                loaded_w = True
        if _threshold_path.exists():
            with open(_threshold_path, "r") as f:
                RECOMMENDED_THRESHOLD = json.load(f)
                loaded_t = True
        
        if (USE_RECALIBRATED_SCORING or SHADOW_MODE) and (not loaded_w or not loaded_t):
            raise FileNotFoundError("Missing recommended_weights.json or recommended_threshold.json")
    except Exception as e:
        import warnings
        warnings.warn(
            f"Failed to load dynamic scoring configuration: {e}. Falling back to legacy scoring."
        )
        USE_RECALIBRATED_SCORING = False


# ── Per-symbol configuration ──────────────────────────────────────────────────

@dataclass
class SymbolConfig:
    """Per-symbol trading parameters."""
    enabled:                bool  = True
    atr_sl_mult:            float = 0.0    # 0 = use global RiskConfig.atr_sl_mult
    max_spread_pts:         float = 50.0   # reject trade if spread exceeds this
    min_atr:                float = 0.0    # reject trade if ATR < this (0 = skip check)
    contract_size_override: float = 0.0    # 0 = read from MT5 symbol_info
    # Per-symbol session preference (empty = use global session)
    preferred_sessions:     List[str] = field(default_factory=list)


# ── Symbol roster ─────────────────────────────────────────────────────────────
# Each key is the symbol name exactly as it appears in MT5.
# Brokers may suffix with 'm', '+', '.a' etc — the MT5Client discovery handles that.
# Disable any symbol by setting enabled=False or BTCUSD_ENABLED=false in .env.

_DEFAULT_SYMBOLS: Dict[str, SymbolConfig] = {
    "XAUUSD": SymbolConfig(
        max_spread_pts=60,
        min_atr=0.30,
        preferred_sessions=["LONDON", "NEW_YORK"],
    ),
    "EURUSD": SymbolConfig(
        max_spread_pts=15,
        min_atr=0.0003,
        preferred_sessions=["LONDON", "NEW_YORK"],
    ),
    "GBPUSD": SymbolConfig(
        max_spread_pts=20,
        min_atr=0.0003,
        preferred_sessions=["LONDON"],
    ),
    "USDJPY": SymbolConfig(
        max_spread_pts=20,
        min_atr=0.03,
        preferred_sessions=["TOKYO", "LONDON"],
    ),
    "NAS100": SymbolConfig(
        max_spread_pts=300,
        min_atr=5.0,
        preferred_sessions=["NEW_YORK"],
    ),
    "US30": SymbolConfig(
        max_spread_pts=400,
        min_atr=10.0,
        preferred_sessions=["NEW_YORK"],
    ),
    "BTCUSD": SymbolConfig(
        enabled=False,           # Enabled via BTCUSD_ENABLED=true in .env
        max_spread_pts=3000,
        min_atr=50.0,
        preferred_sessions=[],   # 24/7 — no session preference
    ),
}

SYMBOL_CONFIGS: Dict[str, SymbolConfig] = _DEFAULT_SYMBOLS


# ── MT5 configuration ─────────────────────────────────────────────────────────

@dataclass
class MT5Config:
    login:               int   = field(default_factory=lambda: _i("MT5_LOGIN", 0))
    password:            str   = field(default_factory=lambda: _s("MT5_PASSWORD"))
    server:              str   = field(default_factory=lambda: _s("MT5_SERVER"))
    path:                str   = field(default_factory=lambda: _s("MT5_PATH"))
    symbol_override:     str   = field(default_factory=lambda: _s("SYMBOL"))
    timeframe:           str   = field(default_factory=lambda: _s("TIMEFRAME", "M15"))
    timeout_ms:          int   = 60_000
    reconnect_attempts:  int   = 15
    reconnect_delay_s:   float = 5.0
    deviation_pts:       int   = 20
    magic:               int   = field(default_factory=lambda: _i("MAGIC_NUMBER", 20250701))
    dom_subscribe:       bool  = True


# ── Risk configuration ────────────────────────────────────────────────────────

@dataclass
class RiskConfig:
    # ── Initial capital (configurable via INITIAL_BALANCE) ──────────────────
    initial_balance:     float = field(default_factory=lambda: _f("INITIAL_BALANCE", 500.0))
    # ── Position sizing ──────────────────────────────────────────────────────
    risk_per_trade_pct:  float = field(default_factory=lambda: _f("RISK_PER_TRADE_PCT", 1.0))
    compounding_enabled: bool  = field(default_factory=lambda: _b("COMPOUNDING_ENABLED", True))
    # ── Drawdown limits ──────────────────────────────────────────────────────
    daily_dd_limit:      float = field(default_factory=lambda: _f("DAILY_DD_LIMIT_PCT", 3.0))
    weekly_dd_limit:     float = field(default_factory=lambda: _f("WEEKLY_DD_LIMIT_PCT", 6.0))
    account_dd_limit:    float = field(default_factory=lambda: _f("ACCOUNT_DD_LIMIT_PCT", 10.0))
    # ── Position controls ─────────────────────────────────────────────────────
    max_open_trades:     int   = field(default_factory=lambda: _i("MAX_OPEN_TRADES", 3))
    max_risk_exposure:   float = field(default_factory=lambda: _f("MAX_RISK_EXPOSURE_PCT", 3.0))
    min_quality_score:   float = field(default_factory=lambda: _f("MIN_QUALITY_SCORE", 80.0))
    # ── TP/SL and exit parameters ─────────────────────────────────────────────
    atr_sl_mult:         float = 1.5
    tp1_rr:              float = 1.0
    tp2_rr:              float = 2.0
    tp3_rr:              float = 3.0
    tp1_close_pct:       float = 0.30
    tp2_close_pct:       float = 0.30
    breakeven_rr:        float = 1.0
    trail_rr:            float = 1.5
    trail_atr_mult:      float = 0.8
    max_trade_dur_h:     float = 4.0
    # ── Circuit breaker ───────────────────────────────────────────────────────
    circuit_loss_streak: int   = 5
    circuit_exec_fails:  int   = 3
    cooldown_after_loss_m: float = 15.0
    # ── Consecutive-loss risk reduction ───────────────────────────────────────
    loss_streak_reduce_risk: bool  = field(default_factory=lambda: _b("LOSS_STREAK_REDUCE_RISK", True))
    loss_streak_threshold:   int   = 2    # After N consecutive losses, reduce risk
    loss_streak_risk_factor: float = 0.5  # Multiply risk_pct by this during streak
    use_recalibrated_scoring: bool = field(default_factory=lambda: USE_RECALIBRATED_SCORING)
    shadow_mode:              bool = field(default_factory=lambda: SHADOW_MODE)
    # ── V3 scoring ────────────────────────────────────────────────────────────
    use_v3_scoring:           bool  = field(default_factory=lambda: USE_V3_SCORING)
    v3_min_atr_percentile:    float = field(default_factory=lambda: V3_MIN_ATR_PERCENTILE)
    # ── Correlation cap (always-on for V3+ safety) ────────────────────────────
    # Max open trades in the same USD-correlated group (prevents cascade stop-outs)
    max_same_corr_group_trades: int = field(default_factory=lambda: _i("MAX_SAME_CORR_GROUP_TRADES", 2))


# ── Session configuration ─────────────────────────────────────────────────────

@dataclass
class SessionConfig:
    london_start:  int = 7
    london_end:    int = 16
    ny_start:      int = 12
    ny_end:        int = 20
    overlap_start: int = 12
    overlap_end:   int = 16
    tokyo_start:   int = 0    # UTC
    tokyo_end:     int = 9
    news_pre_m:    int = 30
    news_post_m:   int = 30   # Upgraded: was 15, now 30 per spec


# ── Quality weights ───────────────────────────────────────────────────────────

@dataclass
class QualityWeights:
    order_flow:       float = 0.35
    liquidity:        float = 0.25
    market_structure: float = 0.15
    volatility:       float = 0.10
    session:          float = 0.10
    news:             float = 0.05


# ── Market Selector configuration ─────────────────────────────────────────────

@dataclass
class MarketSelectorConfig:
    """Controls the continuous multi-asset ranking engine."""
    scan_interval_s:        float = field(default_factory=lambda: _f("SCAN_INTERVAL_S", 5.0))
    min_symbol_score:       float = field(default_factory=lambda: _f("MIN_SYMBOL_SCORE", 55.0))
    # Ranking weights (must sum to ~1.0)
    w_trend:                float = 0.25    # EMA cross-TF alignment
    w_volatility:           float = 0.20    # ATR percentile (prefer expanding)
    w_order_flow:           float = 0.20    # CVD momentum
    w_session:              float = 0.15    # Session suitability for symbol
    w_spread:               float = 0.10    # Relative spread quality
    w_volume:               float = 0.10    # Tick volume rank


# ── Performance tracker configuration ────────────────────────────────────────

@dataclass
class PerformanceConfig:
    """Controls the live performance tracker."""
    log_interval_s:  int   = 300    # How often to log a perf snapshot
    sharpe_window:   int   = 50     # Last N trades for Sharpe estimate
    export_csv:      bool  = True   # Export perf snapshots to CSV


# ── ML configuration ─────────────────────────────────────────────────────────

@dataclass
class MLConfig:
    enabled:     bool  = field(default_factory=lambda: _b("ML_ENABLED", True))
    min_samples: int   = field(default_factory=lambda: _i("ML_MIN_SAMPLES", 50))
    model_path:  str   = "database/ml_model.json"
    retrain_every_n_trades: int = 20


# ── Telegram configuration ────────────────────────────────────────────────────

@dataclass
class TelegramConfig:
    bot_token: str = field(default_factory=lambda: _s("TELEGRAM_BOT_TOKEN"))
    chat_id:   str = field(default_factory=lambda: _s("TELEGRAM_CHAT_ID"))

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


# ── News configuration ────────────────────────────────────────────────────────

@dataclass
class NewsConfig:
    news_api_key:          str = field(default_factory=lambda: _s("NEWS_API_KEY"))
    marketaux_key:         str = field(default_factory=lambda: _s("MARKETAUX_API_KEY"))
    trading_economics_key: str = field(default_factory=lambda: _s("TRADING_ECONOMICS_KEY"))
    fetch_interval_s:      int = 300
    enabled:               bool = True


# ── Dashboard configuration ───────────────────────────────────────────────────

@dataclass
class DashboardConfig:
    host:    str = field(default_factory=lambda: _s("DASHBOARD_HOST", "0.0.0.0"))
    port:    int = field(default_factory=lambda: _i("DASHBOARD_PORT", 8080))
    api_key: str = field(default_factory=lambda: _s("DASHBOARD_API_KEY", "changeme"))
    refresh_s: int = 5


# ── System configuration ──────────────────────────────────────────────────────

@dataclass
class SystemConfig:
    log_level:  str = field(default_factory=lambda: _s("LOG_LEVEL", "INFO"))
    db_path:    str = field(default_factory=lambda: _s("DB_PATH", "database/trading.db"))
    log_dir:    str = "logs"
    report_dir: str = "reports"
    env:        str = field(default_factory=lambda: _s("ENVIRONMENT", "production"))


# ── Root Settings ─────────────────────────────────────────────────────────────

@dataclass
class Settings:
    mt5:       MT5Config          = field(default_factory=MT5Config)
    risk:      RiskConfig         = field(default_factory=RiskConfig)
    session:   SessionConfig      = field(default_factory=SessionConfig)
    quality:   QualityWeights     = field(default_factory=QualityWeights)
    selector:  MarketSelectorConfig = field(default_factory=MarketSelectorConfig)
    perf:      PerformanceConfig  = field(default_factory=PerformanceConfig)
    ml:        MLConfig           = field(default_factory=MLConfig)
    telegram:  TelegramConfig     = field(default_factory=TelegramConfig)
    news:      NewsConfig         = field(default_factory=NewsConfig)
    dashboard: DashboardConfig    = field(default_factory=DashboardConfig)
    system:    SystemConfig       = field(default_factory=SystemConfig)


settings = Settings()


# ── Runtime symbol roster ─────────────────────────────────────────────────────
# Apply .env overrides after settings object is created.

def _apply_env_symbol_overrides() -> None:
    """
    Apply environment-variable overrides to SYMBOL_CONFIGS.
    BTCUSD_ENABLED=true  → enables BTCUSD
    SYMBOLS_DISABLED=NAS100,US30  → disables listed symbols
    """
    if _b("BTCUSD_ENABLED", False):
        SYMBOL_CONFIGS["BTCUSD"].enabled = True

    disabled = _list("SYMBOLS_DISABLED")
    for sym in disabled:
        if sym in SYMBOL_CONFIGS:
            SYMBOL_CONFIGS[sym].enabled = False


_apply_env_symbol_overrides()


def enabled_symbols() -> List[str]:
    """Returns the list of currently enabled symbols in config order."""
    return [sym for sym, cfg in SYMBOL_CONFIGS.items() if cfg.enabled]
