"""
Enhanced Learning & Insights System
====================================

Provides intelligent, actionable insights based on:
1. Signal Quality Analysis - Grade signals BEFORE they execute
2. Execution Gap Detection - Paper vs Live performance comparison  
3. Time-Based Patterns - Which hours/days work best
4. Market Condition Analysis - Trend alignment, volatility impact
5. Symbol Performance Tracking - Per-symbol win rates and patterns
6. Risk Management Insights - Optimal position sizing, SL/TP analysis
"""

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

# Files
TRADES_FILE = Path("trades_log.json")
INSIGHTS_FILE = Path("trade_insights.json")
POSITIONS_FILE = Path("positions.json")
TURBO_QUEUE_FILE = Path("turbo_queue.json")
SIGNALS_LOG_FILE = Path("signals_log.json")
INCOMING_ALERTS_FILE = Path("incoming_alerts.json")


@dataclass
class SignalGrade:
    """Grade for a trading signal based on multiple factors"""
    score: int  # 0-100
    grade: str  # A+, A, B, C, D, F
    factors: Dict[str, Any]
    recommendation: str


@dataclass
class TimePattern:
    """Performance pattern for a specific time period"""
    period: str
    trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    trend: str  # "improving", "declining", "stable"


@dataclass
class SymbolInsight:
    """Comprehensive insight for a symbol"""
    symbol: str
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    best_time: str
    worst_time: str
    trend_alignment_rate: float
    execution_quality: float
    grade: str
    recommendation: str


