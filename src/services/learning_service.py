"""
Learning service — absorbs learning_engine.py + enhanced_learning.py.

Reads from the SQLite DB (trades, signals, insights tables) instead of JSON files.
All public functions are sync (engines run quickly on in-memory data).
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.core.logging_config import get_logger
from src.models.database import get_db_session

logger = get_logger()

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_trades_from_db(db: Session) -> List[Dict]:
    from src.models.database import Trade
    rows = db.query(Trade).all()
    result = []
    for t in rows:
        order_id = str(t.order_id or "")
        is_paper = order_id.startswith("PAPER_") or order_id.startswith("ANALYSIS_")
        result.append({
            "symbol": t.symbol,
            "pnl": float(t.pnl or 0),
            "entry_price": float(t.entry_price or 0),
            "exit_price": float(t.exit_price or 0),
            "status": t.status,
            "order_id": order_id,
            "paper_trading": t.paper_trading if t.paper_trading is not None else is_paper,
            "trade_type": "paper" if (t.paper_trading or is_paper) else "live",
            "date": t.date.isoformat() if t.date else None,
            "scan_name": t.scan_name,
        })
    return result


def _load_signals_from_db(db: Session) -> List[Dict]:
    from src.models.database import Signal
    rows = db.query(Signal).all()
    return [
        {
            "symbol": s.symbol,
            "status": s.status,
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "scan_name": s.scan_name,
        }
        for s in rows
    ]


# ---------------------------------------------------------------------------
# LearningEngine (absorbed from learning_engine.py)
# ---------------------------------------------------------------------------

class LearningEngine:
    def __init__(self, trades: List[Dict], signals: List[Dict]):
        self.trades = trades
        self.signals = signals

    def get_summary(self) -> Dict:
        if not self.trades:
            return {"status": "no_data", "message": "No trades found"}

        paper = [t for t in self.trades if t["trade_type"] == "paper"]
        live = [t for t in self.trades if t["trade_type"] == "live"]

        def _stats(items):
            pnl = sum(t["pnl"] for t in items)
            wins = sum(1 for t in items if t["pnl"] > 0)
            count = len(items)
            return {
                "count": count,
                "pnl": round(pnl, 2),
                "win_rate": round(wins / count * 100, 1) if count else 0,
                "wins": wins,
                "losses": count - wins,
            }

        p, l = _stats(paper), _stats(live)
        return {
            "status": "ok",
            "total_trades": len(self.trades),
            "paper": p,
            "live": l,
            "combined_pnl": round(p["pnl"] + l["pnl"], 2),
        }

    def get_symbol_performance(self) -> Dict:
        if not self.trades:
            return {"status": "no_data", "symbols": []}

        by_symbol: Dict[str, Dict] = defaultdict(lambda: {"paper": [], "live": []})
        for t in self.trades:
            sym = t.get("symbol", "")
            if sym:
                by_symbol[sym][t["trade_type"]].append(t)

        results = []
        for symbol, data in by_symbol.items():
            pt, lt = data["paper"], data["live"]
            pp = sum(t["pnl"] for t in pt)
            pw = sum(1 for t in pt if t["pnl"] > 0)
            lp = sum(t["pnl"] for t in lt)
            lw = sum(1 for t in lt if t["pnl"] > 0)
            total = len(pt) + len(lt)
            comb_wr = (pw + lw) / total * 100 if total else 0
            grade = "A" if comb_wr >= 60 else "B" if comb_wr >= 50 else "C" if comb_wr >= 40 else "D"
            execution_gap = None
            if len(pt) >= 2 and len(lt) >= 1:
                execution_gap = round(pw / len(pt) * 100 - lw / len(lt) * 100, 1)

            results.append({
                "symbol": symbol,
                "paper": {
                    "trades": len(pt),
                    "pnl": round(pp, 2),
                    "win_rate": round(pw / len(pt) * 100, 1) if pt else 0,
                    "wins": pw,
                },
                "live": {
                    "trades": len(lt),
                    "pnl": round(lp, 2),
                    "win_rate": round(lw / len(lt) * 100, 1) if lt else 0,
                    "wins": lw,
                },
                "combined": {
                    "trades": total,
                    "pnl": round(pp + lp, 2),
                    "win_rate": round(comb_wr, 1),
                },
                "execution_gap": execution_gap,
                "grade": grade,
            })

        results.sort(key=lambda x: x["combined"]["pnl"], reverse=True)
        return {
            "status": "ok",
            "count": len(results),
            "symbols": results,
            "summary": {
                "paper_trades": sum(s["paper"]["trades"] for s in results),
                "live_trades": sum(s["live"]["trades"] for s in results),
                "paper_pnl": round(sum(s["paper"]["pnl"] for s in results), 2),
                "live_pnl": round(sum(s["live"]["pnl"] for s in results), 2),
            },
        }

    def get_signal_analysis(self) -> Dict:
        if not self.signals:
            return {"status": "no_data"}

        counts: Dict[str, int] = defaultdict(int)
        for s in self.signals:
            counts[s.get("status", "UNKNOWN")] += 1

        executed = counts.get("EXECUTED", 0)
        rejected = counts.get("REJECTED", 0)
        failed = counts.get("FAILED", 0)
        total_proc = executed + rejected + failed
        conv = (executed / total_proc * 100) if total_proc else 0
        grade = "A" if conv >= 60 else "B" if conv >= 40 else "C" if conv >= 20 else "D"

        return {
            "status": "ok",
            "total_signals": len(self.signals),
            "conversion_rate": round(conv, 1),
            "grade": grade,
            "breakdown": dict(counts),
        }

    def get_time_analysis(self) -> Dict:
        if not self.trades:
            return {"status": "no_data"}

        hourly: Dict[str, Dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in self.trades:
            try:
                dt = datetime.fromisoformat(t["date"].replace("Z", "+00:00"))
                hour = dt.strftime("%H:00")
                hourly[hour]["trades"] += 1
                pnl = t["pnl"]
                hourly[hour]["pnl"] += pnl
                if pnl > 0:
                    hourly[hour]["wins"] += 1
            except Exception:
                continue

        results = []
        for hour, d in sorted(hourly.items()):
            if d["trades"] >= 1:
                wr = d["wins"] / d["trades"] * 100
                results.append({
                    "hour": hour,
                    "trades": d["trades"],
                    "win_rate": round(wr, 1),
                    "pnl": round(d["pnl"], 2),
                    "avg_pnl": round(d["pnl"] / d["trades"], 2),
                })
        results.sort(key=lambda x: x["win_rate"], reverse=True)

        return {
            "status": "ok",
            "hours": results,
            "best_hour": results[0] if results else None,
            "worst_hour": results[-1] if len(results) > 1 else None,
        }

    def get_recommendations(self) -> List[Dict]:
        recs = []
        summary = self.get_summary()
        if summary.get("status") == "no_data":
            return []

        sig = self.get_signal_analysis()
        conv = sig.get("conversion_rate", 100)
        if conv < 30:
            recs.append({
                "priority": "HIGH",
                "title": "Low Signal Conversion",
                "message": f"Only {conv:.0f}% of signals are executed. Check filters.",
                "action": "Review entry criteria",
            })

        paper = summary.get("paper", {})
        live = summary.get("live", {})
        if paper.get("count", 0) > 5 and live.get("count", 0) > 2:
            gap = paper.get("win_rate", 0) - live.get("win_rate", 0)
            if gap > 20:
                recs.append({
                    "priority": "HIGH",
                    "title": "Execution Gap Detected",
                    "message": f"Paper: {paper['win_rate']:.0f}% vs Live: {live['win_rate']:.0f}%",
                    "action": "Check slippage and execution timing",
                })

        time_data = self.get_time_analysis()
        if time_data.get("status") == "ok":
            best = time_data.get("best_hour")
            if best and best["win_rate"] > 50:
                recs.append({
                    "priority": "MEDIUM",
                    "title": f"Best Trading Hour: {best['hour']}",
                    "message": f"{best['win_rate']:.0f}% win rate",
                    "action": "Focus trading during this hour",
                })

        sym_data = self.get_symbol_performance()
        if sym_data.get("status") == "ok":
            bad = [s for s in sym_data.get("symbols", []) if s["grade"] == "D" and s["combined"]["trades"] >= 2]
            for sym in bad[:2]:
                recs.append({
                    "priority": "MEDIUM",
                    "title": f"Avoid: {sym['symbol']}",
                    "message": f"Poor performance: {sym['combined']['win_rate']:.0f}% win rate",
                    "action": "Remove from watchlist",
                })

        return recs

    def get_full_report(self) -> Dict:
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": self.get_summary(),
            "symbols": self.get_symbol_performance(),
            "signals": self.get_signal_analysis(),
            "time_patterns": self.get_time_analysis(),
            "recommendations": self.get_recommendations(),
        }


# ---------------------------------------------------------------------------
# StrategyOptimizer (inlined from chartink_webhook.py)
# ---------------------------------------------------------------------------

class StrategyOptimizer:
    def __init__(self, trades: List[Dict], config: Dict):
        self.all_trades = trades
        self.thresholds = config.get("analysis_engine", {}).get("thresholds", {
            "min_trades_for_recommendation": 5,
            "execution_gap_threshold": 20,
            "min_win_rate_for_best": 60,
            "max_win_rate_for_worst": 35,
        })
        self.min_trades = self.thresholds.get("min_trades_for_recommendation", 5)

    def analyze_time_performance(self) -> Dict[str, Any]:
        hourly: Dict[str, Dict] = {f"{h:02d}:00": {"trades": 0, "wins": 0, "pnl": 0.0} for h in range(9, 16)}
        for t in self.all_trades:
            try:
                dt = datetime.fromisoformat(str(t.get("date", "")).replace("Z", "+00:00"))
                hour = dt.strftime("%H:00")
                if hour not in hourly:
                    continue
                hourly[hour]["trades"] += 1
                pnl = float(t.get("pnl") or 0)
                hourly[hour]["pnl"] += pnl
                if pnl > 0:
                    hourly[hour]["wins"] += 1
            except Exception:
                continue

        results = []
        for hour, d in sorted(hourly.items()):
            if d["trades"] > 0:
                wr = d["wins"] / d["trades"] * 100
                results.append({
                    "hour": hour,
                    "trades": d["trades"],
                    "win_rate": round(wr, 1),
                    "pnl": round(d["pnl"], 2),
                })
        results.sort(key=lambda x: x["win_rate"], reverse=True)
        return {"hours": results, "best": results[0] if results else None}

    def analyze_risk_reward_performance(self) -> Dict[str, Any]:
        buckets: Dict[str, Dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in self.all_trades:
            entry = float(t.get("entry_price") or 0)
            exit_ = float(t.get("exit_price") or 0)
            sl = float(t.get("stop_loss") or 0)
            tp = float(t.get("target") or 0)
            if not all([entry, sl, tp]):
                continue
            risk = entry - sl
            reward = tp - entry
            if risk <= 0:
                continue
            rr = round(reward / risk, 1)
            key = f"{rr:.1f}"
            buckets[key]["trades"] += 1
            pnl = float(t.get("pnl") or 0)
            buckets[key]["pnl"] += pnl
            if pnl > 0:
                buckets[key]["wins"] += 1

        results = [
            {
                "rr_ratio": k,
                "trades": v["trades"],
                "win_rate": round(v["wins"] / v["trades"] * 100, 1),
                "pnl": round(v["pnl"], 2),
            }
            for k, v in sorted(buckets.items())
            if v["trades"] >= 1
        ]
        return {"buckets": results}

    def analyze_atr_multiplier_performance(self) -> Dict[str, Any]:
        return {"message": "ATR multiplier analysis requires historical ATR data", "data": []}

    def analyze_position_sizing(self) -> Dict[str, Any]:
        if not self.all_trades:
            return {"status": "no_data"}
        quantities = [int(t.get("quantity") or 0) for t in self.all_trades if t.get("quantity")]
        if not quantities:
            return {"status": "no_data"}
        return {
            "avg_quantity": round(sum(quantities) / len(quantities), 1),
            "min_quantity": min(quantities),
            "max_quantity": max(quantities),
            "total_trades": len(quantities),
        }

    def generate_strategy_recommendations(self) -> List[Dict[str, Any]]:
        recs = []
        if len(self.all_trades) < self.min_trades:
            return [{"title": "Insufficient data", "message": f"Need {self.min_trades}+ trades for recommendations", "actionable": False}]

        time_perf = self.analyze_time_performance()
        best_hour = time_perf.get("best")
        if best_hour and best_hour.get("win_rate", 0) > self.thresholds.get("min_win_rate_for_best", 60):
            recs.append({
                "type": "time_optimization",
                "title": f"Focus on {best_hour['hour']} slot",
                "message": f"{best_hour['win_rate']:.0f}% win rate during this hour",
                "actionable": False,
                "priority": "MEDIUM",
            })

        paper = [t for t in self.all_trades if t.get("trade_type") == "paper"]
        live = [t for t in self.all_trades if t.get("trade_type") == "live"]
        if len(paper) >= 5 and len(live) >= 2:
            pw = sum(1 for t in paper if float(t.get("pnl") or 0) > 0) / len(paper) * 100
            lw = sum(1 for t in live if float(t.get("pnl") or 0) > 0) / len(live) * 100
            gap = pw - lw
            if gap > self.thresholds.get("execution_gap_threshold", 20):
                recs.append({
                    "type": "execution_gap",
                    "title": "Execution Gap Detected",
                    "message": f"Paper {pw:.0f}% vs Live {lw:.0f}%",
                    "actionable": True,
                    "suggested_config": {"risk_percent": 0.5},
                    "priority": "HIGH",
                })

        return recs


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def _engine_from_db(db: Session) -> LearningEngine:
    return LearningEngine(
        trades=_load_trades_from_db(db),
        signals=_load_signals_from_db(db),
    )


def get_learning_report(db: Session) -> Dict:
    return _engine_from_db(db).get_full_report()


def get_learning_summary(db: Session) -> Dict:
    return _engine_from_db(db).get_summary()


def get_symbol_performance(db: Session) -> Dict:
    return _engine_from_db(db).get_symbol_performance()


def get_signal_analysis(db: Session) -> Dict:
    return _engine_from_db(db).get_signal_analysis()


def get_time_patterns(db: Session) -> Dict:
    return _engine_from_db(db).get_time_analysis()


def get_recommendations(db: Session) -> List[Dict]:
    return _engine_from_db(db).get_recommendations()


def get_strategy_analytics(db: Session, config: Dict) -> Dict:
    trades = _load_trades_from_db(db)
    optimizer = StrategyOptimizer(trades, config)
    return {
        "status": "success",
        "time_performance": optimizer.analyze_time_performance(),
        "risk_reward_analysis": optimizer.analyze_risk_reward_performance(),
        "atr_analysis": optimizer.analyze_atr_multiplier_performance(),
        "position_sizing_analysis": optimizer.analyze_position_sizing(),
        "recommendations": optimizer.generate_strategy_recommendations(),
        "total_trades_analyzed": len(trades),
        "generated_at": datetime.now().isoformat(),
    }


def get_insights(db: Session) -> Dict:
    """Return per-symbol insights from the insights table."""
    from src.models.database import Insight
    rows = db.query(Insight).all()
    symbols = {}
    for row in rows:
        symbols[row.symbol] = {
            "trades": row.trades,
            "wins": row.wins,
            "losses": row.losses,
            "total_pnl": row.total_pnl,
            "avg_pnl": row.avg_pnl,
            "win_rate": row.win_rate,
            "best_pnl": row.best_pnl,
            "worst_pnl": row.worst_pnl,
        }
    return {"status": "success", "symbols": symbols, "last_updated": datetime.now().isoformat()}


def get_symbol_insights(db: Session, symbol: str) -> Optional[Dict]:
    from src.models.database import Insight
    row = db.query(Insight).filter(Insight.symbol == symbol.upper()).first()
    if not row:
        return None
    return {
        "symbol": row.symbol,
        "trades": row.trades,
        "wins": row.wins,
        "losses": row.losses,
        "total_pnl": row.total_pnl,
        "avg_pnl": row.avg_pnl,
        "win_rate": row.win_rate,
        "best_pnl": row.best_pnl,
        "worst_pnl": row.worst_pnl,
    }
