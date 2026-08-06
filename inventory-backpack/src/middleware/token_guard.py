import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Union
from functools import wraps
import logging

logger = logging.getLogger("token_guard")


@dataclass
class BudgetConfig:
    """Token budget configuration"""
    # Total budget limit
    max_total_tokens: int = 8192
    # Prompt budget per request
    max_prompt_tokens: int = 4096
    # Tool output budget threshold (compress when exceeded)
    tool_output_budget: int = 1024
    # Maximum number of tokens to keep after compression
    compressed_output_limit: int = 256
    # Whether to enable strict mode (reject directly when over budget)
    strict_mode: bool = False


@dataclass
class CompressionMetrics:
    """Compression metrics record"""
    original_tokens: int = 0
    compressed_tokens: int = 0
    fields_removed: List[str] = field(default_factory=list)
    compression_ratio: float = 0.0


class TokenEstimator:
    """Token estimator - precision first"""

    # Average characters per token (English ~4, Chinese ~2, use a conservative value for mixed text)
    CHARS_PER_TOKEN = 3.5

    @classmethod
    def estimate(cls, text: str) -> int:
        """Estimate the number of tokens in text"""
        if not text:
            return 0
        # Estimate by characters, round up for safety
        char_count = len(text.encode('utf-8'))
        return max(1, int(char_count / cls.CHARS_PER_TOKEN) + 1)

    @classmethod
    def estimate_json(cls, data: Any) -> int:
        """Estimate the number of tokens in JSON data"""
        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
            return cls.estimate(text)
        except Exception:
            return cls.estimate(str(data))


class OutputCompressor:
    """Tool output compressor"""

    # Critical field whitelist (to keep)
    CRITICAL_FIELDS = {
        "status", "error_code", "error", "result",
        "success", "code", "message", "data",
        "exit_code", "stdout", "stderr"
    }

    # Redundant fields that can be dropped
    REDUNDANT_PATTERNS = [
        r"timestamp", r"created_at", r"updated_at",
        r"log_", r"debug_", r"trace_",
        r"raw_", r"full_", r"verbose",
        r"_details", r"_history", r"_context"
    ]

    @classmethod
    def compress(cls, data: Any, metrics: Optional[CompressionMetrics] = None) -> Any:
        """
        Compress tool output, preserving critical information

        Strategy:
        1. Dict: keep critical fields, recursively compress values
        2. List: truncate and compress elements
        3. String: truncate and clean up
        """
        if metrics is None:
            metrics = CompressionMetrics()

        # Record original size
        original_str = json.dumps(data, ensure_ascii=False, default=str) if not isinstance(data, str) else data
        metrics.original_tokens = TokenEstimator.estimate(original_str)

        result = cls._compress_value(data, metrics)

        # Record compressed size
        compressed_str = json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result
        metrics.compressed_tokens = TokenEstimator.estimate(compressed_str)
        metrics.compression_ratio = (
            (metrics.original_tokens - metrics.compressed_tokens) / max(metrics.original_tokens, 1)
        )

        return result

    @classmethod
    def _compress_value(cls, value: Any, metrics: CompressionMetrics) -> Any:
        """Recursively compress a value"""

        if isinstance(value, dict):
            return cls._compress_dict(value, metrics)

        elif isinstance(value, list):
            # List truncation: keep the first 3 items, mark the total count
            if len(value) > 3:
                compressed = [cls._compress_value(v, metrics) for v in value[:3]]
                # Add a summary marker
                if value and isinstance(value[0], dict):
                    compressed.append({"_truncated": f"total_items={len(value)}"})
                return compressed
            return [cls._compress_value(v, metrics) for v in value]

        elif isinstance(value, str):
            return cls._compress_string(value)

        return value

    @classmethod
    def _compress_dict(cls, data: Dict, metrics: CompressionMetrics) -> Dict:
        """Compress a dict, preserving critical fields"""
        result = {}

        for key, val in data.items():
            # Check if it is a redundant field
            is_redundant = any(
                re.search(pattern, key, re.I)
                for pattern in cls.REDUNDANT_PATTERNS
            )

            if is_redundant and key not in cls.CRITICAL_FIELDS:
                metrics.fields_removed.append(key)
                continue

            # Recursively compress the value
            result[key] = cls._compress_value(val, metrics)

        # Ensure critical fields are kept at minimum
        for critical in cls.CRITICAL_FIELDS:
            if critical in data and critical not in result:
                result[critical] = cls._compress_value(data[critical], metrics)

        return result

    @classmethod
    def _compress_string(cls, text: str, max_length: int = 500) -> str:
        """Compress a string, preserving critical information"""
        if len(text) <= max_length:
            return text

        # Truncate, keeping head and tail
        head_len = max_length // 2
        tail_len = max_length // 4
        return f"{text[:head_len]}...({len(text)} chars)...{text[-tail_len:]}"