class EnhancedLearningEngine:
    """
    Intelligent learning engine that analyzes trading patterns
    and provides actionable insights.
    """
    
    def __init__(self):
        self.trades = self._load_trades()
        self.signals = self._load_signals()
        self.turbo_signals = self._load_turbo_signals()
        self.insights = self._load_existing_insights()
        
    def _load_trades(self) -> List[Dict]:
        """Load all trades from trades log (includes both paper and live)"""
        if not TRADES_FILE.exists():
            return []
        try:
            with open(TRADES_FILE, 'r') as f:
                trades = json.load(f)
            
            # Mark paper trades based on order_id pattern
            # PAPER_* = Paper trades
            # ANALYSIS_* = Analysis-only trades (treat as paper)
            # Numeric = Live trades from Kite
            for trade in trades:
                order_id = str(trade.get('order_id', ''))
                is_paper = (order_id.startswith('PAPER_') or 
                           order_id.startswith('ANALYSIS_'))
                trade['is_paper'] = is_paper
                trade['paper_trading'] = is_paper  # For compatibility
            
            return trades
        except:
            return []
    
    def _load_signals(self) -> List[Dict]:
        """Load all signals from signals log"""
        if not SIGNALS_LOG_FILE.exists():
            return []
        try:
            with open(SIGNALS_LOG_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _load_turbo_signals(self) -> List[Dict]:
        """Load turbo queue signals"""
        if not TURBO_QUEUE_FILE.exists():
            return []
        try:
            with open(TURBO_QUEUE_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _load_existing_insights(self) -> Dict:
        """Load existing insights if available"""
        if not INSIGHTS_FILE.exists():
            return {"symbols": {}, "daily_stats": {}}
        try:
            with open(INSIGHTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"symbols": {}, "daily_stats": {}}
    
    def analyze_signal_quality(self) -> Dict[str, Any]:
        """
        Analyze signal quality based on:
        - Trend alignment success rate
        - Entry timing accuracy
        - Signal-to-execution conversion
        """
        total_signals = len(self.signals)
        if total_signals == 0:
            return {"status": "no_data", "message": "No signals to analyze"}
        
        # Analyze turbo signals for trend alignment
        turbo_signals = self.turbo_signals
        trend_aligned = len([s for s in turbo_signals if 
                            s.get('trend_check', {}).get('aligned') == True])
        trend_mismatch = len([s for s in turbo_signals if 
                             s.get('status') == 'TREND_MISMATCH'])
        
        # Analyze by status
        status_counts = defaultdict(int)
        for signal in self.signals:
            status_counts[signal.get('status', 'UNKNOWN')] += 1
        
        # Calculate signal quality metrics
        executed = status_counts.get('EXECUTED', 0)
        rejected = status_counts.get('REJECTED', 0)
        failed = status_counts.get('FAILED', 0)
        
        total_processed = executed + rejected + failed
        if total_processed == 0:
            conversion_rate = 0
        else:
            conversion_rate = (executed / total_processed) * 100
        
        # Signal quality grade
        if conversion_rate >= 70:
            grade = "A"
        elif conversion_rate >= 50:
            grade = "B"
        elif conversion_rate >= 30:
            grade = "C"
        else:
            grade = "D"
        
        return {
            "total_signals": total_signals,
            "conversion_rate": round(conversion_rate, 1),
            "grade": grade,
            "status_breakdown": dict(status_counts),
            "trend_analysis": {
                "total_turbo": len(turbo_signals),
                "trend_aligned": trend_aligned,
                "trend_mismatch": trend_mismatch,
                "alignment_rate": round((trend_aligned / len(turbo_signals) * 100), 1) if turbo_signals else 0
            },
            "insights": self._generate_signal_insights(conversion_rate, trend_aligned, trend_mismatch)
        }
    
    def _generate_signal_insights(self, conversion_rate: float, trend_aligned: int, trend_mismatch: int) -> List[str]:
        """Generate actionable insights about signal quality"""
        insights = []
        
        if conversion_rate < 40:
            insights.append("⚠️ Low conversion rate. Many signals are being rejected or failing. Check entry filters.")
        elif conversion_rate > 70:
            insights.append("✅ Good conversion rate! Your signals are being executed consistently.")
        
        total_turbo = trend_aligned + trend_mismatch
        if total_turbo > 0:
            alignment_rate = (trend_aligned / total_turbo) * 100
            if alignment_rate < 30:
                insights.append(f"📉 Only {alignment_rate:.0f}% of signals align with trend. Consider trading with stronger trends.")
            elif alignment_rate > 60:
                insights.append(f"📈 {alignment_rate:.0f}% trend alignment is excellent!")
        
        return insights
    
    def analyze_time_patterns(self) -> Dict[str, Any]:
        """
        Analyze performance by time of day, day of week
        """
        if not self.trades:
            return {"status": "no_data"}
        
        # Group by hour
        hourly_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for trade in self.trades:
            try:
                date_str = trade.get('date', '')
                if not date_str:
                    continue
                
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                hour = dt.hour
                
                hourly_stats[hour]["trades"] += 1
                pnl = trade.get('pnl', 0)
                hourly_stats[hour]["pnl"] += pnl
                if pnl > 0:
                    hourly_stats[hour]["wins"] += 1
            except:
                continue
        
        # Calculate win rates and find best/worst hours
        hour_performance = []
        for hour, stats in hourly_stats.items():
            if stats["trades"] >= 2:  # Need at least 2 trades for significance
                win_rate = (stats["wins"] / stats["trades"]) * 100
                hour_performance.append({
                    "hour": f"{hour:02d}:00",
                    "hour_num": hour,
                    "trades": stats["trades"],
                    "win_rate": round(win_rate, 1),
                    "total_pnl": round(stats["pnl"], 2),
                    "avg_pnl": round(stats["pnl"] / stats["trades"], 2)
                })
        
        # Sort by win rate
        hour_performance.sort(key=lambda x: x["win_rate"], reverse=True)
        
        best_hours = [h for h in hour_performance if h["win_rate"] >= 50]
        worst_hours = [h for h in hour_performance if h["win_rate"] < 40]
        
        return {
            "total_hours_traded": len(hourly_stats),
            "hourly_breakdown": hour_performance[:10],  # Top 10
            "best_hours": best_hours[:3],
            "worst_hours": worst_hours[:3],
            "recommendations": self._generate_time_recommendations(best_hours, worst_hours)
        }
    
    def _generate_time_recommendations(self, best_hours: List[Dict], worst_hours: List[Dict]) -> List[str]:
        """Generate time-based recommendations"""
        recs = []
        
        if best_hours:
            best = best_hours[0]
            recs.append(f"🕐 Best time: {best['hour']} ({best['win_rate']:.0f}% win rate, ₹{best['total_pnl']:.0f} P&L)")
        
        if worst_hours:
            worst = worst_hours[0]
            recs.append(f"⚠️ Avoid: {worst['hour']} ({worst['win_rate']:.0f}% win rate, ₹{worst['total_pnl']:.0f} P&L)")
        
        if len(best_hours) >= 2:
            recs.append(f"✅ You have {len(best_hours)} profitable trading hours. Focus on these windows.")
        
        return recs
    
    def _analyze_symbol_stats(self, trades: List[Dict]) -> Dict[str, Any]:
        """Helper to calculate stats for a list of trades"""
        if not trades:
            return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0, "win_rate": 0}
        
        total = len(trades)
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        pnl = sum(t.get('pnl', 0) for t in trades)
        
        return {
            "trades": total,
            "wins": wins,
            "losses": total - wins,
            "pnl": round(pnl, 2),
            "win_rate": round((wins / total) * 100, 1) if total > 0 else 0
        }
    
    def analyze_symbol_performance(self) -> Dict[str, Any]:
        """
        Comprehensive per-symbol analysis with PAPER vs LIVE breakdown
        """
        # Group trades by symbol and type (paper/live)
        symbol_paper = defaultdict(list)
        symbol_live = defaultdict(list)
        
        for trade in self.trades:
            symbol = trade.get('symbol', '')
            if not symbol:
                continue
            
            is_paper = trade.get('is_paper', False) or trade.get('paper_trading', False)
            
            if is_paper:
                symbol_paper[symbol].append(trade)
            else:
                symbol_live[symbol].append(trade)
        
        # Get all unique symbols
        all_symbols = set(symbol_paper.keys()) | set(symbol_live.keys())
        
        # Calculate metrics for each symbol
        symbol_insights = []
        for symbol in all_symbols:
            paper_trades = symbol_paper.get(symbol, [])
            live_trades = symbol_live.get(symbol, [])
            
            paper_stats = self._analyze_symbol_stats(paper_trades)
            live_stats = self._analyze_symbol_stats(live_trades)
            
            # Combined stats
            combined_trades = paper_trades + live_trades
            combined_stats = self._analyze_symbol_stats(combined_trades)
            
            # Calculate profit factor for combined
            total_profit = sum(t.get('pnl', 0) for t in combined_trades if t.get('pnl', 0) > 0)
            total_loss = sum(abs(t.get('pnl', 0)) for t in combined_trades if t.get('pnl', 0) < 0)
            profit_factor = total_profit / total_loss if total_loss > 0 else 999.99
            
            # Execution gap analysis
            execution_gap = None
            if paper_stats["trades"] >= 2 and live_stats["trades"] >= 2:
                gap = paper_stats["win_rate"] - live_stats["win_rate"]
                execution_gap = round(gap, 1)
            
            # Grade based on combined performance
            win_rate = combined_stats["win_rate"]
            if win_rate >= 60 and profit_factor >= 2:
                grade = "A+"
            elif win_rate >= 55 and profit_factor >= 1.5:
                grade = "A"
            elif win_rate >= 50 and profit_factor >= 1.2:
                grade = "B"
            elif win_rate >= 40:
                grade = "C"
            else:
                grade = "D"
            
            # Smart recommendation
            if execution_gap and execution_gap > 20:
                rec = f"⚠️ Execution gap: Paper {paper_stats['win_rate']:.0f}% vs Live {live_stats['win_rate']:.0f}% - Check slippage"
            elif grade in ["A+", "A"]:
                rec = "⭐ Excellent - Increase size"
            elif grade == "B":
                rec = "✅ Good - Continue normal sizing"
            elif win_rate < 35:
                rec = "🚫 Poor - Avoid this symbol"
            else:
                rec = "📊 Mixed - Monitor closely"
            
            symbol_insights.append({
                "symbol": symbol,
                "paper": paper_stats,
                "live": live_stats,
                "combined": {
                    **combined_stats,
                    "profit_factor": round(profit_factor, 2)
                },
                "execution_gap": execution_gap,
                "grade": grade,
                "recommendation": rec
            })
        
        # Sort by combined P&L
        symbol_insights.sort(key=lambda x: x["combined"]["pnl"], reverse=True)
        
        # Calculate totals
        total_paper_pnl = sum(s["paper"]["pnl"] for s in symbol_insights)
        total_live_pnl = sum(s["live"]["pnl"] for s in symbol_insights)
        total_paper_trades = sum(s["paper"]["trades"] for s in symbol_insights)
        total_live_trades = sum(s["live"]["trades"] for s in symbol_insights)
        
        return {
            "total_symbols": len(symbol_insights),
            "symbols": symbol_insights,
            "best_performers": [s for s in symbol_insights if s["grade"] in ["A+", "A"]],
            "worst_performers": [s for s in symbol_insights if s["grade"] == "D"],
            "execution_gaps": [s for s in symbol_insights if s.get("execution_gap") and s["execution_gap"] > 15],
            "summary": {
                "profitable_symbols": len([s for s in symbol_insights if s["combined"]["pnl"] > 0]),
                "losing_symbols": len([s for s in symbol_insights if s["combined"]["pnl"] < 0]),
                "total_paper_pnl": round(total_paper_pnl, 2),
                "total_live_pnl": round(total_live_pnl, 2),
                "total_paper_trades": total_paper_trades,
                "total_live_trades": total_live_trades,
                "combined_pnl": round(total_paper_pnl + total_live_pnl, 2)
            }
        }
    
    def analyze_execution_quality(self) -> Dict[str, Any]:
        """
        Analyze quality of trade execution
        - Entry slippage
        - Exit timing
        - Hold time analysis
        """
        if not self.trades:
            return {"status": "no_data"}
        
        # Group by entry price vs alert price
        slippage_data = []
        hold_times = []
        
        for trade in self.trades:
            entry = trade.get('entry_price', 0)
            alert = trade.get('alert_price', entry)  # Fallback to entry if no alert price
            
            if entry > 0 and alert > 0:
                slippage = ((entry - alert) / alert) * 100
                slippage_data.append({
                    "symbol": trade.get('symbol', ''),
                    "slippage_pct": slippage,
                    "entry": entry,
                    "alert": alert
                })
        
        if not slippage_data:
            return {"status": "insufficient_data", "message": "Need more trade data"}
        
        avg_slippage = statistics.mean([s["slippage_pct"] for s in slippage_data])
        
        # Categorize slippage
        good_slippage = len([s for s in slippage_data if abs(s["slippage_pct"]) < 0.3])
        bad_slippage = len([s for s in slippage_data if abs(s["slippage_pct"]) > 1.0])
        
        return {
            "total_trades_analyzed": len(slippage_data),
            "avg_slippage_pct": round(avg_slippage, 3),
            "good_entries": good_slippage,
            "bad_entries": bad_slippage,
            "execution_grade": "A" if abs(avg_slippage) < 0.3 else "B" if abs(avg_slippage) < 0.6 else "C",
            "details": slippage_data[:10],
            "insights": [
                f"Average entry slippage: {avg_slippage:.2f}%" + (" (Good)" if abs(avg_slippage) < 0.3 else " (High)"),
                f"{good_slippage}/{len(slippage_data)} trades with good entry (< 0.3% slippage)",
                "💡 Use limit orders if slippage is consistently high" if abs(avg_slippage) > 0.5 else "✅ Entry execution is good"
            ]
        }
    
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate complete learning report with all analyses"""
        return {
            "generated_at": datetime.now().isoformat(),
            "signal_quality": self.analyze_signal_quality(),
            "time_patterns": self.analyze_time_patterns(),
            "symbol_performance": self.analyze_symbol_performance(),
            "execution_quality": self.analyze_execution_quality(),
            "top_recommendations": self._generate_top_recommendations(),
            "action_items": self._generate_action_items()
        }
    
    def _generate_top_recommendations(self) -> List[Dict]:
        """Generate top 5 actionable recommendations"""
        recommendations = []
        
        # Analyze signal quality
        signal_analysis = self.analyze_signal_quality()
        if signal_analysis.get('conversion_rate', 0) < 40:
            recommendations.append({
                "priority": "HIGH",
                "category": "Signal Quality",
                "title": "Low Signal Conversion",
                "description": "Most signals are being rejected. Check your filters and validation rules.",
                "action": "Review entry criteria in config.json"
            })
        
        # Analyze time patterns
        time_analysis = self.analyze_time_patterns()
        best_hours = time_analysis.get('best_hours', [])
        if best_hours:
            best = best_hours[0]
            recommendations.append({
                "priority": "MEDIUM",
                "category": "Timing",
                "title": f"Best Trading Hour: {best['hour']}",
                "description": f"You have {best['win_rate']:.0f}% win rate during this hour.",
                "action": "Focus trading during this time window"
            })
        
        # Analyze symbols
        symbol_analysis = self.analyze_symbol_performance()
        best_symbols = symbol_analysis.get('best_performers', [])
        if best_symbols:
            best = best_symbols[0]
            recommendations.append({
                "priority": "HIGH",
                "category": "Symbol Selection",
                "title": f"Top Performer: {best['symbol']}",
                "description": f"{best['win_rate']:.0f}% win rate, ₹{best['total_pnl']:.0f} total profit",
                "action": "Consider increasing position size for this symbol"
            })
        
        worst_symbols = symbol_analysis.get('worst_performers', [])
        if worst_symbols:
            worst = worst_symbols[0]
            recommendations.append({
                "priority": "HIGH",
                "category": "Risk Management",
                "title": f"Avoid: {worst['symbol']}",
                "description": f"Poor performance with {worst['win_rate']:.0f}% win rate",
                "action": "Stop trading this symbol or reduce position size"
            })
        
        # Execution quality
        exec_analysis = self.analyze_execution_quality()
        if exec_analysis.get('status') != 'no_data':
            avg_slippage = exec_analysis.get('avg_slippage_pct', 0)
            if abs(avg_slippage) > 0.5:
                recommendations.append({
                    "priority": "MEDIUM",
                    "category": "Execution",
                    "title": "High Entry Slippage",
                    "description": f"Average slippage of {avg_slippage:.2f}% is eating into profits",
                    "action": "Use limit orders instead of market orders"
                })
        
        return recommendations
    
    def _generate_action_items(self) -> List[str]:
        """Generate concrete action items - uses individual analyses to avoid recursion"""
        actions = []
        
        # Signal quality actions
        sq = self.analyze_signal_quality()
        if sq.get('conversion_rate', 100) < 50:
            actions.append("🔧 Review and loosen entry filters to improve signal conversion")
        
        # Time-based actions
        tp = self.analyze_time_patterns()
        if tp.get('best_hours'):
            best = tp['best_hours'][0]
            actions.append(f"🕐 Schedule trading sessions around {best['hour']} (your best time)")
        
        # Symbol actions
        sp = self.analyze_symbol_performance()
        for symbol in sp.get('best_performers', [])[:2]:
            actions.append(f"📈 Increase size for {symbol['symbol']} (Grade {symbol['grade']})")
        
        for symbol in sp.get('worst_performers', [])[:2]:
            actions.append(f"📉 Remove {symbol['symbol']} from watchlist (poor performance)")
        
        return actions


# API functions for FastAPI integration
def get_enhanced_learning_report() -> Dict[str, Any]:
    """Get comprehensive learning report"""
    engine = EnhancedLearningEngine()
    return engine.generate_comprehensive_report()


def get_signal_quality_analysis() -> Dict[str, Any]:
    """Get signal quality analysis"""
    engine = EnhancedLearningEngine()
    return engine.analyze_signal_quality()


def get_time_pattern_analysis() -> Dict[str, Any]:
    """Get time-based performance patterns"""
    engine = EnhancedLearningEngine()
    return engine.analyze_time_patterns()


def get_symbol_insights_detailed() -> Dict[str, Any]:
    """Get detailed symbol insights"""
    engine = EnhancedLearningEngine()
    return engine.analyze_symbol_performance()


if __name__ == "__main__":
    # Test the engine
    engine = EnhancedLearningEngine()
    report = engine.generate_comprehensive_report()
    print(json.dumps(report, indent=2, default=str))
