"""
Analytics & Learning API routes.

GET  /api/insights
GET  /api/insights/{symbol}
GET  /api/learning/report
GET  /api/learning/summary
GET  /api/learning/symbols
GET  /api/learning/signals
GET  /api/learning/time-patterns
GET  /api/learning/recommendations
GET  /api/strategy/analytics
POST /api/strategy/apply
POST /api/strategy/custom
POST /api/strategy/reset
GET  /api/strategy/history
"""
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.models.database import get_db_session
from src.services.learning_service import (
    get_insights,
    get_symbol_insights,
    get_learning_report,
    get_learning_summary,
    get_symbol_performance,
    get_signal_analysis,
    get_time_patterns,
    get_recommendations,
    get_strategy_analytics,
    StrategyOptimizer,
    _load_trades_from_db,
)

router = APIRouter(prefix="/api", tags=["analytics"])


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@router.get("/insights")
async def insights_all():
    """Per-symbol trade insights from DB."""
    db = get_db_session()
    try:
        return get_insights(db)
    finally:
        db.close()


@router.get("/insights/{symbol}")
async def insights_symbol(symbol: str):
    """Insights for a specific symbol."""
    db = get_db_session()
    try:
        data = get_symbol_insights(db, symbol.upper())
        if not data:
            raise HTTPException(status_code=404, detail=f"No insights for {symbol.upper()}")
        return {"status": "success", "symbol": symbol.upper(), "insights": data}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------

@router.get("/learning/report")
async def learning_report():
    """Full learning report — summary, symbols, signals, time patterns, recommendations."""
    db = get_db_session()
    try:
        return get_learning_report(db)
    finally:
        db.close()


@router.get("/learning/summary")
async def learning_summary():
    """High-level paper vs live P&L summary."""
    db = get_db_session()
    try:
        return get_learning_summary(db)
    finally:
        db.close()


@router.get("/learning/symbols")
async def learning_symbols():
    """Per-symbol performance with paper/live breakdown and grades."""
    db = get_db_session()
    try:
        return get_symbol_performance(db)
    finally:
        db.close()


@router.get("/learning/signals")
async def learning_signals():
    """Signal conversion rate and status breakdown."""
    db = get_db_session()
    try:
        return get_signal_analysis(db)
    finally:
        db.close()


@router.get("/learning/time-patterns")
async def learning_time_patterns():
    """Hourly win-rate and P&L patterns."""
    db = get_db_session()
    try:
        return get_time_patterns(db)
    finally:
        db.close()