class TokenBudgetGuard:
    """
    Token budget guard - middleware core

    Usage:
        guard = TokenBudgetGuard(config=BudgetConfig())
        compressed = guard.process_tool_output(tool_result)
    """

    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self.compression_history: List[CompressionMetrics] = []

    def estimate_prompt_tokens(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_outputs: Optional[List[Dict]] = None
    ) -> int:
        """
        Estimate the number of tokens in a full prompt

        Includes:
        - System prompt
        - Conversation history
        - Tool definitions
        - Pending tool outputs
        """
        total = 0

        # Messages
        for msg in messages:
            total += TokenEstimator.estimate(msg.get("content", ""))
            total += TokenEstimator.estimate(msg.get("role", ""))

        # Tools
        if tools:
            for tool in tools:
                total += TokenEstimator.estimate_json(tool)

        # Tool outputs
        if tool_outputs:
            for output in tool_outputs:
                total += TokenEstimator.estimate_json(output)

        # Format overhead (message separators, etc.)
        total += len(messages) * 4

        return total

    def process_tool_output(
        self,
        output: Any,
        force: bool = False
    ) -> tuple[Any, Optional[CompressionMetrics]]:
        """
        Process tool output, compress when necessary

        Returns:
            (processed output, compression metrics or None)
        """
        # Estimate current size
        output_str = json.dumps(output, ensure_ascii=False, default=str) if not isinstance(output, str) else output
        estimated_tokens = TokenEstimator.estimate(output_str)

        # Check whether compression is needed
        needs_compression = (
            force or
            estimated_tokens > self.config.tool_output_budget
        )

        if not needs_compression:
            return output, None

        # Perform compression
        metrics = CompressionMetrics()
        compressed = OutputCompressor.compress(output, metrics)

        self.compression_history.append(metrics)

        logger.info(
            f"Tool output compressed: {metrics.original_tokens} -> {metrics.compressed_tokens} tokens "
            f"({metrics.compression_ratio*100:.1f}% reduction), "
            f"removed fields: {metrics.fields_removed[:5]}"
        )

        return compressed, metrics

    def check_budget(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_outputs: Optional[List[Dict]] = None
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Check whether the budget is exceeded

        Returns:
            (whether allowed, diagnostic info)
        """
        prompt_tokens = self.estimate_prompt_tokens(messages, tools, tool_outputs)

        info = {
            "prompt_tokens": prompt_tokens,
            "max_allowed": self.config.max_prompt_tokens,
            "remaining": self.config.max_prompt_tokens - prompt_tokens,
            "tool_outputs_count": len(tool_outputs) if tool_outputs else 0,
        }

        if prompt_tokens > self.config.max_prompt_tokens:
            if self.config.strict_mode:
                return False, {**info, "action": "reject"}

            # Non-strict mode: mark that compression is needed
            return True, {**info, "action": "compress", "overage": prompt_tokens - self.config.max_prompt_tokens}

        return True, {**info, "action": "allow"}

    def get_stats(self) -> Dict[str, Any]:
        """Get compression statistics"""
        if not self.compression_history:
            return {"compressions": 0}

        total_saved = sum(
            m.original_tokens - m.compressed_tokens
            for m in self.compression_history
        )

        return {
            "compressions": len(self.compression_history),
            "total_tokens_saved": total_saved,
            "avg_compression_ratio": statistics.mean(
                m.compression_ratio for m in self.compression_history
            ) if self.compression_history else 0,
            "total_fields_removed": sum(
                len(m.fields_removed) for m in self.compression_history
            )
        }


# ==================== Decorator / integration approach ====================

def with_token_guard(config: Optional[BudgetConfig] = None):
    """
    Decorator: add token budget control to a function

    Usage:
        @with_token_guard(BudgetConfig(max_prompt_tokens=2048))
        def my_tool_handler(tool_output, ...):
            ...
    """
    guard = TokenBudgetGuard(config)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check whether the tool output needs compression
            if args and isinstance(args[0], (dict, list, str)):
                compressed, metrics = guard.process_tool_output(args[0])
                # Replace the first argument
                args = (compressed,) + args[1:]

                if metrics:
                    logger.debug(f"Compressed in decorator: {metrics.compression_ratio*100:.1f}%")

            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== Agent integration example ====================

class TokenAwareAgent:
    """
    Token budget-aware Agent example

    Demonstrates how to integrate TokenBudgetGuard into an Agent
    """

    def __init__(self):
        self.guard = TokenBudgetGuard(BudgetConfig(
            max_prompt_tokens=4096,
            tool_output_budget=1024,
            compressed_output_limit=256,
            strict_mode=False  # Allow auto compression instead of rejection
        ))

    def execute_with_tools(
        self,
        user_query: str,
        tools: List[Dict],
        pending_outputs: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Execute a request with tools, automatically handling the token budget
        """
        # Build messages
        messages = [{"role": "user", "content": user_query}]

        # Check budget
        allowed, info = self.guard.check_budget(
            messages=messages,
            tools=tools,
            tool_outputs=pending_outputs
        )

        if not allowed:
            return {
                "error": "Token budget exceeded",
                "budget_info": info
            }

        # Process tool outputs (compress overly long ones)
        processed_outputs = []
        if pending_outputs:
            for output in pending_outputs:
                compressed, metrics = self.guard.process_tool_output(output)
                processed_outputs.append(compressed)

        # Call the actual LLM here ...
        # result = llm_call(messages=messages, tools=tools, tool_outputs=processed_outputs)

        return {
            "processed": True,
            "outputs_count": len(processed_outputs),
            "budget_info": info,
            "guard_stats": self.guard.get_stats()
        }


# ==================== Tests ====================

if __name__ == "__main__":
    import statistics

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Test 1: Basic compression
    print("=" * 50)
    print("Test 1: Basic Compression")

    guard = TokenBudgetGuard()

    tool_output = {
        "status": "success",
        "result": {"data": "important"},
        "timestamp": "2024-01-01T00:00:00Z",
        "created_at": "2024-01-01T00:00:00Z",
        "debug_info": "..." * 1000,
        "verbose_logs": ["log1", "log2", "log3", "log4", "log5"],
        "raw_response": "x" * 5000,
        "error_code": 0
    }

    compressed, metrics = guard.process_tool_output(tool_output)

    print(f"Original tokens: {metrics.original_tokens}")
    print(f"Compressed tokens: {metrics.compressed_tokens}")
    print(f"Compression ratio: {metrics.compression_ratio*100:.1f}%")
    print(f"Removed fields: {metrics.fields_removed}")
    print(f"Compressed output keys: {list(compressed.keys())}")

    # Test 2: Budget check
    print("\n" + "=" * 50)
    print("Test 2: Budget Check")

    guard2 = TokenBudgetGuard(BudgetConfig(
        max_prompt_tokens=100,
        tool_output_budget=50
    ))

    messages = [{"role": "user", "content": "Hello world " * 20}]

    allowed, info = guard2.check_budget(
        messages=messages,
        tool_outputs=[{"result": "x" * 1000}]
    )

    print(f"Allowed: {allowed}")
    print(f"Budget info: {json.dumps(info, indent=2)}")

    # Test 3: Agent integration
    print("\n" + "=" * 50)
    print("Test 3: Agent Integration")

    agent = TokenAwareAgent()

    result = agent.execute_with_tools(
        user_query="Analyze this data",
        tools=[{"name": "analyzer", "description": "Analyze data"}],
        pending_outputs=[tool_output]
    )

    print(f"Agent result: {json.dumps(result, indent=2, default=str)}")
