"""
Caching layer with Redis or in-memory fallback.
"""
import json
from typing import Optional, Any
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive

from src.core.config import get_settings
from src.core.logging_config import get_logger

logger = get_logger()

# Try to import redis, fallback to in-memory if not available
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class Cache:
    """Cache manager with Redis or in-memory fallback."""
    
    def __init__(self):
        self.settings = get_settings()
        self._redis: Optional[Any] = None
        self._memory_cache: dict = {}
        self._memory_ttl: dict = {}
        self._use_redis = False
        
        if REDIS_AVAILABLE and self.settings.redis_url:
            try:
                self._redis = aioredis.from_url(
                    self.settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                self._use_redis = True
                logger.info("Redis cache initialized")
            except Exception as e:
                logger.warning(f"Redis not available, using in-memory cache: {e}")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            if self._use_redis and self._redis:
                value = await self._redis.get(key)
                if value:
                    return json.loads(value)
            else:
                # In-memory cache
                if key in self._memory_cache:
                    expiry = self._memory_ttl.get(key)
                    if expiry and ist_naive() > expiry:
                        del self._memory_cache[key]
                        del self._memory_ttl[key]
                        return None
                    return self._memory_cache[key]
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        
        return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: int = 300  # 5 minutes default
    ) -> bool:
        """Set value in cache."""
        try:
            if self._use_redis and self._redis:
                await self._redis.setex(
                    key, 
                    ttl, 
                    json.dumps(value, default=str)
                )
            else:
                # In-memory cache
                self._memory_cache[key] = value
                self._memory_ttl[key] = ist_naive() + timedelta(seconds=ttl)
            
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        try:
            if self._use_redis and self._redis:
                await self._redis.delete(key)
            else:
                self._memory_cache.pop(key, None)
                self._memory_ttl.pop(key, None)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def clear_pattern(self, pattern: str) -> bool:
        """Clear cache keys matching pattern."""
        try:
            if self._use_redis and self._redis:
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
            else:
                # In-memory: check all keys
                keys_to_delete = [
                    k for k in self._memory_cache.keys() 
                    if pattern.replace("*", "") in k
                ]
                for k in keys_to_delete:
                    del self._memory_cache[k]
                    self._memory_ttl.pop(k, None)
            return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False


# Global cache instance
_cache: Optional[Cache] = None


def get_cache() -> Cache:
    """Get cache singleton."""
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
