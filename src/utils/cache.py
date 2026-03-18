"""
Caching layer with Redis or in-memory fallback.
"""
import json
import pickle
from typing import Optional, Any, Union
from datetime import datetime, timedelta
from src.utils.time_utils import ist_naive
import hashlib

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
    
    def generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from arguments."""
        key_parts = [prefix]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        raw_key = ":".join(key_parts)
        
        # Hash if too long
        if len(raw_key) > 200:
            return f"{prefix}:{hashlib.md5(raw_key.encode()).hexdigest()}"
        
        return raw_key


# Global cache instance
_cache: Optional[Cache] = None


def get_cache() -> Cache:
    """Get cache singleton."""
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


class cached:
    """Decorator for caching function results."""
    
    def __init__(self, ttl: int = 300, key_prefix: Optional[str] = None):
        self.ttl = ttl
        self.key_prefix = key_prefix
    
    def __call__(self, func):
        async def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Generate cache key
            prefix = self.key_prefix or func.__name__
            cache_key = cache.generate_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return cached_value
            
            # Call function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, self.ttl)
            
            return result
        
        return wrapper
