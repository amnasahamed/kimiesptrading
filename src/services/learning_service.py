"""
Learning service — absorbs learning_engine.py + enhanced_learning.py.

Reads from the SQLite DB (trades, signals, insights tables) instead of JSON files.
All public functions are sync (engines run quickly on in-memory data).
"""
import time
from collections import defaultdict
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.core.logging_config import get_logger
from src.models.database import get_db_session

logger = get_logger()

# ---------------------------------------------------------------------------
# Analytics in-memory result cache (busted when new trades land)
# ---------------------------------------------------------------------------
_analytics_cache: Dict[str, Any] = {}
_analytics_cache_ts: float = 0.0
_ANALYTICS_TTL = 600.0  # 10 minutes — analytics data changes infrequently


def _bust_analytics_cache():
    global _analytics_cache, _analytics_cache_ts
    _analytics_cache = {}
    _analytics_cache_ts = 0.0


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

# Only load trades from the last N days — avoids full-table scans
_TRADE_HISTORY_DAYS = 90


def _load_trades_from_db(db: Session) -> List[Dict]:
    from src.models.database import Trade
    cutoff = ist_naive() - timedelta(days=_TRADE_HISTORY_DAYS)
    rows = db.query(Trade).filter(Trade.date >= cutoff).all()
    result = []
    for t in rows:
        order_id = str(t.order_id or "")
        is_paper_from_order = order_id.startswith("PAPER_") or order_id.startswith("ANALYSIS_")
        is_paper = t.paper_trading if t.paper_trading is not None else is_paper_from_order
        result.append({
            "symbol": t.symbol,
            "pnl": float(t.pnl or 0),
            "entry_price": float(t.entry_price or 0),
            "exit_price": float(t.exit_price or 0),
            "status": t.status,
            "order_id": order_id,
            "paper_trading": is_paper,
            "trade_type": "paper" if is_paper else "live",
            "date": t.date.isoformat() if t.date else None,
            "scan_name": t.scan_name,
        })
    return result


