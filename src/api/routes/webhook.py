"""
ChartInk webhook routes.
Receives signals from ChartInk and dispatches them to the trading service.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from src.core.logging_config import get_logger
from src.models.database import get_db_session
from src.repositories.alert_repository import record_alert, update_status
from src.services.trading_service import get_trading_service

logger = get_logger()
router = APIRouter(tags=["webhook"])

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_webhook_calls: dict = defaultdict(list)
RATE_LIMIT = 20
RATE_WINDOW = 60
# Cleanup when any single IP accumulates more than this many entries
_CLEANUP_THRESHOLD = 200


def _check_rate_limit(client_ip: str) -> tuple[bool, str]:
    now = ist_naive()
    window_start = now - timedelta(seconds=RATE_WINDOW)
    _webhook_calls[client_ip] = [t for t in _webhook_calls[client_ip] if t > window_start]

    if len(_webhook_calls[client_ip]) >= RATE_LIMIT:
        oldest = min(_webhook_calls[client_ip])
        retry_after = int((oldest + timedelta(seconds=RATE_WINDOW) - now).total_seconds())
        return False, f"Rate limit exceeded. Try again in {retry_after} seconds."

    _webhook_calls[client_ip].append(now)

    if len(_webhook_calls[client_ip]) > _CLEANUP_THRESHOLD:
        _cleanup_stale_entries(window_start)

    return True, "OK"


def _cleanup_stale_entries(window_start) -> None:
    stale_ips = [
        ip for ip, timestamps in _webhook_calls.items()
        if not any(t > window_start for t in timestamps)
    ]
    for ip in stale_ips:
        del _webhook_calls[ip]


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ChartinkAlert(BaseModel):
    symbol: Optional[str] = None
    action: Optional[str] = "BUY"
    price: Optional[float] = None
    alert_name: Optional[str] = ""
    secret: Optional[str] = ""
    stocks: Optional[str] = None
    trigger_prices: Optional[str] = None
    triggered_at: Optional[str] = None
    scan_name: Optional[str] = None
    scan_url: Optional[str] = None
    webhook_url: Optional[str] = None
    volume: Optional[float] = None
    change_percent: Optional[float] = None


# ---------------------------------------------------------------------------
# Payload parser
# ---------------------------------------------------------------------------
def _parse_payload(alert: ChartinkAlert) -> List[Dict[str, Any]]:
    """Parse Chartink payload (single or multi-stock)."""
    alerts = []

    if alert.symbol and not alert.stocks:
        sym = alert.symbol.upper().strip().replace(" ", "")
        if sym and len(sym) <= 20 and sym.replace("-", "").replace("_", "").isalnum():
            alerts.append({
                "symbol": sym,
                "price": alert.price,
                "scan_name": alert.alert_name or alert.scan_name or "Chartink Alert",
            })
        return alerts

    if alert.stocks:
        raw_stocks = [s.strip().upper() for s in alert.stocks.split(",") if s.strip()]
        stocks = []
        for s in raw_stocks:
            cleaned = s.replace("-", "").replace("_", "")
            if cleaned.isalnum() and len(s) <= 20:
                stocks.append(s)

        prices: list = []
        if alert.trigger_prices:
            for p in alert.trigger_prices.split(","):
                try:
                    v = float(p.strip())
                    prices.append(v if v > 0 else None)
                except (ValueError, TypeError):
                    prices.append(None)

        for i, stock in enumerate(stocks):
            alerts.append({
                "symbol": stock,
                "price": prices[i] if i < len(prices) else None,
                "scan_name": alert.scan_name or alert.alert_name or "Chartink Scan",
            })

    return alerts


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
async def _process_alert(alert: ChartinkAlert, config: dict) -> Dict[str, Any]:
    """Process a parsed ChartInk alert and return the result."""
    # Validate secret
    expected_secret = config.get("chartink", {}).get("webhook_secret", "")
    if expected_secret and alert.secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    stock_alerts = _parse_payload(alert)
    if not stock_alerts:
        return {
            "status": "REJECTED",
            "reason": "No valid stocks in alert",
            "timestamp": ist_naive().isoformat(),
        }

    trading_service = get_trading_service()
    results = []

    for stock in stock_alerts:
        result = await trading_service.process_signal(
            symbol=stock["symbol"],
            alert_price=stock.get("price"),
            scan_name=stock.get("scan_name", ""),
            action=(alert.action or "BUY").upper(),
            config=config,
        )
        results.append(result)

    # Aggregate result
    if len(results) == 1:
        return results[0]

    executed = [r for r in results if r.get("status") == "SUCCESS"]
    rejected = [r for r in results if r.get("status") == "REJECTED"]
    if not executed:
        return {
            "status": "ALL_REJECTED",
            "reason": f"All {len(results)} stocks rejected",
            "results": results,
            "timestamp": ist_naive().isoformat(),
        }

    return {
        "status": "BATCH_PROCESSED",
        "total": len(results),
        "executed": len(executed),
        "rejected": len(rejected),
        "results": results,
        "timestamp": ist_naive().isoformat(),
    }


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------
async def _handle_webhook(
    alert: ChartinkAlert,
    request: Request,
    alert_type: str,
    symbols: List[str],
    raw_payload: dict,
) -> Dict[str, Any]:
    """Common handler for all three webhook variants."""
    ip = _client_ip(request)

    allowed, msg = _check_rate_limit(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=msg)

    headers = {
        "user-agent": request.headers.get("user-agent", ""),
        "content-type": request.headers.get("content-type", ""),
    }

    db = get_db_session()
    try:
        db_alert = await record_alert(
            db=db,
            alert_type=alert_type,
            raw_payload={**raw_payload, "secret": "***" if raw_payload.get("secret") else None},
            source_ip=ip,
            headers=headers,
            symbols=symbols,
        )
        alert_id = db_alert.id
    finally:
        db.close()

    from src.api.routes.config import load_config
    config = load_config()

    start = ist_naive()
    try:
        result = await _process_alert(alert, config)

        if result.get("status") in ("SUCCESS", "BATCH_PROCESSED"):
            status = "processed"
        elif result.get("status") == "ALL_REJECTED":
            status = "rejected"
        elif result.get("status") == "REJECTED":
            status = "rejected"
        else:
            status = "error"

        latency_ms = (ist_naive() - start).total_seconds() * 1000
        db = get_db_session()
        try:
            await update_status(db, alert_id, status,
                                result.get("reason") or result.get("message"),
                                round(latency_ms, 2))
        finally:
            db.close()

        return result

    except HTTPException as he:
        latency_ms = (ist_naive() - start).total_seconds() * 1000
        db = get_db_session()
        try:
            await update_status(db, alert_id, "error",
                                f"HTTP {he.status_code}: {he.detail}", round(latency_ms, 2))
        finally:
            db.close()
        raise

    except Exception as e:
        latency_ms = (ist_naive() - start).total_seconds() * 1000
        db = get_db_session()
        try:
            await update_status(db, alert_id, "error", str(e), round(latency_ms, 2))
        finally:
            db.close()
        raise


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/webhook/chartink")
async def chartink_webhook_json(
    alert: ChartinkAlert,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Main webhook endpoint — JSON payload (standard ChartInk format)."""
    # ChartInk sometimes sends secret in query string
    if not alert.secret:
        qs = request.query_params.get("secret")
        if qs:
            alert.secret = qs

    symbols: list = []
    if alert.stocks:
        symbols = [s.strip().upper() for s in alert.stocks.split(",") if s.strip()]
    elif alert.symbol:
        symbols = [alert.symbol.upper()]

    raw = {
        "symbol": alert.symbol,
        "action": alert.action,
        "price": alert.price,
        "alert_name": alert.alert_name,
        "secret": alert.secret,
        "stocks": alert.stocks,
        "trigger_prices": alert.trigger_prices,
        "triggered_at": alert.triggered_at,
        "scan_name": alert.scan_name,
        "scan_url": alert.scan_url,
    }

    return await _handle_webhook(alert, request, "json", symbols, raw)


