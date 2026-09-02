"""External integration stubs for future infrastructure.

These modules intentionally provide no-op / disabled implementations so the
application compiles and runs without Redis, Celery, OpenAI, AMD, or LangSmith.
"""

from integrations.amd import AMDClient, get_amd_client
from integrations.celery_app import get_celery_app
from integrations.langsmith import LangSmithTracer, get_langsmith_tracer
from integrations.openai_provider import OpenAIProvider, get_openai_provider
from integrations.redis import RedisClient, get_redis_client

__all__ = [
    "AMDClient",
    "LangSmithTracer",
    "OpenAIProvider",
    "RedisClient",
    "get_amd_client",
    "get_celery_app",
    "get_langsmith_tracer",
    "get_openai_provider",
    "get_redis_client",
]
