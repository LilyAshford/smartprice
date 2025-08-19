import redis
import json
from flask import current_app
from typing import Optional, Any
import hashlib
import asyncio


class CacheManager:
    _redis_client = None

    @classmethod
    def get_client(cls):
        if cls._redis_client is None:
            try:
                redis_url = current_app.config.get('REDIS_URL')
                if not redis_url:
                    # Build URL from individual config values
                    host = current_app.config.get('REDIS_HOST', 'redis')
                    port = current_app.config.get('REDIS_PORT', 6379)
                    password = current_app.config.get('REDIS_PASSWORD')
                    db = current_app.config.get('REDIS_DB', 0)

                    if password:
                        redis_url = f"redis://:{password}@{host}:{port}/{db}"
                    else:
                        redis_url = f"redis://{host}:{port}/{db}"

                cls._redis_client = redis.from_url(redis_url, decode_responses=True)
                cls._redis_client.ping()
                current_app.logger.info("Successfully connected to Redis.")
            except Exception as e:
                current_app.logger.error(f"Redis connection failed: {e}. Caching will be disabled.")
                cls._redis_client = None
        return cls._redis_client

    @classmethod
    def get_sync(cls, key: str) -> Optional[str]:
        """Synchronous version of get for use in non-async contexts"""
        client = cls.get_client()
        if client:
            try:
                return client.get(key)
            except Exception as e:
                current_app.logger.error(f"Cache GET error for key {key}: {e}")
        return None

    @classmethod
    def set_sync(cls, key: str, value: str, ttl: int = 3600) -> bool:
        """Synchronous version of set for use in non-async contexts"""
        client = cls.get_client()
        if client:
            try:
                return client.setex(key, ttl, value)
            except Exception as e:
                current_app.logger.error(f"Cache SET error for key {key}: {e}")
        return False

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """Async version - runs sync method in executor"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cls.get_sync, key)

    @classmethod
    async def set(cls, key: str, value: str, ttl: int = 3600) -> bool:
        """Async version - runs sync method in executor"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cls.set_sync, key, value, ttl)

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete a key from cache"""
        client = cls.get_client()
        if client:
            try:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: bool(client.delete(key)))
            except Exception as e:
                current_app.logger.error(f"Cache DELETE error for key {key}: {e}")
        return False


class SearchResultsCache:
    """Cache for marketplace search results"""

    @staticmethod
    def _generate_key(marketplace: str, query: str) -> str:
        """Generate cache key for search results"""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        return f"search_results:{marketplace.lower()}:{query_hash}"

    @staticmethod
    async def get(marketplace: str, query: str) -> Optional[list]:
        """Get cached search results"""
        cache_key = SearchResultsCache._generate_key(marketplace, query)
        cached_data = await CacheManager.get(cache_key)
        if cached_data:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                current_app.logger.warning(f"Invalid JSON in cache for key {cache_key}")
                await CacheManager.delete(cache_key)
        return None

    @staticmethod
    async def save(marketplace: str, query: str, results: list, ttl: int = 86400):
        """Save search results to cache (24 hours by default)"""
        if not results:
            return False

        cache_key = SearchResultsCache._generate_key(marketplace, query)
        try:
            json_data = json.dumps(results, ensure_ascii=False)
            return await CacheManager.set(cache_key, json_data, ttl)
        except Exception as e:
            current_app.logger.error(f"Error saving search results to cache: {e}")
            return False

    @staticmethod
    async def clear_for_marketplace(marketplace: str):
        """Clear all cached results for a specific marketplace"""
        client = CacheManager.get_client()
        if client:
            try:
                pattern = f"search_results:{marketplace.lower()}:*"
                keys = client.keys(pattern)
                if keys:
                    client.delete(*keys)
                    current_app.logger.info(f"Cleared {len(keys)} cache entries for {marketplace}")
            except Exception as e:
                current_app.logger.error(f"Error clearing cache for {marketplace}: {e}")


def cached_result(key_template: str, ttl: int = 3600):
    """
    Decorator for caching results of asynchronous functions

    Args:
        key_template: Key template, e.g. "user_products:{user_id}"
        ttl: Cache lifetime in seconds
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Generate cache key by formatting template with args/kwargs
            cache_key = key_template.format(*args, **kwargs)

            # Try to get from cache first
            cached = await CacheManager.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    current_app.logger.warning(f"Invalid cached JSON for key {cache_key}")

            # Execute function if not in cache
            result = await func(*args, **kwargs)

            # Cache the result if it's not None
            if result is not None:
                try:
                    await CacheManager.set(cache_key, json.dumps(result, default=str), ttl)
                except Exception as e:
                    current_app.logger.warning(f"Failed to cache result for {cache_key}: {e}")

            return result

        return wrapper

    return decorator


# Backward compatibility functions
async def get_cached(key: str) -> Optional[str]:
    """Legacy function for backward compatibility"""
    return await CacheManager.get(key)


async def set_cached(key: str, value: str, ttl: int = 3600) -> bool:
    """Legacy function for backward compatibility"""
    return await CacheManager.set(key, value, ttl)


