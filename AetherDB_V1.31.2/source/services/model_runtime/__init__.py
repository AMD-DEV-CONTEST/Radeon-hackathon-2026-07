"""Hardware admission and isolated model-worker runtime services."""

from services.model_runtime.scheduler import ResourceScheduler, get_resource_scheduler

__all__ = ["ResourceScheduler", "get_resource_scheduler"]
