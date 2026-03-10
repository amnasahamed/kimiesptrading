"""
Kite API Wrapper - Enhanced with proper bracket orders and position tracking
Async, lightweight wrapper for Zerodha Kite Connect
"""
import httpx
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import json


@dataclass
class KiteQuote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    change: float
    change_percent: float


@dataclass
class KiteOrder:
    order_id: str
    status: str  # SUCCESS, FAILED, PENDING, OPEN
    message: str
    variety: str
    filled_quantity: int = 0
    average_price: float = 0.0
    

@dataclass
class KiteGTT:
    gtt_id: str
    status: str
    message: str
    trigger_id: Optional[str] = None


@dataclass
class Position:
    """Track an open position with SL and TP"""
    symbol: str
    quantity: int
    entry_price: float
    entry_order_id: str
    sl_price: float
    tp_price: float
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    status: str = "OPEN"  # OPEN, CLOSED, PARTIAL
    pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None  # SL_HIT, TP_HIT, MANUAL
    partial_exits: List[Dict] = field(default_factory=list)


class KiteAPI:
    def __init__(self, api_key: str, access_token: str, base_url: str = "https://api.kite.trade"):
        self.api_key = api_key
        self.access_token = access_token
        self.base_url = base_url
        self.headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self._client: Optional[httpx.AsyncClient] = None
        self.positions: Dict[str, Position] = {}  # Track open positions
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                timeout=httpx.Timeout(10.0, connect=5.0)
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_quote(self, symbol: str) -> Optional[KiteQuote]:
        """Get live quote for a symbol."""
        if not symbol or not isinstance(symbol, str):
            return None
        
        url = f"{self.base_url}/quote"
        params = {"i": f"NSE:{symbol}"}
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, params=params)
            
            if resp.status_code == 401:
                print("Error: Unauthorized - Check your API key and access token")
                return None
            
            data = resp.json()
            
            if data.get("status") == "success" and "data" in data:
                quote_data = data["data"].get(f"NSE:{symbol}", {})
                if not quote_data:
                    return None
                    
                ohlc = quote_data.get("ohlc", {})
                
                return KiteQuote(
                    symbol=symbol,
                    ltp=float(quote_data.get("last_price", 0)),
                    open=float(ohlc.get("open", 0)),
                    high=float(ohlc.get("high", 0)),
                    low=float(ohlc.get("low", 0)),
                    close=float(ohlc.get("close", 0)),
                    volume=int(quote_data.get("volume", 0)),
                    change=float(quote_data.get("change", 0)),
                    change_percent=float(quote_data.get("change_percent", 0))
                )
        except Exception as e:
            print(f"Error fetching quote: {e}")
            return None
    
    async def get_instrument_token(self, symbol: str) -> Optional[str]:
        """Get instrument token for a symbol."""
        if not symbol or not isinstance(symbol, str):
            return None
            
        url = f"{self.base_url}/quote"
        params = {"i": f"NSE:{symbol}"}
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, params=params)
            data = resp.json()
            
            if data.get("status") == "success" and "data" in data:
                quote_data = data["data"].get(f"NSE:{symbol}", {})
                return quote_data.get("instrument_token")
            return None
        except Exception as e:
            print(f"Error fetching token: {e}")
            return None
    
    async def place_market_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        product: str = "MIS",
        tag: str = "chartink_bot"
    ) -> KiteOrder:
        """Place a market order for immediate execution."""
        if not symbol or quantity <= 0:
            return KiteOrder(
                order_id="",
                status="ERROR",
                message="Invalid symbol or quantity",
                variety="regular"
            )
        
        url = f"{self.base_url}/orders/regular"
        
        data = {
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transaction_type": transaction_type.upper(),
            "quantity": str(quantity),
            "product": product,
            "order_type": "MARKET",
            "validity": "DAY",
            "tag": tag
        }
        
        try:
            client = await self._get_client()
            resp = await client.post(url, headers=self.headers, data=data)
            result = resp.json()
            
            if result.get("status") == "success":
                order_id = result["data"].get("order_id", "")
                return KiteOrder(
                    order_id=order_id,
                    status="PENDING",  # Will be OPEN when filled
                    message=f"Market order placed: {order_id}",
                    variety="regular"
                )
            else:
                return KiteOrder(
                    order_id="",
                    status="FAILED",
                    message=result.get("message", "Unknown error"),
                    variety="regular"
                )
        except Exception as e:
            return KiteOrder(
                order_id="",
                status="ERROR",
                message=str(e),
                variety="regular"
            )
    
    async def place_limit_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        price: float,
        product: str = "MIS",
        tag: str = "chartink_bot"
    ) -> KiteOrder:
        """Place a limit order."""
        if not symbol or quantity <= 0 or price <= 0:
            return KiteOrder(
                order_id="",
                status="ERROR",
                message="Invalid parameters",
                variety="regular"
            )
        
        url = f"{self.base_url}/orders/regular"
        
        data = {
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transaction_type": transaction_type.upper(),
            "quantity": str(quantity),
            "product": product,
            "order_type": "LIMIT",
            "price": str(round(price, 2)),
            "validity": "DAY",
            "tag": tag
        }
        
        try:
            client = await self._get_client()
            resp = await client.post(url, headers=self.headers, data=data)
            result = resp.json()
            
            if result.get("status") == "success":
                order_id = result["data"].get("order_id", "")
                return KiteOrder(
                    order_id=order_id,
                    status="PENDING",
                    message=f"Limit order placed: {order_id}",
                    variety="regular"
                )
            else:
                return KiteOrder(
                    order_id="",
                    status="FAILED",
                    message=result.get("message", "Unknown error"),
                    variety="regular"
                )
        except Exception as e:
            return KiteOrder(
                order_id="",
                status="ERROR",
                message=str(e),
                variety="regular"
            )
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get detailed status of an order."""
        if not order_id:
            return {}
            
        url = f"{self.base_url}/orders"
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers)
            data = resp.json()
            
            if data.get("status") == "success":
                for order in data.get("data", []):
                    if order.get("order_id") == order_id:
                        return {
                            "order_id": order.get("order_id"),
                            "status": order.get("status"),  # OPEN, COMPLETE, REJECTED, CANCELLED
                            "filled_quantity": int(order.get("filled_quantity", 0)),
                            "pending_quantity": int(order.get("pending_quantity", 0)),
                            "average_price": float(order.get("average_price", 0)),
                            "message": order.get("status_message", "")
                        }
            return {}
        except Exception as e:
            print(f"Error fetching order status: {e}")
            return {}
    
    async def wait_for_order_fill(
        self, 
        order_id: str, 
        timeout: int = 60,
        poll_interval: float = 1.0
    ) -> Dict[str, Any]:
        """Poll order until filled or timeout."""
        start_time = datetime.now()
        
        while (datetime.now() - start_time).seconds < timeout:
            status = await self.get_order_status(order_id)
            
            if status.get("status") == "COMPLETE":
                return {
                    "filled": True,
                    "filled_quantity": status.get("filled_quantity", 0),
                    "average_price": status.get("average_price", 0),
                    "status": "COMPLETE"
                }
            elif status.get("status") in ["REJECTED", "CANCELLED"]:
                return {
                    "filled": False,
                    "status": status.get("status"),
                    "message": status.get("message", "Order failed")
                }
            
            await asyncio.sleep(poll_interval)
        
        return {"filled": False, "status": "TIMEOUT", "message": "Order not filled in time"}
    
    async def place_bracket_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        entry_price: Optional[float] = None,
        stop_loss: float = 0,
        target: float = 0,
        product: str = "MIS",
        use_market_order: bool = True  # Default to market for immediate execution
    ) -> Tuple[KiteOrder, Optional[Position]]:
        """
        Place a complete bracket order:
        1. Entry order (ALWAYS market for immediate execution)
        2. Wait for fill
        3. Place SL GTT
        4. Place TP GTT
        
        Returns: (EntryOrder, Position)
        """
        # Step 1: Place entry order - ALWAYS use market for immediate execution
        # When webhook fires, we want in NOW, not hope for a better price
        if use_market_order or not entry_price:
            # Market order - guaranteed immediate fill
            entry_order = await self.place_market_order(
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product
            )
        else:
            # Limit order only if explicitly requested
            entry_order = await self.place_limit_order(
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=entry_price,
                product=product
            )
        
        if entry_order.status in ["FAILED", "ERROR"]:
            return entry_order, None
        
        # Step 2: Wait for entry fill (up to 30 seconds)
        fill_result = await self.wait_for_order_fill(entry_order.order_id, timeout=30)
        
        if not fill_result.get("filled"):
            entry_order.status = "FAILED"
            entry_order.message = f"Entry not filled: {fill_result.get('message')}"
            return entry_order, None
        
        # Update entry order with fill details
        entry_order.filled_quantity = fill_result.get("filled_quantity", quantity)
        entry_order.average_price = fill_result.get("average_price", entry_price or 0)
        entry_order.status = "SUCCESS"
        
        actual_entry = entry_order.average_price or entry_price
        
        # Step 3: Create position object
        position = Position(
            symbol=symbol,
            quantity=entry_order.filled_quantity,
            entry_price=actual_entry,
            entry_order_id=entry_order.order_id,
            sl_price=stop_loss,
            tp_price=target
        )
        
        # Step 4: Place SL GTT
        sl_order = await self.place_sl_gtt(symbol, quantity, stop_loss, transaction_type, product)
        if sl_order.status == "SUCCESS":
            position.sl_order_id = sl_order.gtt_id
        
        # Step 5: Place TP GTT
        tp_order = await self.place_tp_gtt(symbol, quantity, target, transaction_type, product)
        if tp_order.status == "SUCCESS":
            position.tp_order_id = tp_order.gtt_id
        
        # Track position
        self.positions[symbol] = position
        
        return entry_order, position
    
    async def place_sl_gtt(
        self,
        symbol: str,
        quantity: int,
        trigger_price: float,
        entry_transaction_type: str,
        product: str = "MIS"
    ) -> KiteGTT:
        """Place Stop Loss GTT order."""
        # SL is opposite of entry
        exit_transaction = "SELL" if entry_transaction_type.upper() == "BUY" else "BUY"
        
        return await self._place_gtt(
            symbol=symbol,
            quantity=quantity,
            trigger_price=trigger_price,
            transaction_type=exit_transaction,
            product=product,
            order_type="SL-M"  # Stop Loss Market
        )
    
    async def place_tp_gtt(
        self,
        symbol: str,
        quantity: int,
        trigger_price: float,
        entry_transaction_type: str,
        product: str = "MIS"
    ) -> KiteGTT:
        """Place Target/TP GTT order."""
        # TP is opposite of entry
        exit_transaction = "SELL" if entry_transaction_type.upper() == "BUY" else "BUY"
        
        return await self._place_gtt(
            symbol=symbol,
            quantity=quantity,
            trigger_price=trigger_price,
            transaction_type=exit_transaction,
            product=product,
            order_type="LIMIT"
        )
    
    async def _place_gtt(
        self,
        symbol: str,
        quantity: int,
        trigger_price: float,
        transaction_type: str,
        product: str,
        order_type: str = "LIMIT"
    ) -> KiteGTT:
        """Place a GTT (Good Till Triggered) order."""
        if not symbol or quantity <= 0 or trigger_price <= 0:
            return KiteGTT(
                gtt_id="",
                status="ERROR",
                message="Invalid GTT parameters"
            )
        
        # Get instrument token
        token = await self.get_instrument_token(symbol)
        if not token:
            return KiteGTT(
                gtt_id="",
                status="ERROR",
                message=f"Could not get instrument token for {symbol}"
            )
        
        url = f"{self.base_url}/gtt/triggers"
        
        # Build GTT payload
        gtt_data = {
            "condition": {
                "exchange": "NSE",
                "tradingsymbol": symbol,
                "trigger_values": [round(trigger_price, 2)],
                "last_price": round(trigger_price * 0.99, 2)  # Slightly below trigger
            },
            "orders": [
                {
                    "exchange": "NSE",
                    "tradingsymbol": symbol,
                    "transaction_type": transaction_type,
                    "quantity": str(quantity),
                    "order_type": order_type,
                    "product": product,
                    "price": round(trigger_price, 2) if order_type == "LIMIT" else "0"
                }
            ],
            "type": "single"
        }
        
        try:
            client = await self._get_client()
            resp = await client.post(
                url,
                headers={**self.headers, "Content-Type": "application/json"},
                json=gtt_data
            )
            result = resp.json()
            
            if result.get("status") == "success":
                gtt_id = str(result["data"].get("trigger_id", ""))
                return KiteGTT(
                    gtt_id=gtt_id,
                    status="SUCCESS",
                    message=f"GTT placed: {gtt_id}",
                    trigger_id=gtt_id
                )
            else:
                return KiteGTT(
                    gtt_id="",
                    status="FAILED",
                    message=result.get("message", "GTT placement failed")
                )
        except Exception as e:
            return KiteGTT(
                gtt_id="",
                status="ERROR",
                message=str(e)
            )
    
    async def modify_sl_gtt(
        self,
        gtt_id: str,
        new_trigger_price: float,
        symbol: str,
        quantity: int,
        transaction_type: str,
        product: str = "MIS"
    ) -> KiteGTT:
        """Modify existing SL GTT (for trailing stop)."""
        # Delete old GTT
        await self.delete_gtt(gtt_id)
        
        # Place new GTT with updated price
        return await self.place_sl_gtt(symbol, quantity, new_trigger_price, transaction_type, product)
    
    async def delete_gtt(self, gtt_id: str) -> bool:
        """Delete a GTT order."""
        if not gtt_id:
            return False
            
        url = f"{self.base_url}/gtt/triggers/{gtt_id}"
        
        try:
            client = await self._get_client()
            resp = await client.delete(url, headers=self.headers)
            data = resp.json()
            return data.get("status") == "success"
        except Exception as e:
            print(f"Error deleting GTT: {e}")
            return False
    
    async def get_positions(self) -> Dict[str, Position]:
        """Get current open positions."""
        return self.positions
    
    async def close_position(
        self,
        symbol: str,
        reason: str = "MANUAL"
    ) -> KiteOrder:
        """Close an open position immediately."""
        position = self.positions.get(symbol)
        if not position:
            return KiteOrder(
                order_id="",
                status="ERROR",
                message="Position not found"
            )
        
        # Cancel SL and TP GTTs
        if position.sl_order_id:
            await self.delete_gtt(position.sl_order_id)
        if position.tp_order_id:
            await self.delete_gtt(position.tp_order_id)
        
        # Place market order to exit
        exit_transaction = "SELL" if position.quantity > 0 else "BUY"
        exit_order = await self.place_market_order(
            symbol=symbol,
            transaction_type=exit_transaction,
            quantity=abs(position.quantity)
        )
        
        if exit_order.status == "PENDING":
            # Wait for fill
            fill_result = await self.wait_for_order_fill(exit_order.order_id, timeout=30)
            if fill_result.get("filled"):
                position.status = "CLOSED"
                position.exit_price = fill_result.get("average_price", 0)
                position.exit_time = datetime.now()
                position.exit_reason = reason
                position.pnl = (position.exit_price - position.entry_price) * position.quantity
                
                # Remove from open positions
                del self.positions[symbol]
        
        return exit_order
    
    async def cancel_order(self, order_id: str, variety: str = "regular") -> bool:
        """Cancel an order."""
        if not order_id:
            return False
            
        url = f"{self.base_url}/orders/{variety}/{order_id}"
        
        try:
            client = await self._get_client()
            resp = await client.delete(url, headers=self.headers)
            data = resp.json()
            return data.get("status") == "success"
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False

    async def get_ohlcv_history(
        self, 
        symbol: str, 
        interval: str = "day", 
        duration: int = 15
    ) -> List[Dict[str, float]]:
        """
        Fetch OHLCV history for ATR calculation.
        
        Args:
            symbol: Trading symbol
            interval: Candle interval (day, 60minute, etc.)
            duration: Number of candles to fetch
        
        Returns:
            List of dicts with 'high', 'low', 'close' keys
        """
        if not symbol:
            return []
        
        # Get instrument token first
        token = await self.get_instrument_token(symbol)
        if not token:
            # Fallback: return empty list - caller will handle
            return []
        
        url = f"{self.base_url}/instruments/historical/{token}/{interval}"
        
        # Calculate date range
        from_date = (datetime.now() - timedelta(days=duration * 2)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        
        params = {
            "from": from_date,
            "to": to_date,
            "continuous": "0",
            "oi": "0"
        }
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, params=params)
            data = resp.json()
            
            if data.get("status") == "success" and "data" in data:
                candles = data["data"].get("candles", [])
                # candles format: [timestamp, open, high, low, close, volume]
                ohlcv = []
                for candle in candles[-duration:]:  # Take last 'duration' candles
                    if len(candle) >= 5:
                        ohlcv.append({
                            "high": float(candle[2]),
                            "low": float(candle[3]),
                            "close": float(candle[4])
                        })
                return ohlcv
            return []
        except Exception as e:
            print(f"Error fetching OHLCV: {e}")
            return []
    
    async def exchange_request_token(self, request_token: str, api_secret: str) -> Optional[str]:
        """Exchange request token for access token."""
        if not request_token or not api_secret:
            return None
            
        url = f"{self.base_url}/session/token"
        
        import hashlib
        checksum_str = self.api_key + request_token + api_secret
        checksum = hashlib.sha256(checksum_str.encode("utf-8")).hexdigest()
        
        data = {
            "api_key": self.api_key,
            "request_token": request_token,
            "checksum": checksum
        }
        
        try:
            client = await self._get_client()
            resp = await client.post(url, data=data)
            result = resp.json()
            if result.get("status") == "success":
                return result["data"].get("access_token")
            return None
        except Exception as e:
            print(f"Request error: {e}")
            return None
