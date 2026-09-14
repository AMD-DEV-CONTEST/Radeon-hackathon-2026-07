"""Optional production object-perception integration.

This package is deliberately lightweight. CUDA/Ultralytics imports live only
inside the worker engine so importing the gateway never allocates GPU memory.
"""

from .contracts import deterministic_job_id

__all__ = ["deterministic_job_id"]
