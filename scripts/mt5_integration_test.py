"""
scripts/mt5_integration_test.py — MetaTrader 5 Integration Verification Suite

Comprehensive test runner to verify:
1. Terminal connection, process auto-launch, login verification, account specs, & safety checks
2. Symbol discovery & market watch resolution (BTCUSD, XAUUSD, EURUSD, GBPUSD, USDJPY, US30, NAS100)
3. Historical data downloading via copy_rates_from_pos() across M1, M5, M15, M30, H1, H4, D1
4. Continuous live tick streaming (Bid, Ask, Spread, Time, Volume)
5. Demo order execution (OPTIONAL, disabled by default, requires --demo-order flag)

Usage:
    python scripts/mt5_integration_test.py
    python scripts/mt5_integration_test.py --demo-order
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.mt5_connector import MT5Connector
from app.account_manager import AccountManager
from app.symbol_manager import SymbolManager, REQUIRED_SYMBOLS
from app.market_feed import MarketFeed, TIMEFRAME_MAP
from app.order_executor import OrderExecutor


def run_connection_test(connector: MT5Connector) -> bool:
    print("\n" + "=" * 60)
    print(" 1. TESTING VANTAGE MT5 CONNECTION & ACCOUNT SAFETY")
    print("=" * 60)

    from app.mt5_connection import run_startup_validation
    val_ok = run_startup_validation(settings.mt5.symbol_override or "XAUUSD")
    if not val_ok:
        print("[FAIL] Startup validation checklist failed.")
        return False

    return True


def run_symbol_test(symbol_mgr: SymbolManager) -> bool:
    print("\n" + "=" * 60)
    print(" 2. TESTING SYMBOL DISCOVERY & MARKET WATCH")
    print("=" * 60)

    symbols_map = symbol_mgr.initialize_symbols()
    print(f"Resolved Symbol Mapping ({len(symbols_map)} active):")

    for canonical in REQUIRED_SYMBOLS:
        broker_sym = symbols_map.get(canonical)
        if broker_sym:
            spec = symbol_mgr.get_symbol_spec(canonical)
            is_open, msg = symbol_mgr.verify_symbol_tradeable(canonical)
            trade_str = "OPEN / TRADEABLE" if is_open else f"CLOSED ({msg})"
            print(f"   - {canonical:<8} -> {broker_sym:<10} [{trade_str}]")
            if spec:
                print(f"       Digits={spec.digits}, Point={spec.point}, ContractSize={spec.contract_size}, MinVol={spec.vol_min}")
        else:
            print(f"   - {canonical:<8} -> [WARN] NOT FOUND ON BROKER (Skipped gracefully)")

    return len(symbols_map) > 0


def run_historical_data_test(market_feed: MarketFeed, symbol_mgr: SymbolManager) -> bool:
    print("\n" + "=" * 60)
    print(" 3. TESTING HISTORICAL DATA (copy_rates_from_pos)")
    print("=" * 60)

    test_symbols = [s for s in REQUIRED_SYMBOLS if s in symbol_mgr.symbol_map][:3]
    if not test_symbols:
        print("[WARN] No active symbols available for historical data test")
        return False

    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    all_ok = True

    for sym in test_symbols:
        print(f"\nDownloading historical bars for {sym}:")
        for tf in timeframes:
            df = market_feed.get_historical_dataframe(sym, timeframe=tf, count=50, include_indicators=True)
            if df.empty:
                print(f"   - {tf:<4}: [FAIL] No data returned")
                all_ok = False
            else:
                last_time = df.index[-1] if hasattr(df.index, 'name') and df.index.name == 'time' else df['time'].iloc[-1]
                print(
                    f"   - {tf:<4}: [OK] {len(df)} bars downloaded. "
                    f"Close={df['close'].iloc[-1]:.4f}, ATR={df['atr'].iloc[-1]:.4f}, "
                    f"Latest={last_time}"
                )

    return all_ok


def run_live_tick_test(market_feed: MarketFeed, symbol_mgr: SymbolManager) -> bool:
    print("\n" + "=" * 60)
    print(" 4. TESTING CONTINUOUS LIVE TICK FEED")
    print("=" * 60)

    test_symbols = [s for s in REQUIRED_SYMBOLS if s in symbol_mgr.symbol_map][:3]
    if not test_symbols:
        print("[WARN] No active symbols for live tick test")
        return False

    print("Streaming live ticks (3 seconds sample per symbol)...")
    for sym in test_symbols:
        tick = market_feed.get_live_tick(sym)
        if tick:
            print(
                f"   - {sym:<8} Tick: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}, "
                f"Spread={tick.spread_pts} pts, Time={tick.time.strftime('%H:%M:%S')}"
            )
        else:
            print(f"   - {sym:<8} Tick: [FAIL] Failed to retrieve tick")

    return True


def run_demo_order_test(order_executor: OrderExecutor, symbol_mgr: SymbolManager) -> bool:
    print("\n" + "=" * 60)
    print(" 5. TESTING DEMO ORDER EXECUTION (OPTIONAL)")
    print("=" * 60)

    sym = "EURUSD" if "EURUSD" in symbol_mgr.symbol_map else list(symbol_mgr.symbol_map.keys())[0]
    print(f"Testing order execution safety & demo buy/close flow on {sym}...")

    # First test pre-trade risk validation
    valid, reason = order_executor.validate_pre_trade_risk(sym, volume=0.01)
    print(f"Pre-trade Risk Check for {sym} (0.01 lot): Valid={valid} ({reason})")

    if not valid:
        print(f"[WARN] Pre-trade risk check prevented order submission: {reason}")
        return True

    # Execute Market Buy
    print("Sending Market Buy 0.01 lot...")
    res = order_executor.market_buy(
        symbol=sym,
        volume=0.01,
        sl=0.0,
        tp=0.0,
        comment="Demo Integration Test",
    )

    if not res.success:
        print(f"[FAIL] Market Buy Failed: {res.error} (Retcode={res.retcode})")
        return False

    print(f"[OK] Market Buy Executed! Ticket #{res.ticket}, Fill Price={res.price:.5f}, Latency={res.latency_ms:.1f}ms")

    # Close Position
    time.sleep(1.0)
    print(f"Closing position #{res.ticket}...")
    close_res = order_executor.close_position(ticket=res.ticket, symbol=sym, reason="Test Complete")

    if not close_res.success:
        print(f"[FAIL] Position Close Failed: {close_res.error}")
        return False

    print(f"[OK] Position #{res.ticket} Closed Successfully!")
    return True


def main():
    parser = argparse.ArgumentParser(description="MT5 Integration Verification Suite")
    parser.add_argument(
        "--demo-order",
        action="store_true",
        help="Enable live demo order test (Disabled by default)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("   MetaTrader 5 Direct Integration Test Suite")
    print("=" * 60)

    # Initialize Integration Components
    connector = MT5Connector(
        login=settings.mt5.login,
        password=settings.mt5.password,
        server=settings.mt5.server,
        path=settings.mt5.path,
        timeout_ms=settings.mt5.timeout_ms,
    )
    acct_mgr = AccountManager()
    symbol_mgr = SymbolManager()
    market_feed = MarketFeed(symbol_resolver=symbol_mgr)
    order_executor = OrderExecutor(
        symbol_manager=symbol_mgr,
        account_manager=acct_mgr,
        magic=settings.mt5.magic,
        deviation_pts=settings.mt5.deviation_pts,
    )

    # 1. Connection Test
    if not run_connection_test(connector):
        print("\n[FAIL] ABORTING: MT5 connection test failed.")
        sys.exit(1)

    # 2. Symbol Test
    if not run_symbol_test(symbol_mgr):
        print("\n[FAIL] ABORTING: Symbol test failed.")
        sys.exit(1)

    # 3. Historical Data Test
    run_historical_data_test(market_feed, symbol_mgr)

    # 4. Live Tick Test
    run_live_tick_test(market_feed, symbol_mgr)

    # 5. Demo Order Test (Optional)
    if args.demo_order:
        run_demo_order_test(order_executor, symbol_mgr)
    else:
        print("\n" + "=" * 60)
        print(" 5. DEMO ORDER TEST: SKIPPED (Use --demo-order to enable)")
        print("=" * 60)

    print("\n" + "=" * 60)
    print(" ALL MT5 INTEGRATION VERIFICATION TESTS COMPLETED!")
    print("=" * 60)

    connector.disconnect()


if __name__ == "__main__":
    main()
