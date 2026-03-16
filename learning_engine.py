"""
Robust Learning & Insights Engine
==================================
Handles all edge cases and provides reliable analysis.
"""

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

# File paths
TRADES_FILE = Path("trades_log.json")
SIGNALS_FILE = Path("signals_log.json")
TURBO_FILE = Path("turbo_queue.json")


def safe_json_load(filepath: Path, default=None) -> Any:
    """Safely load JSON file"""
    if not filepath.exists():
        return default
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return default


def safe_float(value, default=0.0) -> float:
    """Safely convert to float"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class LearningEngine:
    """Robust learning engine with proper error handling"""
    
    def __init__(self):
        self.trades = self._load_trades()
        self.signals = safe_json_load(SIGNALS_FILE, [])
        self.turbo = safe_json_load(TURBO_FILE, [])
    
    def _load_trades(self) -> List[Dict]:
        """Load and classify trades"""
        trades = safe_json_load(TRADES_FILE, [])
        
        for trade in trades:
            order_id = str(trade.get('order_id', ''))
            # Classify trade type
            if order_id.startswith('PAPER_') or order_id.startswith('ANALYSIS_'):
                trade['trade_type'] = 'paper'
            elif order_id.isdigit() or len(order_id) > 10:
                trade['trade_type'] = 'live'
            else:
                trade['trade_type'] = 'paper'  # Default to paper for safety
            
            # Ensure numeric fields
            trade['pnl'] = safe_float(trade.get('pnl'))
            trade['entry_price'] = safe_float(trade.get('entry_price'))
        
        return trades
    
    def get_summary(self) -> Dict:
        """Get high-level summary"""
        if not self.trades:
            return {"status": "no_data", "message": "No trades found"}
        
        paper_trades = [t for t in self.trades if t.get('trade_type') == 'paper']
        live_trades = [t for t in self.trades if t.get('trade_type') == 'live']
        
        # Calculate P&L
        paper_pnl = sum(t.get('pnl', 0) for t in paper_trades)
        live_pnl = sum(t.get('pnl', 0) for t in live_trades)
        
        # Win rates
        paper_wins = sum(1 for t in paper_trades if t.get('pnl', 0) > 0)
        live_wins = sum(1 for t in live_trades if t.get('pnl', 0) > 0)
        
        paper_wr = (paper_wins / len(paper_trades) * 100) if paper_trades else 0
        live_wr = (live_wins / len(live_trades) * 100) if live_trades else 0
        
        return {
            "status": "ok",
            "total_trades": len(self.trades),
            "paper": {
                "count": len(paper_trades),
                "pnl": round(paper_pnl, 2),
                "win_rate": round(paper_wr, 1),
                "wins": paper_wins,
                "losses": len(paper_trades) - paper_wins
            },
            "live": {
                "count": len(live_trades),
                "pnl": round(live_pnl, 2),
                "win_rate": round(live_wr, 1),
                "wins": live_wins,
                "losses": len(live_trades) - live_wins
            },
            "combined_pnl": round(paper_pnl + live_pnl, 2)
        }
    
    def get_symbol_performance(self) -> Dict:
        """Get per-symbol performance with paper/live breakdown"""
        if not self.trades:
            return {"status": "no_data", "symbols": []}
        
        # Group by symbol
        symbol_data = defaultdict(lambda: {"paper": [], "live": []})
        
        for trade in self.trades:
            symbol = trade.get('symbol', '')
            if not symbol:
                continue
            trade_type = trade.get('trade_type', 'paper')
            symbol_data[symbol][trade_type].append(trade)
        
        # Calculate metrics for each symbol
        results = []
        for symbol, data in symbol_data.items():
            paper_trades = data['paper']
            live_trades = data['live']
            
            # Paper stats
            paper_pnl = sum(t.get('pnl', 0) for t in paper_trades)
            paper_wins = sum(1 for t in paper_trades if t.get('pnl', 0) > 0)
            paper_count = len(paper_trades)
            
            # Live stats
            live_pnl = sum(t.get('pnl', 0) for t in live_trades)
            live_wins = sum(1 for t in live_trades if t.get('pnl', 0) > 0)
            live_count = len(live_trades)
            
            # Combined
            total_pnl = paper_pnl + live_pnl
            total_count = paper_count + live_count
            
            # Execution gap (if both have trades)
            execution_gap = None
            if paper_count >= 2 and live_count >= 1:
                paper_wr = (paper_wins / paper_count * 100)
                live_wr = (live_wins / live_count * 100) if live_count > 0 else 0
                execution_gap = round(paper_wr - live_wr, 1)
            
            # Grade
            combined_wr = (paper_wins + live_wins) / total_count * 100 if total_count > 0 else 0
            if combined_wr >= 60:
                grade = "A"
            elif combined_wr >= 50:
                grade = "B"
            elif combined_wr >= 40:
                grade = "C"
            else:
                grade = "D"
            
            results.append({
                "symbol": symbol,
                "paper": {
                    "trades": paper_count,
                    "pnl": round(paper_pnl, 2),
                    "win_rate": round(paper_wins / paper_count * 100, 1) if paper_count > 0 else 0,
                    "wins": paper_wins
                },
                "live": {
                    "trades": live_count,
                    "pnl": round(live_pnl, 2),
                    "win_rate": round(live_wins / live_count * 100, 1) if live_count > 0 else 0,
                    "wins": live_wins
                },
                "combined": {
                    "trades": total_count,
                    "pnl": round(total_pnl, 2),
                    "win_rate": round(combined_wr, 1)
                },
                "execution_gap": execution_gap,
                "grade": grade
            })
        
        # Sort by combined P&L
        results.sort(key=lambda x: x['combined']['pnl'], reverse=True)
        
        return {
            "status": "ok",
            "count": len(results),
            "symbols": results,
            "summary": {
                "paper_trades": sum(s['paper']['trades'] for s in results),
                "live_trades": sum(s['live']['trades'] for s in results),
                "paper_pnl": round(sum(s['paper']['pnl'] for s in results), 2),
                "live_pnl": round(sum(s['live']['pnl'] for s in results), 2)
            }
        }
    
    def get_signal_analysis(self) -> Dict:
        """Analyze signal quality"""
        if not self.signals:
            return {"status": "no_data"}
        
        total = len(self.signals)
        
        # Status breakdown
        status_counts = defaultdict(int)
        for s in self.signals:
            status = s.get('status', 'UNKNOWN')
            status_counts[status] += 1
        
        executed = status_counts.get('EXECUTED', 0)
        rejected = status_counts.get('REJECTED', 0)
        conversion = (executed / (executed + rejected) * 100) if (executed + rejected) > 0 else 0
        
        # Grade
        if conversion >= 60:
            grade = "A"
        elif conversion >= 40:
            grade = "B"
        elif conversion >= 20:
            grade = "C"
        else:
            grade = "D"
        
        return {
            "status": "ok",
            "total_signals": total,
            "conversion_rate": round(conversion, 1),
            "grade": grade,
            "breakdown": dict(status_counts)
        }
    
    def get_time_analysis(self) -> Dict:
        """Analyze performance by time of day"""
        if not self.trades:
            return {"status": "no_data"}
        
        hourly = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        
        for trade in self.trades:
            try:
                date_str = trade.get('date', '')
                if not date_str:
                    continue
                
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                hour = dt.strftime('%H:00')
                
                hourly[hour]["trades"] += 1
                pnl = trade.get('pnl', 0)
                hourly[hour]["pnl"] += pnl
                if pnl > 0:
                    hourly[hour]["wins"] += 1
            except:
                continue
        
        # Convert to list and calculate win rates
        results = []
        for hour, data in sorted(hourly.items()):
            if data["trades"] >= 1:
                wr = (data["wins"] / data["trades"] * 100)
                results.append({
                    "hour": hour,
                    "trades": data["trades"],
                    "win_rate": round(wr, 1),
                    "pnl": round(data["pnl"], 2),
                    "avg_pnl": round(data["pnl"] / data["trades"], 2)
                })
        
        # Sort by win rate
        results.sort(key=lambda x: x["win_rate"], reverse=True)
        
        return {
            "status": "ok",
            "hours": results,
            "best_hour": results[0] if results else None,
            "worst_hour": results[-1] if len(results) > 1 else None
        }
    
    def get_recommendations(self) -> List[Dict]:
        """Generate actionable recommendations"""
        recs = []
        
        summary = self.get_summary()
        if summary.get('status') == 'no_data':
            return []
        
        # Check conversion rate
        signal_analysis = self.get_signal_analysis()
        conv = signal_analysis.get('conversion_rate', 100)
        if conv < 30:
            recs.append({
                "priority": "HIGH",
                "title": "Low Signal Conversion",
                "message": f"Only {conv:.0f}% of signals are being executed. Check your filters.",
                "action": "Review entry criteria"
            })
        
        # Check paper vs live gap
        paper = summary.get('paper', {})
        live = summary.get('live', {})
        if paper.get('count', 0) > 5 and live.get('count', 0) > 2:
            gap = paper.get('win_rate', 0) - live.get('win_rate', 0)
            if gap > 20:
                recs.append({
                    "priority": "HIGH",
                    "title": "Execution Gap Detected",
                    "message": f"Paper: {paper['win_rate']:.0f}% vs Live: {live['win_rate']:.0f}%",
                    "action": "Check slippage and execution timing"
                })
        
        # Check time patterns
        time_data = self.get_time_analysis()
        if time_data.get('status') == 'ok':
            best = time_data.get('best_hour')
            if best and best['win_rate'] > 50:
                recs.append({
                    "priority": "MEDIUM",
                    "title": f"Best Trading Hour: {best['hour']}",
                    "message": f"{best['win_rate']:.0f}% win rate during this hour",
                    "action": "Focus trading during this time"
                })
        
        # Check symbol performance
        symbol_data = self.get_symbol_performance()
        if symbol_data.get('status') == 'ok':
            symbols = symbol_data.get('symbols', [])
            bad_symbols = [s for s in symbols if s['grade'] == 'D' and s['combined']['trades'] >= 2]
            for sym in bad_symbols[:2]:
                recs.append({
                    "priority": "MEDIUM",
                    "title": f"Avoid: {sym['symbol']}",
                    "message": f"Poor performance: {sym['combined']['win_rate']:.0f}% win rate",
                    "action": "Remove from watchlist"
                })
        
        return recs
    
    def get_full_report(self) -> Dict:
        """Get complete learning report"""
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": self.get_summary(),
            "symbols": self.get_symbol_performance(),
            "signals": self.get_signal_analysis(),
            "time_patterns": self.get_time_analysis(),
            "recommendations": self.get_recommendations()
        }


# API helper functions
def get_learning_report() -> Dict:
    """Get full learning report for API"""
    engine = LearningEngine()
    return engine.get_full_report()


def get_learning_summary() -> Dict:
    """Get summary only"""
    engine = LearningEngine()
    return engine.get_summary()