@router.get("/learning/recommendations")
async def learning_recommendations():
    """Actionable trading recommendations."""
    db = get_db_session()
    try:
        return {"recommendations": get_recommendations(db)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

@router.get("/strategy/analytics")
async def strategy_analytics():
    """Comprehensive strategy analytics for optimization."""
    from src.api.routes.config import load_config
    db = get_db_session()
    try:
        config = load_config()
        return get_strategy_analytics(db, config)
    finally:
        db.close()


class StrategyApplyRequest(BaseModel):
    recommendation_idx: int


class CustomStrategyRequest(BaseModel):
    risk_percent: Optional[float] = None
    min_risk_reward: Optional[float] = None
    atr_multiplier_sl: Optional[float] = None
    atr_multiplier_tp: Optional[float] = None
    max_slippage_percent: Optional[float] = None
    trading_hours: Optional[Dict[str, Any]] = None


@router.post("/strategy/apply")
async def apply_strategy(request: StrategyApplyRequest):
    """Apply a strategy recommendation from the optimizer."""
    from src.api.routes.config import load_config, save_config

    db = get_db_session()
    try:
        config = load_config()
        trades = _load_trades_from_db(db)
        optimizer = StrategyOptimizer(trades, config)
        recommendations = optimizer.generate_strategy_recommendations()

        idx = request.recommendation_idx
        if idx < 0 or idx >= len(recommendations):
            raise HTTPException(status_code=400, detail="Invalid recommendation index")

        rec = recommendations[idx]
        if not rec.get("actionable") or not rec.get("suggested_config"):
            raise HTTPException(status_code=400, detail="Recommendation is not actionable")

        suggested = rec["suggested_config"]
        if "strategy_history" not in config:
            config["strategy_history"] = []
        config["strategy_history"].append({
            "date": datetime.now().isoformat(),
            "reason": rec["title"],
            "type": rec.get("type"),
            "new_values": suggested,
        })

        if "risk_percent" in suggested:
            config["risk_percent"] = suggested["risk_percent"]
        if "min_risk_reward" in suggested:
            config.setdefault("risk_management", {})["min_risk_reward"] = suggested["min_risk_reward"]

        save_config(config)
        return {"status": "success", "message": f"Applied: {rec['title']}", "changes": suggested, "recommendation": rec}
    finally:
        db.close()


@router.post("/strategy/custom")
async def apply_custom_strategy(settings: CustomStrategyRequest):
    """Apply custom strategy settings and save to config."""
    from src.api.routes.config import load_config, save_config

    config = load_config()
    changes = []

    if settings.risk_percent is not None:
        v = settings.risk_percent
        if 0.1 <= v <= 5.0:
            old = config.get("risk_percent", 1.0)
            config["risk_percent"] = v
            changes.append(f"Risk percent: {old}% → {v}%")

    if settings.min_risk_reward is not None:
        v = settings.min_risk_reward
        if 1.0 <= v <= 5.0:
            rm = config.setdefault("risk_management", {})
            old = rm.get("min_risk_reward", 2.0)
            rm["min_risk_reward"] = v
            changes.append(f"Min R:R: {old} → {v}")

    if settings.atr_multiplier_sl is not None:
        v = settings.atr_multiplier_sl
        if 0.5 <= v <= 3.0:
            rm = config.setdefault("risk_management", {})
            old = rm.get("atr_multiplier_sl", 1.5)
            rm["atr_multiplier_sl"] = v
            changes.append(f"SL ATR multiplier: {old}x → {v}x")

    if settings.atr_multiplier_tp is not None:
        v = settings.atr_multiplier_tp
        if 1.0 <= v <= 5.0:
            rm = config.setdefault("risk_management", {})
            old = rm.get("atr_multiplier_tp", 3.0)
            rm["atr_multiplier_tp"] = v
            changes.append(f"TP ATR multiplier: {old}x → {v}x")

    if settings.max_slippage_percent is not None:
        v = settings.max_slippage_percent
        if 0.1 <= v <= 2.0:
            sv = config.setdefault("signal_validation", {})
            old = sv.get("max_slippage_percent", 0.5)
            sv["max_slippage_percent"] = v
            changes.append(f"Max slippage: {old}% → {v}%")

    if settings.trading_hours is not None:
        config["trading_hours"] = settings.trading_hours
        changes.append("Trading hours updated")

    if changes:
        config.setdefault("strategy_history", []).append({
            "date": datetime.now().isoformat(),
            "reason": "Manual strategy adjustment",
            "type": "custom",
            "changes": changes,
        })
        save_config(config)

    return {"status": "success", "changes": changes, "message": f"Applied {len(changes)} strategy change(s)"}


@router.get("/strategy/history")
async def strategy_history():
    """History of strategy changes."""
    from src.api.routes.config import load_config

    config = load_config()
    history = config.get("strategy_history", [])
    return {
        "status": "success",
        "history": history[-20:],
        "total_changes": len(history),
        "current_config": {
            "risk_percent": config.get("risk_percent", 1.0),
            "risk_management": config.get("risk_management", {}),
            "trading_hours": config.get("trading_hours", {}),
            "signal_validation": config.get("signal_validation", {}),
        },
    }


@router.post("/strategy/reset")
async def reset_strategy():
    """Reset strategy parameters to defaults."""
    from src.api.routes.config import load_config, save_config

    config = load_config()
    old = {
        "risk_percent": config.get("risk_percent"),
        "risk_management": dict(config.get("risk_management", {})),
    }
    config["risk_percent"] = 1.0
    config["risk_management"] = {
        "atr_multiplier_sl": 1.5,
        "atr_multiplier_tp": 3.0,
        "min_risk_reward": 2.0,
        "max_sl_percent": 2.0,
    }
    config["trading_hours"] = {"start": "09:15", "end": "15:30"}
    config["signal_validation"] = {"enabled": True, "max_slippage_percent": 0.5}
    config.setdefault("strategy_history", []).append({
        "date": datetime.now().isoformat(),
        "reason": "Strategy reset to defaults",
        "type": "reset",
        "previous_config": old,
    })
    save_config(config)

    return {
        "status": "success",
        "message": "Strategy reset to default values",
        "new_config": config["risk_management"],
    }
