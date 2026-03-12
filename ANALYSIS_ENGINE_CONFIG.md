# Analysis Engine Configuration

## Overview

The trading bot's Strategy Optimizer now includes a **configurable Analysis Engine**. You can choose how your trade data is analyzed and customize the thresholds for generating recommendations.

## Accessing the Settings

1. Open Dashboard → Click **"Configuration"** in sidebar
2. Scroll down to **"Analysis Engine Configuration"** section
3. Configure your preferred analysis method

## Analysis Engine Types

### 1. Local Rule-Based (Default) - FREE
**No API key required**

Uses built-in algorithms to analyze:
- Time-based performance (best/worst trading hours)
- Risk/Reward ratio effectiveness
- ATR multiplier performance
- Position sizing optimization
- Paper vs Live execution gaps

**Best for:** Most users who want immediate insights without external dependencies

### 2. OpenAI GPT (Optional) - PAID
**Requires OpenAI API key**

Uses GPT models for:
- Natural language trade summaries
- Advanced pattern recognition
- Contextual market analysis
- Detailed strategy recommendations

**Cost:** Depends on usage (~$0.01-0.10 per analysis)

### 3. Claude by Anthropic (Optional) - PAID
**Requires Claude API key**

Uses Claude models for:
- In-depth strategy analysis
- Long-form recommendation reports
- Complex pattern detection
- Detailed risk assessments

**Cost:** Depends on usage (~$0.01-0.15 per analysis)

---

## Configuration Options

### Enable/Disable Analysis
```
[✓] Enable Analysis
```
Turn off to disable all analysis and recommendations. Useful when you want to trade without suggestions.

### Engine Selection
```
Analysis Engine: [Local Rule-Based ▼]
                 [OpenAI GPT]
                 [Claude (Anthropic)]
```

### API Key Configuration
When using OpenAI or Claude:
- Enter your API key in the secure input field
- Keys are masked (shown as ***) after saving
- Keys are stored in `config.json` on your server only

---

## Threshold Configuration

### Min Trades for Recommendation
**Default: 5 trades**

How many trades are needed before the system generates recommendations.

| Setting | Effect |
|---------|--------|
| 3 | More aggressive suggestions (faster but less reliable) |
| 5 | Balanced approach (recommended) |
| 10 | Conservative (wait for more data, more reliable) |
| 20 | Very conservative ( institutional-level analysis) |

**Example:** If you set this to 3, the system will suggest time windows after only 3 trades in that hour.

### Execution Gap Threshold
**Default: 20%**

The percentage difference between paper and live win rates that triggers an "execution gap" warning.

| Setting | Effect |
|---------|--------|
| 10% | Very sensitive (alerts on small discrepancies) |
| 20% | Balanced (recommended) |
| 30% | Tolerant (only major gaps) |
| 50% | Very tolerant (rare alerts) |

**Example:** If paper shows 70% WR and live shows 48% WR (22% gap), with threshold at 20%, you'll get an alert.

### Min Win Rate for "Good"
**Default: 60%**

What win rate is considered "good performance" for recommendations.

| Setting | Classification |
|---------|---------------|
| 50% | More symbols marked as good |
| 60% | Standard (recommended) |
| 70% | Strict (only consistently profitable) |
| 80% | Very strict (institutional-grade) |

---

## Metrics to Analyze

Toggle which aspects of your trading to analyze:

```
[✓] Time Performance        → Best/worst trading hours
[✓] Risk/Reward Ratios      → Optimal R:R settings  
[✓] ATR Multipliers         → Stop loss optimization
[✓] Position Sizing         → Risk percentage tuning
[✓] Execution Gaps          → Paper vs Live comparison
```

**Tip:** Disable metrics you're not interested in to speed up analysis.

---

## How Analysis Works

### Local Rule-Based Engine

```
1. Collect trade data (entry, exit, P&L, time, etc.)
2. Group by metric (time, R:R, ATR, etc.)
3. Calculate statistics (win rate, avg P&L)
4. Compare against thresholds
5. Generate recommendations if criteria met
```

**No external API calls** - everything happens on your server.

### External AI Engines (OpenAI/Claude)

When configured and enough data exists:

```
1. Compile trade statistics
2. Send structured data to AI API
3. Receive natural language analysis
4. Display insights with context
```

**Note:** External AI is only used if:
- Engine type is set to "openai" or "claude"
- API key is configured
- Sufficient trade data exists (20+ trades recommended)

---

## Example Workflows

### For Beginners
```
Engine: Local Rule-Based
Min Trades: 5
Thresholds: Default (20%, 60%)
Metrics: All enabled
```
**Result:** Balanced suggestions based on solid data

### For Experienced Traders
```
Engine: Local Rule-Based
Min Trades: 10
Thresholds: 15% gap, 65% good
Metrics: Time + Execution Gaps only
```
**Result:** Conservative, focused on execution quality

### For AI-Powered Analysis
```
Engine: OpenAI GPT
API Key: sk-...
Min Trades: 20
Metrics: All enabled
```
**Result:** Detailed natural language insights and recommendations

---

## Cost Comparison

| Engine | Cost | Speed | Depth |
|--------|------|-------|-------|
| Local | FREE | Instant | Statistical |
| OpenAI | ~$0.05/analysis | 1-3 sec | Natural language |
| Claude | ~$0.08/analysis | 2-5 sec | Detailed reports |

**Recommendation:** Start with Local. Upgrade to AI only when you need deeper insights.

---

## API Endpoints

### Get Current Config
```bash
GET /api/config
```

### Update Analysis Config
```bash
POST /api/config
{
  "analysis_engine": {
    "enabled": true,
    "engine_type": "local",
    "thresholds": {
      "min_trades_for_recommendation": 5,
      "execution_gap_threshold": 20,
      "min_win_rate_for_best": 60
    },
    "metrics": {
      "analyze_time_performance": true,
      "analyze_risk_reward": true,
      "analyze_atr_multipliers": true,
      "analyze_position_sizing": true,
      "analyze_execution_gaps": true
    }
  }
}
```

### Run Analysis
```bash
GET /api/strategy/analytics
```

---

## Troubleshooting

### "No recommendations yet"
- Check if analysis is enabled
- Verify you have enough trades (see Min Trades setting)
- Check if metrics are enabled for your trade types

### "Analysis is disabled"
- Go to Settings → Analysis Engine Configuration
- Check "Enable Analysis" toggle
- Save settings

### "API key invalid" (for OpenAI/Claude)
- Verify your API key is correct
- Check if you have credits in your OpenAI/Anthropic account
- Ensure API key has proper permissions

### Too many/few recommendations
- Adjust "Min Trades for Recommendation"
- Change "Execution Gap Threshold"
- Toggle specific metrics on/off

---

## Data Privacy

**Local Analysis:**
- ✅ All data stays on your server
- ✅ No external API calls
- ✅ Complete privacy

**External AI Analysis:**
- ⚠️ Trade statistics sent to OpenAI/Anthropic
- ⚠️ Data is anonymized (no personal info)
- ⚠️ Review their privacy policies

**Recommendation:** Use Local for privacy, External AI for advanced features.

---

## Future: Custom Analysis Scripts

Coming soon: Upload custom Python scripts for analysis:

```python
# custom_analyzer.py
def analyze(trades):
    # Your custom logic
    return {
        "recommendations": [...],
        "insights": {...}
    }
```

This will allow complete customization of how your trades are analyzed.
