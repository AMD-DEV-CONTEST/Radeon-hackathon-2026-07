"""LLM inference package — vLLM client and system prompts."""

from .prompts import LLMClient, DSL_GENERATION_SYSTEM, REPORT_GENERATION_SYSTEM

__all__ = ["LLMClient", "DSL_GENERATION_SYSTEM", "REPORT_GENERATION_SYSTEM"]
