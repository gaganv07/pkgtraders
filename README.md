# XAUUSD Pro Scalper — Institutional Multi-Asset Trading System

A production-grade, automated MetaTrader 5 trading bot built for **XAUUSD (Gold)** and major FX/Crypto pairs. Features a multi-phase signal engine, AI/ML quality scoring, live risk management, a real-time web dashboard, and a full strategy certification suite.

> ⚠️ **For educational and research purposes.** Always paper-trade before using any automated system with real capital. Past backtested performance does not guarantee future results.

---

## Architecture Overview

```
xauusd_pro/
├── app/                    # Core bot engine
│   ├── main.py             # System orchestrator & async event loop
│   ├── config.py           # Environment configuration
│   ├── mt5_client.py       # MetaTrader 5 client (multi-symbol)
│   ├── mt5_connection.py   # Connection lifecycle & safety checks
│   ├── mt5_connector.py    # Low-level MT5 connector
│   ├── trade_engine.py     # Signal evaluation & order execution
│   ├── trade_quality.py    # Multi-factor quality scoring engine
│   ├── risk_manager.py     # Drawdown limits & circuit breaker
│   ├── position_sizer.py   # Dynamic lot sizing
│   ├── ml_layer.py         # ML win-rate filter
│   ├── market_data.py      # Multi-timeframe indicator engine
│   ├── market_selector.py  # Symbol ranking & selection
│   ├── session.py          # Session & news calendar filter
│   ├── health.py           # System health monitor
│   ├── database.py         # SQLite trade & event journal
│   ├── notifier.py         # Telegram notifications
│   └── ...
├── strategies/             # Strategy definitions
│   ├── context.py          # StrategyContext data model
│   ├── signal.py           # StrategySignal output
│   └── prototypes/         # Strategy implementations (P4, etc.)
├── scripts/                # Diagnostic & validation utilities
│   ├── mt5_history_repair.py   # MT5 history/tick repair tool
│   ├── mt5_integration_test.py # Full MT5 integration test suite
│   ├── strategy_validation.py  # 11-phase strategy certification
│   ├── verify_vantage_account.py
│   └── ...
├── dashboard/              # FastAPI + Plotly web dashboard
│   └── app.py
├── backtesting/            # Backtesting engine
├── reports/                # Generated performance reports (.md)
├── database/               # SQLite database (auto-created)
├── logs/                   # Log files (auto-created)
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
└── main.py                 # Entry point
```

---

## Quick Start

### 1. Prerequisites

- **Python 3.11+** on Windows
- **MetaTrader 5** terminal installed and configured with a broker account
- A MetaTrader 5 broker account (Demo recommended for testing)

### 2. Clone the Repository

```bash
git clone https://github.com/gaganv07/pkgtraders.git
cd pkgtraders
```

### 3. Create Virtual Environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux (not supported for MT5)
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment

```bash
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
```

Edit `.env` with your actual credentials:

```env
MT5_LOGIN=25687070
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Demo
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
MAGIC_NUMBER=20250701
SYMBOL=XAUUSD
TIMEFRAME=M15
```

> **NEVER commit `.env` to version control.** It is listed in `.gitignore`.

### 6. MT5 Terminal Setup

1. Open your MetaTrader 5 terminal and log in to your broker account.
2. Enable **AutoTrading** (press `Ctrl+E` or click the AutoTrading button in the toolbar).
3. Ensure `XAUUSD` is visible in **Market Watch** (`Ctrl+M`).
4. Keep the MT5 terminal open while the bot is running.

---

## Running the Bot

```bash
# From the project root (xauusd_pro/)
.venv\Scripts\python.exe main.py
```

The bot will:
1. Connect to your MT5 account and verify credentials
2. Discover and validate all configured symbols
3. Warm up all indicators across M1/M5/M15/H1 timeframes
4. Start the live trading loop (scanning, signaling, executing)
5. Serve the web dashboard at **http://localhost:8080**

To stop the bot, press **Ctrl+C**.

---

## Web Dashboard

Open **http://localhost:8080** in your browser after starting the bot.

The dashboard shows:
- Live account balance, equity, and drawdown
- Open positions and P&L
- Market state (bid/ask, spread, ATR, VWAP)
- Order flow, DOM/liquidity, and microstructure analysis
- ML layer status
- Recent trade history

---

## MT5 History Repair

If you see MT5 Journal errors like `'XAUUSD' file write error [18]` or `synchronization process failed [XAUUSD]`:

```bash
.venv\Scripts\python.exe scripts/mt5_history_repair.py
```

This will diagnose the root cause, back up and remove any corrupted cache files, and force MT5 to rebuild the XAUUSD history database. A full report is saved to `reports/mt5_history_repair_report.md`.

---

## MT5 Integration Test

Verify your full MT5 environment before live trading:

```bash
.venv\Scripts\python.exe scripts/mt5_integration_test.py
```

Tests:
1. Connection & account safety
2. Symbol discovery & market watch
3. Historical data (M1..D1)
4. Live tick stream

---

## Strategy Certification (Backtesting)

Run the 11-phase strategy validation suite:

```bash
.venv\Scripts\python.exe scripts/strategy_validation.py
```

Generates reports in `reports/` covering:
- Walk-forward validation
- Monte Carlo stress testing
- Market regime analysis
- Statistical significance testing
- Production readiness certification

---

## Active Symbols

The bot trades across these symbols (auto-discovered from your broker):

| Symbol | Description |
|:---|:---|
| XAUUSD | Gold vs USD (primary) |
| EURUSD | Euro vs USD |
| GBPUSD | British Pound vs USD |
| USDJPY | USD vs Japanese Yen |
| BTCUSD | Bitcoin vs USD |
| NAS100 | NASDAQ 100 Index |

---

## Risk Management

All risk parameters are configured via `.env`:

| Parameter | Default | Description |
|:---|:---:|:---|
| `RISK_PER_TRADE_PCT` | 1.0% | Max risk per trade |
| `DAILY_DD_LIMIT_PCT` | 3.0% | Daily drawdown circuit breaker |
| `WEEKLY_DD_LIMIT_PCT` | 6.0% | Weekly drawdown circuit breaker |
| `ACCOUNT_DD_LIMIT_PCT` | 10.0% | Account-level emergency stop |
| `MAX_OPEN_TRADES` | 3 | Maximum concurrent open positions |

---

## Safety Notes

- **Demo first.** Always validate on a Demo account before risking real capital.
- **Never share your `.env` file.** It contains your MT5 credentials.
- **The bot runs in hedge mode.** Ensure your broker account supports hedging.
- **MT5 must remain open.** The Python API requires the MT5 terminal process to be running.
- **Do not run two MT5 terminals** pointing to the same data folder simultaneously.

---

## License

This project is for educational and research purposes. Use at your own risk.
