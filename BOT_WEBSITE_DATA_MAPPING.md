# PKG Traders — Bot-to-Website Data Field Mapping

**Document Version**: 1.0.0  
**Target Architecture**: Client Portal & Admin Portal Read-Only Presentation Layer  

---

## 1. Data Mapping Matrix

| Data Item | Required By | Trading Bot Internal Symbol / Source | Central Backend Database Field | Website UI Element |
| :--- | :--- | :--- | :--- | :--- |
| `client_id` | Client & Admin | N/A (Web Entity) | `users.id` | User Profile / Tenant Identity |
| `client_name` | Client & Admin | N/A (Web Entity) | `users.firstName`, `users.lastName` | Portal Navigation Bar |
| `account_id` | Client & Admin | `AccountConfig.account_id` | `trading_accounts.id` | Account Selector Dropdown |
| `mt5_login` | Client & Admin | `AccountConfig.login` | `trading_accounts.mt5Login` | Mapped Trading Account List |
| `broker` | Client & Admin | `AccountConfig.server` | `brokers.name`, `brokers.serverName` | Account Profile Details |
| `account_balance` | Client & Admin | `MT5DirectSession.get_account_info()["balance"]` | `trading_accounts.balance` | Balance Dashboard Card |
| `equity` | Client & Admin | `MT5DirectSession.get_account_info()["equity"]` | `trading_accounts.equity` | Net Equity Dashboard Card |
| `free_margin` | Client | `MT5DirectSession.get_account_info()["free_margin"]` | `trading_accounts.freeMargin` | Wallet & Margin Overview |
| `margin` | Client | `MT5DirectSession.get_account_info()["margin"]` | `trading_accounts.margin` | Account Risk Summary |
| `margin_level` | Client | `MT5DirectSession.get_account_info()["margin_level"]` | `trading_accounts.marginLevel` | Risk Indicator |
| `floating_pnl` | Client & Admin | `sum(PositionSnapshot.profit)` | Calculated (`equity - balance`) | Live Floating P&L Card |
| `realized_pnl` | Client & Admin | `mt5.history_deals_get().profit` | `trades.realizedPnL` | Closed Trade Journal Table |
| `open_positions` | Client & Admin | `MT5DirectSession.get_positions()` | `open_positions` | Active Positions Grid |
| `executed_trades` | Client & Admin | `MT5DirectSession.get_account_history()` | `trades` | Historical Execution Table |
| `trade_ticket` | Client & Admin | `deal.ticket` / `position.ticket` | `trades.dealTicket`, `open_positions.positionTicket` | Order Details |
| `symbol` | Client & Admin | `deal.symbol` / `position.symbol` | `trades.symbol` | Trade Row Symbol Badge |
| `buy_sell` | Client & Admin | `0` = BUY, `1` = SELL | `trades.direction` | Order Direction Tag |
| `lot_size` | Client & Admin | `deal.volume` | `trades.volume` | Volume Column |
| `entry_price` | Client & Admin | `deal.price` | `trades.entryPrice` | Price Column |
| `stop_loss` | Client & Admin | `position.sl` | `open_positions.stopLoss` | SL Column |
| `take_profit` | Client & Admin | `position.tp` | `open_positions.takeProfit` | TP Column |
| `commission` | Client & Admin | `deal.commission` | `trades.commission` | Transaction Charges |
| `swap` | Client & Admin | `deal.swap` | `trades.swap` | Rollover Cost |
| `bot_status` | Admin | `TerminalSupervisor.get_status()` | `bot_instances.status` | System Health Monitoring |
| `last_telemetry` | Admin | System clock on push | `trading_accounts.lastSyncAt` | Sync Status Badge |
| `deposits` | Client & Admin | N/A (Web Financial Entity) | `deposits` | Deposit Requests Table |
| `withdrawals` | Client & Admin | N/A (Web Financial Entity) | `withdrawals` | Withdrawal Requests Queue |

---

## 2. Client-to-Trading Account Mapping Relationship

```
Client (User ID: usr-client-001)
├── Mapped Account 1 -> Internal ID: ta-001 | MT5 Login: #26128885 | Server: VantageMarkets-Demo
└── Mapped Account 3 -> Internal ID: ta-003 | MT5 Login: #26179878 | Server: VantageMarkets-Demo
```

- **Database Table**: `account_user_mappings` (`userId`, `tradingAccountId`).
- **Tenant Guard**: Client API endpoints strictly filter database queries by checking authorization JWT against `account_user_mappings`. Raw MT5 logins are never accepted as raw query parameters.
