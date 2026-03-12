# Strategy Optimization System

## Overview

The trading bot now includes a powerful **Strategy Optimization System** that analyzes your long-term trading performance and provides actionable recommendations to improve your strategy. Based on data-driven insights, you can edit and refine your trading approach directly from the dashboard.

## Key Features

### 1. AI-Powered Analytics
The system analyzes your trade history across multiple dimensions:

- **Time Performance** - Which hours of the day are most/least profitable
- **Risk/Reward Analysis** - Which R:R ratios work best for you
- **ATR Multipliers** - Optimal stop loss distances
- **Position Sizing** - Best risk percentage per trade

### 2. Automatic Recommendations
Based on analysis, the system generates prioritized suggestions:

| Priority | Type | Example |
|----------|------|---------|
| 🔴 High | Execution Gap | Paper 70% WR vs Live 40% WR - Check slippage |
| 🟡 Medium | Time Window | 10:00 AM shows best performance |
| 🔵 Low | Risk Adjustment | Consider 1.5% risk instead of 1% |

### 3. Strategy Editor
Manually adjust your strategy parameters:

- **Risk per Trade** (0.1% - 3%)
- **Minimum R:R** (1:1.5 to 1:3)
- **ATR Multipliers** for SL/TP
- **Trading Hours**

### 4. One-Click Apply
Apply AI recommendations with a single click, or manually configure custom settings.

### 5. Change History
Track all strategy modifications over time to see what works.

---

## How It Works

### Data Collection
Every trade is analyzed and stored:
```
Trade Executed → Insights Updated → Analytics Recalculated
```

### Analysis Engine
The `StrategyOptimizer` class performs deep analysis:

```python
# Time-based analysis
hourly_stats = {
    "10:00": {"trades": 15, "win_rate": 73%, "avg_pnl": 1250},
    "14:00": {"trades": 8, "win_rate": 25%, "avg_pnl": -500}
}

# Risk/Reward analysis
rr_performance = {
    "1:2_to_1:3": {"win_rate": 65%, "avg_pnl": 800},
    "1:3_plus": {"win_rate": 45%, "avg_pnl": 1200}
}
```

### Recommendation Generation
```python
if best_hour and best_hour['avg_pnl'] > 1000:
    suggest_focus_on_hour(best_hour)

if paper_wr > live_wr + 20:
    alert_execution_gap(symbol)
```

---

## Dashboard - Strategy Optimizer

### Accessing the Optimizer

1. Open Dashboard → Click **"Learning"** in sidebar
2. The **Strategy Optimizer** section appears at top
3. Click **"Analyze Strategy"** to generate insights

### Understanding the Analytics

**Summary Cards:**
```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  47         │ │   10:00     │ │  1:2-1:3    │ │    1%       │
│ Trades      │ │ Best Hour   │ │ Optimal R:R │ │ Optimal Risk│
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

**AI Recommendations:**
```
┌─────────────────────────────────────────────────────────────┐
│ 🔴 Best Trading Hour: 10:00 AM                              │
│ 10:00 shows 73% win rate with ₹1,250 avg P&L. Consider      │
│ focusing trades during this hour.                           │
│                                              [Apply]        │
├─────────────────────────────────────────────────────────────┤
│ 🟡 Stop Loss Optimization                                   │
│ Use tighter stops (1x ATR) - quick cuts, small losses       │
│                                              [Apply]        │
└─────────────────────────────────────────────────────────────┘
```

**Strategy Editor:**
```
┌─────────────────────────────────────────────────────────────┐
│ Strategy Editor                                             │
├───────────────────────┬─────────────────────────────────────┤
│ Risk Management       │ ATR Multipliers                     │
│ • Risk Per Trade:     │ • Stop Loss: 1.5x ATR (Default)     │
│   [====●====] 1.0%    │ • Take Profit: 3.0x ATR (Default)   │
│ • Min R:R: 1:2        │                                     │
├───────────────────────┴─────────────────────────────────────┤
│ Strategy Preview:                                           │
│ • Risk per trade: 1% of capital                             │
│ • Minimum R:R: 1:2                                          │
│ • Stop Loss: 1.5x ATR                                       │
│ • Take Profit: 3.0x ATR                                     │
│                                                             │
│         [Apply Strategy Changes]                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Types of Recommendations

### 1. Time Window Optimization
**When:** You have 3+ trades in specific hours with clear patterns

**Example:**
```
10:00 AM: 73% win rate, ₹1,250 avg P&L
11:00 AM: 25% win rate, -₹500 avg P&L

→ Recommendation: Focus on 10:00-11:00 window
```