@router.post("/webhook/chartink/form")
async def chartink_webhook_form(request: Request):
    """Form-data webhook endpoint — ChartInk sometimes sends form-encoded data."""
    form = await request.form()
    form_data = dict(form)

    secret = form_data.get("secret") or request.query_params.get("secret") or ""
    symbol = form_data.get("symbol", "")
    stocks_str = form_data.get("stocks", "")
    trigger_prices = form_data.get("trigger_prices", "")
    scan_name = form_data.get("scan_name") or form_data.get("alert_name") or "Chartink Form Alert"

    symbols: list = []
    if stocks_str:
        symbols = [s.strip().upper() for s in stocks_str.split(",") if s.strip()]
    elif symbol:
        symbols = [symbol.upper()]

    try:
        price = float(form_data.get("price", 0)) or None
    except (ValueError, TypeError):
        price = None

    alert = ChartinkAlert(
        symbol=symbol or None,
        action=(form_data.get("action") or "BUY").upper(),
        price=price,
        alert_name=form_data.get("alert_name", ""),
        secret=secret,
        stocks=stocks_str or None,
        trigger_prices=trigger_prices or None,
        triggered_at=form_data.get("triggered_at"),
        scan_name=scan_name,
        scan_url=form_data.get("scan_url"),
        webhook_url=form_data.get("webhook_url"),
    )

    raw = dict(form_data)
    return await _handle_webhook(alert, request, "form", symbols, raw)


@router.get("/webhook/chartink")
async def chartink_webhook_status(request: Request):
    """Return webhook endpoint status (used by ChartInk to verify connectivity)."""
    return {
        "status": "active",
        "endpoint": "/webhook/chartink",
        "methods": ["POST", "GET"],
        "timestamp": ist_naive().isoformat(),
        "message": "ChartInk webhook active. Use POST to send signals.",
    }
