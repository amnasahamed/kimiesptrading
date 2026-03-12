"""
Trading API routes.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.services.trading_service import get_trading_service
from src.services.kite_service import get_kite_service
from src.models.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api", tags=["trading"])


class TradeRequest(BaseModel):
    symbol: str
    action: str = "BUY"
    quantity: Optional[int] = None
    price: Optional[float] = None


class ClosePositionRequest(BaseModel):
    exit_price: Optional[float] = None


@router.post("/trade")
async def execute_trade(
    request: TradeRequest,
    db: Session = Depends(get_db)
):
    """Execute a trade."""
    service = get_trading_service()
    
    result = await service.process_signal(
        symbol=request.symbol,
        alert_price=request.price,
        scan_name="Manual",
        action=request.action
    )
    
    if result["status"] == "ERROR":
        raise HTTPException(status_code=500, detail=result["reason"])
    
    if result["status"] == "REJECTED":
        raise HTTPException(status_code=400, detail=result["reason"])
    
    return result


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: str,
    request: ClosePositionRequest,
    db: Session = Depends(get_db)
):
    """Close a position."""
    service = get_trading_service()
    
    result = await service.close_position(
        position_id=position_id,
        exit_price=request.exit_price
    )
    
    if result["status"] == "ERROR":
        raise HTTPException(status_code=400, detail=result["reason"])
    
    return result


@router.get("/portfolio")
async def get_portfolio(db: Session = Depends(get_db)):
    """Get portfolio summary."""
    service = get_trading_service()
    return await service.get_portfolio_summary()


@router.get("/kite/funds")
async def get_kite_funds():
    """Get Kite account funds."""
    kite = get_kite_service()
    funds = await kite.get_funds()
    
    if funds is None:
        raise HTTPException(status_code=503, detail="Could not fetch funds")
    
    return {"status": "success", "funds": funds}


@router.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a symbol."""
    kite = get_kite_service()
    quote = await kite.get_quote(symbol)
    
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not available")
    
    return {
        "symbol": quote.symbol,
        "ltp": quote.ltp,
        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "change_percent": quote.change_percent
    }