### 2. Execution Gap Detection
**When:** Paper trading significantly outperforms live trading

**Example:**
```
RELIANCE Paper: 70% WR, ₹800 avg P&L
RELIANCE Live:  40% WR, ₹200 avg P&L

→ Recommendation: Check slippage and entry timing
→ Suggested: Tighter slippage tolerance (0.3%)
```

### 3. Risk/Reward Optimization
**When:** Certain R:R ratios consistently perform better

**Example:**
```
1:2 R:R: 45% WR, ₹600 avg P&L
1:3 R:R: 65% WR, ₹900 avg P&L

→ Recommendation: Target 1:3 R:R minimum
```

### 4. Position Size Adjustment
**When:** Current risk % isn't optimal

**Example:**
```
1% risk: Break-even over 20 trades
1.5% risk: +₹5,000 over 20 trades

→ Recommendation: Increase to 1.5% risk
```

### 5. ATR Multiplier Tuning
**When:** SL distance impacts performance

**Example:**
```
1.0x ATR (tight):  60% WR, small losses
1.5x ATR (medium): 45% WR, larger losses

→ Recommendation: Use tighter 1x ATR stops
```

---

## API Endpoints

### Get Strategy Analytics
```bash
GET /api/strategy/analytics
```

Response:
```json
{
  "status": "success",
  "time_performance": { "hourly_breakdown": {...}, "best_hour": [...] },
  "risk_reward_analysis": { "buckets": {...}, "best_rr_range": "1:2_to_1:3" },
  "atr_analysis": { "buckets": {...}, "best_sl_setting": "tight_1x" },
  "position_sizing_analysis": { "optimal_risk_range": "medium_0_5_1" },
  "recommendations": [...]
}
```

### Apply Recommendation
```bash
POST /api/strategy/apply?recommendation_idx=0
```

### Apply Custom Strategy
```bash
POST /api/strategy/custom
{
  "risk_percent": 1.5,
  "min_risk_reward": 2.5,
  "atr_multiplier_sl": 1.0,
  "atr_multiplier_tp": 3.0
}
```

### Get Strategy History
```bash
GET /api/strategy/history
```

### Reset to Defaults
```bash
POST /api/strategy/reset
```

---

## Best Practices

### Weekly Strategy Review
1. **Monday Morning:** Check weekend analytics
2. **Review Recommendations:** Note any high-priority items
3. **Apply Selectively:** Don't apply all recommendations at once
4. **Track Changes:** Monitor performance after each change
5. **Iterate:** Strategy optimization is continuous

### When to Make Changes

| Signal | Action |
|--------|--------|
| Consistent losing hour | Avoid that time window |
| Execution gap > 20% | Check broker/settings |
| R:R analysis clear | Adjust min R:R requirement |
| 10+ trades in bucket | Trust the statistics |

### What NOT to Do

❌ **Don't over-optimize** - Need minimum 5-10 trades per bucket  
❌ **Don't change everything at once** - Change one parameter, observe  
❌ **Don't ignore context** - Market conditions change  
❌ **Don't optimize for paper only** - Live performance matters most  

---

## Example Workflow

### Week 1: Data Collection
- Trade normally (both paper and live)
- Let system collect data

### Week 2: First Analysis
```
Analytics Shows:
- Best hour: 10:00 AM
- Worst hour: 2:00 PM
- Paper/Live gap in TCS
```

### Week 3: Apply Changes
1. Apply "Focus on 10:00 AM" recommendation
2. Manually avoid 2:00 PM trades
3. Check TCS execution settings

### Week 4: Measure Results
```
Compare Week 1 vs Week 3:
- Win rate improved?
- P&L improved?
- Execution gap reduced?
```

### Iterate
Continue this cycle, refining strategy based on data.

---

## Configuration Storage

Strategy settings are stored in `config.json`:

```json
{
  "risk_percent": 1.0,
  "risk_management": {
    "atr_multiplier_sl": 1.5,
    "atr_multiplier_tp": 3.0,
    "min_risk_reward": 2.0
  },
  "strategy_history": [
    {
      "date": "2026-03-12T10:00:00",
      "reason": "Best Trading Hour: 10:00 AM",
      "type": "time_window",
      "new_values": {"trading_hours": {"start": "10:00", "end": "11:00"}}
    }
  ]
}
```

---

## Need Help?

The Strategy Optimizer learns from YOUR trading data. The more you trade, the better the recommendations become. Start trading and let the AI help you improve!

📊 **Remember:** Past performance doesn't guarantee future results, but data-driven decisions beat guessing every time.
