# Trading Learning System

## Overview

The trading bot now includes a comprehensive **Learning System** that tracks and analyzes every trade to help you improve your trading performance. This system:

1. **Auto Paper Trades** - Every signal is automatically paper traded for learning
2. **Tracks Performance** - Records win rates and P&L by symbol (paper vs live)
3. **Provides Insights** - Generates recommendations based on historical data
4. **Preserves Data** - Daily reset archives data without destroying historical insights

## How It Works

### Auto Paper Trading

Every stock signal that hits the system is now **automatically paper traded**, regardless of your live trading mode:

```
Signal Received → Paper Trade Executed (always)
                ↓
         Live Trading ON? → Live Trade Also Executed
```

This ensures you have a complete paper trading record for every signal to compare against live performance.

### Trade Insights

The system tracks per-symbol statistics:

```json
{
  "RELIANCE": {
    "paper": {
      "trades": 10,
      "wins": 7,
      "losses": 3,
      "win_rate": 70.0,
      "total_pnl": 12500.50
    },
    "live": {
      "trades": 5,
      "wins": 2,
      "losses": 3,
      "win_rate": 40.0,
      "total_pnl": -2500.00
    }
  }
}
```

### Learning Recommendations

The system automatically generates recommendations:

1. **Execution Gap** ⚠️
   - Paper win rate > 60% but Live win rate < 40%
   - Suggests checking execution slippage or timing

2. **Strong Performer** 🌟
   - Paper win rate > 65% with 5+ trades
   - Consider taking this symbol live

3. **Avoid** 🚫
   - Paper win rate < 35% with 5+ trades
   - Consider avoiding this symbol

## Dashboard - Learning Tab

### Accessing Learning Data

1. Open the Dashboard
2. Click **"Learning"** in the left sidebar
3. View three sections:
   - **Trade Insights** - Per-symbol performance
   - **Recommendations** - AI-generated suggestions
   - **Daily Performance** - Last 7 days history

### Reading the Data

**Trade Insights Card:**
```
┌─────────────────────────────┐
│ RELIANCE          12/03/24  │
├─────────────────────────────┤
│ Paper Trades    Live Trades │
│ 10              5           │
│ 70% WR          40% WR      │
│                             │
│ Paper P&L: ₹12,500.50      │
└─────────────────────────────┘
```

## Daily Reset

### Purpose

The **Daily Reset** button prepares your dashboard for the next trading day:

- ✅ Archives open positions to insights
- ✅ Clears today's trade log
- ✅ Preserves ALL historical data
- ✅ Updates daily statistics

### When to Use

Use at the **end of each trading day** (after market close):

1. Review your day's performance
2. Click **"Reset for Next Trading Day"**
3. System archives all data
4. Dashboard is fresh for tomorrow

### What Gets Reset

| Data | Action |
|------|--------|
| Open Positions | Closed & Archived |
| Today's Trades | Cleared (in trades_log.json) |
| Trade Insights | **Preserved** |
| Daily Stats | **Preserved** |
| Config Settings | **Preserved** |
| Symbol History | **Preserved** |

## API Endpoints

### Get Insights
```bash
GET /api/insights
```

Response:
```json
{
  "status": "success",
  "symbols": { /* per-symbol stats */ },
  "daily_stats": { /* daily history */ },
  "recommendations": [ /* AI suggestions */ ],
  "last_updated": "2026-03-12T23:46:23"
}
```

### Get Symbol Insights
```bash
GET /api/insights/{symbol}
```

### Daily Reset
```bash
POST /api/reset-daily
```

Response:
```json
{
  "status": "reset",
  "message": "Day reset complete. Archived 15 positions.",
  "details": {
    "closed_positions": 15,
    "trades_cleared": 25,
    "trades_preserved": 12,
    "today_paper_pnl": 0,
    "today_live_pnl": 159.35,
    "insights_preserved": true
  }
}
```

## Data Storage

### Files Used

| File | Purpose |
|------|---------|
| `trade_insights.json` | Symbol stats, daily stats, recommendations |
| `trades_log.json` | All trade records (cleared daily) |
| `positions.json` | Open positions (cleared daily) |

### Insight Data Structure

```json
{
  "symbols": {
    "RELIANCE": {
      "paper": { "trades": 10, "wins": 7, "losses": 3, ... },
      "live": { "trades": 5, "wins": 2, "losses": 3, ... },
      "first_seen": "2026-03-01T09:30:00",
      "last_trade": { "date": "2026-03-12T14:30:00", "pnl": 1250.50 }
    }
  },
  "daily_stats": {
    "2026-03-12": {
      "trades": 25,
      "paper_pnl": 5000.00,
      "live_pnl": 159.35,
      "reset_time": "2026-03-12T23:46:23"
    }
  }
}
```

## Using Insights to Improve

### Weekly Review Process

1. **Check Recommendations** - Look for execution gaps
2. **Compare Paper vs Live** - Identify slippage issues
3. **Review Strong Performers** - Consider for live trading
4. **Note Symbols to Avoid** - Update your watchlist

### Example Analysis

```
Symbol: TCS
Paper: 70% win rate (7/10 trades)
Live:  40% win rate (2/5 trades)

→ Execution gap detected!
→ Check: Entry timing, slippage, order type
```

### Continuous Improvement

1. **Track Paper Performance** - Validate your strategy
2. **Compare with Live** - Find execution improvements
3. **Follow Recommendations** - Let data guide decisions
4. **Daily Reset** - Keep dashboard organized

## Tips

1. **Always Paper Trade First** - Every signal gets paper traded automatically
2. **Review Weekly** - Check Learning tab every weekend
3. **Heed Warnings** - Execution gaps indicate real issues
4. **Archive Daily** - Reset at end of trading day
5. **Preserve History** - Insights help long-term improvement

---

**Remember:** The learning system is only as good as the data you feed it. Keep trading (paper and live) to build a comprehensive performance database!
