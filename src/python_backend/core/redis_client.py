from redis import Redis

from python_backend.core.config import settings

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)
