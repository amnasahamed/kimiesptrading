"""
Enhanced Kite API service with circuit breaker and caching.
"""
import asyncio
import json
import httpx
from typing import Optional, Dict, Any
from datetime import datetime
from src.utils.time_utils import ist_naive

from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.utils.circuit_breaker import circuit_breaker, CircuitBreakerOpen
from src.utils.cache import get_cache

logger = get_logger()


class KiteQuote:
    """Quote data class."""
    def __init__(self, data: Dict[str, Any]) -> None:
        self.symbol = data.get("symbol", "")
        self.ltp = float(data.get("last_price", 0))
        self.open = float(data.get("ohlc", {}).get("open", 0))
        self.high = float(data.get("ohlc", {}).get("high", 0))
        self.low = float(data.get("ohlc", {}).get("low", 0))
        self.close = float(data.get("ohlc", {}).get("close", 0))
        self.volume = int(data.get("volume", 0))
        self.change = float(data.get("change", 0))
        self.change_percent = float(data.get("change_percent", 0))
        self.timestamp = ist_naive()


class KiteService:
    """Kite API service with resilience patterns."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.kite_base_url
        self._client: Optional[httpx.AsyncClient] = None
        self.cache = get_cache()
        self._reload_headers()

    def _reload_headers(self) -> None:
        """Reload headers from config.json (supports runtime token updates)."""
        from src.api.routes.config import load_config
        cfg = load_config()
        kite_cfg = cfg.get("kite", {})
        api_key = kite_cfg.get("api_key") or self.settings.kite_api_key
        access_token = kite_cfg.get("access_token") or self.settings.kite_access_token
        self.headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_keepalive_connections=10, 
                    max_connections=20
                ),
                timeout=httpx.Timeout(10.0, connect=5.0)
            )
        return self._client
    
    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    @circuit_breaker("kite_quote")
    async def get_quote(self, symbol: str) -> Optional[KiteQuote]:
        """
        Get live quote for a symbol with caching and circuit breaker.
        """
        if not symbol or not isinstance(symbol, str):
            return None
        
        # Check cache first
        cache_key = f"quote:{symbol.upper()}"
        cached_data = await self.cache.get(cache_key)
        
        if cached_data:
            logger.debug(f"Quote cache hit: {symbol}")
            return KiteQuote(cached_data)
        
        # Fetch from API
        url = f"{self.base_url}/quote"
        params = {"i": f"NSE:{symbol}"}
        
        try:
            client = await self._get_client()
            resp = await client.get(
                url, 
                headers=self.headers, 
                params=params,
                timeout=5.0
            )
            
            if resp.status_code == 401:
                logger.error("Kite API unauthorized - check credentials")
                return None
            
            data = resp.json()
            
            if data.get("status") == "success" and "data" in data:
                quote_data = data["data"].get(f"NSE:{symbol}", {})
                if quote_data:
                    quote_data["symbol"] = symbol
                    
                    # Cache for 5 seconds (quotes change frequently)
                    await self.cache.set(cache_key, quote_data, ttl=5)
                    
                    return KiteQuote(quote_data)
                    
        except CircuitBreakerOpen:
            logger.warning(f"Circuit breaker open for Kite API - using cached/stale data")
            # Return cached data even if stale
            if cached_data:
                return KiteQuote(cached_data)
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
        
        return None
    
    @circuit_breaker("kite_funds")
    async def get_funds(self) -> Optional[Dict[str, float]]:
        """Get available funds and margins."""
        url = f"{self.base_url}/user/margins"
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, timeout=5.0)
            
            if resp.status_code == 401:
                logger.error("Kite API unauthorized")
                return None
            
            data = resp.json()
            
            if data.get("status") == "success" and "data" in data:
                equity = data["data"].get("equity", {})
                return {
                    "available_cash": float(equity.get("available", {}).get("cash", 0)),
                    "available_intraday": float(equity.get("available", {}).get("intraday_payin", 0)),
                    "utilized": float(equity.get("utilised", {}).get("debits", 0)),
                    "exposure": float(equity.get("utilised", {}).get("exposure", 0)),
                    "span": float(equity.get("utilised", {}).get("span", 0)),
                    "net_available": float(equity.get("net", 0))
                }
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
        
        return None
    
    @circuit_breaker("kite_positions")
    async def get_positions(self) -> list:
        """Get current positions from Kite."""
        url = f"{self.base_url}/portfolio/positions"
        
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("data", {}).get("net", [])
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
        
        return []
    
    async def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0,
        product: str = "MIS"
    ) -> Dict[str, Any]:
        """Place an order with retry logic."""
        url = f"{self.base_url}/orders/regular"
        
        data = {
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "validity": "DAY"
        }
        
        if order_type != "MARKET" and price > 0:
            data["price"] = price
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                resp = await client.post(
                    url,
                    headers=self.headers,
                    data=data,
                    timeout=10.0
                )
                
                result = resp.json()
                
                if result.get("status") == "success":
                    order_id = result.get("data", {}).get("order_id")
                    
                    # Try to get the filled/average price
                    avg_price = None
                    try:
                        # Fetch order details to get fill price
                        order_details = await self._get_order_details(order_id)
                        if order_details:
                            avg_price = order_details.get("average_price")
                    except Exception as e:
                        logger.warning(f"Could not fetch fill price for order {order_id}: {e}")
                    
                    return {
                        "status": "SUCCESS",
                        "order_id": order_id,
                        "average_price": avg_price,
                        "message": "Order placed successfully"
                    }
                else:
                    error_msg = result.get("message", "Unknown error")
                    logger.error(f"Order failed: {error_msg}")
                    
                    # Don't retry on certain errors
                    if "insufficient funds" in error_msg.lower():
                        return {
                            "status": "FAILED",
                            "message": error_msg
                        }
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    
                    return {
                        "status": "FAILED",
                        "message": error_msg
                    }
                    
            except Exception as e:
                logger.error(f"Order error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                
                return {
                    "status": "ERROR",
                    "message": str(e)
                }
        
        return {
            "status": "FAILED",
            "message": "Max retries exceeded"
        }

    async def _get_order_details(self, order_id: str) -> Optional[Dict]:
        """Get order details to find filled price."""
        try:
            url = f"{self.base_url}/orders/{order_id}"
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"Error fetching order details for {order_id}: {e}")
        return None

    async def list_gtt_orders(self) -> list:
        """List all GTT orders from Kite."""
        url = f"{self.base_url}/gtt/triggers"
        try:
            client = await self._get_client()
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("data", [])
        except Exception as e:
            logger.error(f"Error fetching GTT orders: {e}")
        return []

    async def delete_gtt(self, gtt_id: str) -> bool:
        """Delete/cancel a GTT order."""
        url = f"{self.base_url}/gtt/triggers/{gtt_id}"
        try:
            client = await self._get_client()
            resp = await client.delete(url, headers=self.headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status") == "success"
        except Exception as e:
            logger.error(f"Error deleting GTT {gtt_id}: {e}")
        return False

    async def place_sl_gtt(
        self, symbol: str, quantity: int, trigger_price: float, limit_price: float,
        product: str = "MIS", side: str = "BUY"
    ) -> Optional[Dict]:
        """Place a Stop-Loss GTT order.

        Args:
            symbol: Trading symbol
            quantity: Number of shares
            trigger_price: Price at which GTT triggers
            limit_price: Limit price for the triggered order
            product: "MIS" for intraday, "CNC" for delivery.
            side: "BUY" for LONG positions (GTT closes LONG by selling),
                  "SELL" for SHORT positions (GTT closes SHORT by buying).
        """
        # transaction_type is the CLOSING transaction — opposite of entry
        # LONG entry (BUY) → close with SELL
        # SHORT entry (SELL) → close with BUY
        transaction_type = "SELL" if side.upper() == "BUY" else "BUY"
        url = f"{self.base_url}/gtt/triggers"
        payload = {
            "type": "single",
            "condition": {
                "exchange": "NSE",
                "tradingsymbol": symbol,
                "trigger_values": [trigger_price],
                "last_price": trigger_price,
            },
            "orders": [{
                "exchange": "NSE",
                "tradingsymbol": symbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": "LIMIT",
                "product": product,
                "price": limit_price,
            }],
        }
        try:
            client = await self._get_client()
            resp = await client.post(
                url, headers=self.headers, content=json.dumps(payload), timeout=10.0
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return {"gtt_id": str(data["data"]["trigger_id"])}
        except Exception as e:
            logger.error(f"Error placing SL GTT for {symbol}: {e}")
        return None

    @circuit_breaker("kite_historical")
    async def get_historical_data(
        self,
        symbol: str,
        interval: str,
        duration: int = 30,
    ) -> list:
        """
        Get historical candle data for a symbol.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            interval: Kite interval (minute, 5minute, 15minute, 30minute, 60minute, day)
            duration: Number of candles to fetch (e.g., 30 for last 30 candles)

        Returns:
            List of candle dicts with open, high, low, close, volume, timestamp
        """
        from datetime import datetime, timedelta

        now = ist_naive()
        interval_map = {
            "minute": timedelta(minutes=1),
            "5minute": timedelta(minutes=5),
            "15minute": timedelta(minutes=15),
            "30minute": timedelta(minutes=30),
            "60minute": timedelta(hours=1),
            "day": timedelta(days=1),
        }
        delta = interval_map.get(interval, timedelta(minutes=5))
        from_time = now - (delta * duration)
        from_str = from_time.strftime("%Y-%m-%d %H:%M:%S")
        to_str = now.strftime("%Y-%m-%d %H:%M:%S")

        url = f"{self.base_url}/GetHistoricalData"
        params = {
            "symbol": f"NSE:{symbol}",
            "token": "",
            "exchange": "NSE",
            "interval": interval,
            "from": from_str,
            "to": to_str,
            "period": duration,
        }

        try:
            client = await self._get_client()
            resp = await client.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15.0,
            )

            if resp.status_code == 401:
                logger.error("Kite API unauthorized - check credentials")
                return []
            if resp.status_code != 200:
                logger.error(f"Kite historical data error: {resp.status_code}")
                return []

            data = resp.json()
            if data.get("status") == "success" and "data" in data:
                candles = data["data"].get("candles", [])
                return [
                    {
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]) if len(c) > 5 else 0,
                        "timestamp": c[0] if len(c) > 0 else None,
                    }
                    for c in candles
                ]
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")

        return []

    async def exchange_request_token(
        self,
        request_token: str,
        api_key: str,
        api_secret: str,
    ) -> Optional[str]:
        """Exchange a request_token for a long-lived access_token."""
        if not request_token or not api_secret:
            return None
        import hashlib
        checksum = hashlib.sha256(
            (api_key + request_token + api_secret).encode("utf-8")
        ).hexdigest()
        url = f"{self.base_url}/session/token"
        data = {
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum,
        }
        try:
            client = await self._get_client()
            resp = await client.post(url, data=data)
            result = resp.json()
            if result.get("status") == "success":
                return result["data"].get("access_token")
        except Exception as e:
            logger.error(f"Token exchange error: {e}")
        return None


# Global service instance
_kite_service: Optional[KiteService] = None


def get_kite_service() -> KiteService:
    """Get Kite service singleton."""
    global _kite_service
    if _kite_service is None:
        _kite_service = KiteService()
    return _kite_service


def reset_kite_service():
    """Discard the singleton so the next call to get_kite_service() creates a fresh instance."""
    global _kite_service
    if _kite_service is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_kite_service.close())
            else:
                loop.run_until_complete(_kite_service.close())
        except Exception:
            pass
        _kite_service = None