def _load_signals_from_db(db: Session) -> List[Dict]:
    from src.models.database import Signal
    cutoff = ist_naive() - timedelta(days=_TRADE_HISTORY_DAYS)
    rows = db.query(Signal).filter(Signal.timestamp >= cutoff).all()
    return [
        {
            "symbol": s.symbol,
            "status": s.status,
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "scan_name": (s.signal_metadata or {}).get("scan_name") if s.signal_metadata else None,
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
            "generated_at": ist_naive().isoformat(),
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
# Scanner performance helper
# ---------------------------------------------------------------------------

def _get_scanner_performance(db: Session) -> Dict[str, Any]:
    """Compute per-scanner win rate and P&L using SQL GROUP BY."""
    from src.models.database import Trade
    cutoff = ist_naive() - timedelta(days=_TRADE_HISTORY_DAYS)

    rows = (
        db.query(
            Trade.scan_name,
            func.count(Trade.id).label("trades"),
            func.sum(case((Trade.pnl.isnot(None) & (Trade.pnl > 0), 1), else_=0)).label("wins"),
            func.sum(case((Trade.pnl.isnot(None), Trade.pnl), else_=0.0)).label("pnl"),
        )
        .filter(
            Trade.date >= cutoff,
            Trade.scan_name.isnot(None),
            Trade.scan_name != "",
        )
        .group_by(Trade.scan_name)
        .all()
    )

    results = []
    for r in rows:
        count = r.trades
        wins = int(r.wins or 0)
        pnl = float(r.pnl or 0)
        wr = round(wins / count * 100, 1) if count else 0
        avg_pnl = round(pnl / count, 2) if count else 0
        grade = "A" if wr >= 60 else "B" if wr >= 50 else "C" if wr >= 40 else "D"
        results.append({
            "scanner": r.scan_name,
            "trades": count,
            "wins": wins,
            "losses": count - wins,
            "win_rate": wr,
            "total_pnl": round(pnl, 2),
            "avg_pnl": avg_pnl,
            "grade": grade,
        })

    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    total_trades = sum(r["trades"] for r in results)
    total_pnl = sum(r["total_pnl"] for r in results)
    return {
        "scanners": results,
        "total_scanners": len(results),
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "best": results[0] if results else None,
        "worst": results[-1] if results else None,
    }


# ---------------------------------------------------------------------------
# Priority recommendations builder
# ---------------------------------------------------------------------------

def _build_priority_recommendations(
    engine: "LearningEngine",
    optimizer: "StrategyOptimizer",
    scanner_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate ranked, actionable recommendations with specific config changes."""
    recs: List[Dict[str, Any]] = []
    summary = engine.get_summary()
    sig = engine.get_signal_analysis()
    time_data = engine.get_time_analysis()
    symbol_data = engine.get_symbol_performance()

    # HIGH: No live trades yet — don't go live
    live = summary.get("live", {})
    if live.get("count", 0) == 0 and summary.get("paper", {}).get("count", 0) >= 5:
        recs.append({
            "priority": "HIGH",
            "title": "Validate in paper before going live",
            "message": f"{summary['paper']['count']} paper trades but 0 live trades. Run live with small capital to validate.",
            "action": "Enable paper mode",
            "action_type": "paper_mode",
        })

    # HIGH: Execution gap — paper vs live mismatch
    paper = summary.get("paper", {})
    if paper.get("count", 0) >= 5 and live.get("count", 0) >= 2:
        gap = paper.get("win_rate", 0) - live.get("win_rate", 0)
        if gap > 15:
            recs.append({
                "priority": "HIGH",
                "title": f"Execution gap: {gap:.0f}%",
                "message": f"Paper {paper['win_rate']:.0f}% win rate vs Live {live['win_rate']:.0f}%. "
                            f"Check slippage and order execution.",
                "action": "Review entry timing",
                "action_type": "review",
            })

    # HIGH: Low signal conversion
    conv = sig.get("conversion_rate", 0)
    if conv < 30 and sig.get("total_signals", 0) > 10:
        recs.append({
            "priority": "HIGH",
            "title": f"Signal conversion only {conv:.0f}%",
            "message": f"{sig['total_signals']} signals received but only {sig.get('breakdown', {}).get('EXECUTED', 0)} executed.",
            "action": "Relax validation filters",
            "action_type": "config",
            "suggested": {"prevent_duplicate_stocks": False},
        })

    # HIGH: Losing scanner generating most trades
    scanners = scanner_data.get("scanners", [])
    if len(scanners) >= 2:
        worst = scanners[-1]
        best = scanners[0]
        if worst["win_rate"] < 40 and worst["trades"] >= 3:
            recs.append({
                "priority": "HIGH",
                "title": f"Stop using: {worst['scanner']}",
                "message": f"{worst['trades']} trades, {worst['win_rate']:.0f}% win rate, ₹{worst['total_pnl']:.0f} loss. "
                            f"Best alternative: {best['scanner']} ({best['win_rate']:.0f}% win rate).",
                "action": f"Disable {worst['scanner']}",
                "action_type": "scanner_disable",
                "scanner": worst["scanner"],
            })

    # HIGH: Negative total P&L
    if summary.get("combined_pnl", 0) < 0:
        recs.append({
            "priority": "HIGH",
            "title": "Overall P&L is negative",
            "message": f"Total P&L: ₹{summary['combined_pnl']:.0f}. Review worst-performing symbols.",
            "action": "Review losers",
            "action_type": "review",
        })

    # MEDIUM: Time-based insight
    best_hour = time_data.get("best_hour")
    worst_hour = time_data.get("worst_hour")
    if best_hour and best_hour["win_rate"] >= 55:
        recs.append({
            "priority": "MEDIUM",
            "title": f"Trade more at {best_hour['hour']}",
            "message": f"{best_hour['win_rate']:.0f}% win rate, ₹{best_hour['avg_pnl']:.2f} avg P&L. "
                        f"{worst_hour['hour']} is worst at {worst_hour['win_rate']:.0f}%.",
            "action": f"Focus on {best_hour['hour']} window",
            "action_type": "time_window",
        })

    # MEDIUM: Symbol avoid
    symbols = symbol_data.get("symbols", [])
    avoid = [s for s in symbols if s["grade"] in ("C", "D") and s["combined"]["trades"] >= 3]
    for sym in avoid[:2]:
        recs.append({
            "priority": "MEDIUM",
            "title": f"Review {sym['symbol']}",
            "message": f"{sym['combined']['win_rate']:.0f}% win rate, ₹{sym['combined']['pnl']:.0f} P&L across {sym['combined']['trades']} trades.",
            "action": f"Remove {sym['symbol']} from watchlist",
            "action_type": "symbol_avoid",
            "symbol": sym["symbol"],
        })

    # MEDIUM: R:R validation
    rr_buckets = optimizer.analyze_risk_reward_performance().get("buckets", [])
    for bucket in rr_buckets:
        rr = float(bucket["rr_ratio"])
        achieved_wr = bucket["win_rate"]
        # If 1:2 R:R but only winning 30%, that's terrible
        if rr >= 2.0 and achieved_wr < 40:
            recs.append({
                "priority": "MEDIUM",
                "title": f"Risk:Reward mismatch at {rr:.1f}x",
                "message": f"Using {rr:.1f}x R:R but only winning {achieved_wr:.0f}% of trades. "
                            f"Need {max(35, round(100/rr, 0)):.0f}% win rate to break even.",
                "action": "Tighten stop loss",
                "action_type": "config",
            })

    # Sort: HIGH first, then by type
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 2))
    return recs[:10]  # Cap at 10


def _compute_learning_grade(
    summary: Dict,
    signal_data: Dict,
    scanner_data: Dict,
) -> Dict[str, Any]:
    """Compute overall A-F learning grade and confidence metrics."""
    paper = summary.get("paper", {})
    live = summary.get("live", {})
    combined_wr = 0.0
    if paper.get("count", 0) + live.get("count", 0) > 0:
        total_wins = paper.get("wins", 0) + live.get("wins", 0)
        total_trades = paper.get("count", 0) + live.get("count", 0)
        combined_wr = round(total_wins / total_trades * 100, 1) if total_trades else 0

    conv = signal_data.get("conversion_rate", 0)
    scanners = scanner_data.get("scanners", [])
    best_scanner_wr = scanners[0]["win_rate"] if scanners else 0
    combined_pnl = summary.get("combined_pnl", 0)

    # Scoring: win rate 40%, P&L 30%, signal conversion 20%, best scanner 10%
    wr_score = min(combined_wr / 60 * 100, 100) if combined_wr else 0
    pnl_score = 100 if combined_pnl > 0 else max(0, 100 + combined_pnl / 10)
    conv_score = min(conv / 60 * 100, 100) if conv else 0
    scanner_score = min(best_scanner_wr / 60 * 100, 100) if best_scanner_wr else 0

    overall = round(
        wr_score * 0.40 +
        pnl_score * 0.30 +
        conv_score * 0.20 +
        scanner_score * 0.10,
        1,
    )

    if overall >= 80:
        grade = "A"
        label = "Excellent"
    elif overall >= 65:
        grade = "B"
        label = "Good"
    elif overall >= 50:
        grade = "C"
        label = "Average"
    elif overall >= 35:
        grade = "D"
        label = "Needs Work"
    else:
        grade = "F"
        label = "Critical"

    return {
        "grade": grade,
        "label": label,
        "score": overall,
        "win_rate": combined_wr,
        "total_pnl": combined_pnl,
        "signal_conversion": conv,
        "best_scanner_wr": best_scanner_wr,
    }


# ---------------------------------------------------------------------------
# Main dashboard aggregator (cached)
# ---------------------------------------------------------------------------

def _learning_dashboard_impl(db: Session) -> Dict[str, Any]:
    """Aggregate all learning data into a single dashboard payload."""
    engine = _engine_from_db(db)
    trades = engine.trades  # reuse already-loaded trades (avoids duplicate query)
    optimizer = StrategyOptimizer(trades, {})

    summary = engine.get_summary()
    symbol_data = engine.get_symbol_performance()
    scanner_data = _get_scanner_performance(db)
    time_data = engine.get_time_analysis()
    rr_data = optimizer.analyze_risk_reward_performance()
    signal_data = engine.get_signal_analysis()

    grade = _compute_learning_grade(summary, signal_data, scanner_data)
    recommendations = _build_priority_recommendations(engine, optimizer, scanner_data)

    # Top/bottom symbols
    symbols = symbol_data.get("symbols", [])
    top_winners = symbols[:5]
    top_losers = sorted(symbols, key=lambda s: s["combined"]["pnl"])[:5]

    return {
        "grade": grade,
        "summary": summary,
        "top_winners": top_winners,
        "top_losers": top_losers,
        "time_patterns": time_data,
        "scanner_performance": scanner_data,
        "risk_reward": rr_data,
        "signals": signal_data,
        "recommendations": recommendations,
        "generated_at": ist_naive().isoformat(),
    }


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def _engine_from_db(db: Session) -> LearningEngine:
    return LearningEngine(
        trades=_load_trades_from_db(db),
        signals=_load_signals_from_db(db),
    )


def _cached(key: str, db: Session, fn):
    """Return cached result if fresh, otherwise recompute and cache."""
    global _analytics_cache, _analytics_cache_ts
    now = time.monotonic()
    if key in _analytics_cache and (now - _analytics_cache_ts) < _ANALYTICS_TTL:
        return _analytics_cache[key]
    result = fn()
    _analytics_cache[key] = result
    _analytics_cache_ts = now
    return result


def get_learning_report(db: Session) -> Dict:
    return _cached("report", db, lambda: _engine_from_db(db).get_full_report())


def get_learning_summary(db: Session) -> Dict:
    return _cached("summary", db, lambda: _engine_from_db(db).get_summary())


def get_symbol_performance(db: Session) -> Dict:
    return _cached("symbol_perf", db, lambda: _engine_from_db(db).get_symbol_performance())


def get_signal_analysis(db: Session) -> Dict:
    return _cached("signal_analysis", db, lambda: _engine_from_db(db).get_signal_analysis())


def get_time_patterns(db: Session) -> Dict:
    return _cached("time_patterns", db, lambda: _engine_from_db(db).get_time_analysis())


def get_recommendations(db: Session) -> List[Dict]:
    return _cached("recommendations", db, lambda: _engine_from_db(db).get_recommendations())


def get_learning_dashboard(db: Session) -> Dict:
    return _cached("learning_dashboard", db, lambda: _learning_dashboard_impl(db))


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
        "generated_at": ist_naive().isoformat(),
    }


def _compute_side_stats(trades_rows) -> Dict:
    """Compute stats for one side (paper or live)."""
    closed = [t for t in trades_rows if t.status in ("CLOSED", "closed") and t.pnl is not None]
    pnl_values = [float(t.pnl) for t in closed if t.pnl is not None]
    wins = [t for t in closed if float(t.pnl or 0) > 0]
    total_pnl = sum(pnl_values)
    win_rate = round(len(wins) / len(pnl_values) * 100, 1) if pnl_values else 0.0
    return {
        "trades": len(trades_rows),
        "closed": len(pnl_values),
        "wins": len(wins),
        "losses": len(pnl_values) - len(wins),
        "pnl": round(total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "win_rate": win_rate,
        "avg_pnl": round(total_pnl / len(pnl_values), 2) if pnl_values else 0.0,
        "best_pnl": round(max(pnl_values, default=0.0), 2),
        "worst_pnl": round(min(pnl_values, default=0.0), 2),
    }


def _compute_symbol_insights(trades_rows) -> Dict:
    """Compute per-symbol insight metrics with paper/live breakdown."""
    paper = _compute_side_stats([t for t in trades_rows if getattr(t, 'paper_trading', False)])
    live = _compute_side_stats([t for t in trades_rows if not getattr(t, 'paper_trading', False)])
    combined_pnl = round(paper["total_pnl"] + live["total_pnl"], 2)
    combined_closed = paper["closed"] + live["closed"]
    combined_wins = paper["wins"] + live["wins"]
    return {
        "paper": paper,
        "live": live,
        "combined": {
            "trades": paper["trades"] + live["trades"],
            "closed": combined_closed,
            "pnl": combined_pnl,
            "win_rate": round(combined_wins / combined_closed * 100, 1) if combined_closed else 0.0,
        },
        "total_pnl": combined_pnl,
        "avg_pnl": round(combined_pnl / combined_closed, 2) if combined_closed else 0.0,
        "win_rate": round(combined_wins / combined_closed * 100, 1) if combined_closed else 0.0,
    }


def get_insights(db: Session) -> Dict:
    """Return per-symbol insights with paper/live breakdown, computed from trades table."""
    return _cached("insights", db, lambda: _get_insights_impl(db))


def _get_insights_impl(db: Session) -> Dict:
    """Uncached implementation of get_insights."""
    from src.models.database import Trade
    from collections import defaultdict
    cutoff = ist_naive() - timedelta(days=_TRADE_HISTORY_DAYS)
    rows = db.query(Trade).filter(Trade.date >= cutoff).all()
    grouped: Dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row.symbol].append(row)
    symbols = {sym: _compute_symbol_insights(trades) for sym, trades in grouped.items()}
    return {"status": "success", "symbols": symbols, "last_updated": ist_naive().isoformat()}


def get_symbol_insights(db: Session, symbol: str) -> Optional[Dict]:
    from src.models.database import Trade
    cutoff = ist_naive() - timedelta(days=_TRADE_HISTORY_DAYS)
    rows = db.query(Trade).filter(
        Trade.symbol == symbol.upper(),
        Trade.date >= cutoff
    ).all()
    if not rows:
        return None
    data = _compute_symbol_insights(rows)
    data["symbol"] = symbol.upper()
    return data
