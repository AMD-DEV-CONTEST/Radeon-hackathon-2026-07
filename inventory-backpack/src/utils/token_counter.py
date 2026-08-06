"""
Token calculation - based on tiktoken, precise budgeting
"""

import logging
from typing import Optional, Union

import tiktoken

logger = logging.getLogger(__name__)


class TokenCounter:
    """
    Token counter - precision first

    Use tiktoken for precise calculation, avoid character estimation errors
    """

    # Cache encoders to avoid repeated creation
    _encoders = {}

    @classmethod
    def get_encoder(cls, model: str = "cl100k_base"):
        """Get encoder (with cache)"""
        if model not in cls._encoders:
            try:
                cls._encoders[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to generic encoding
                cls._encoders[model] = tiktoken.get_encoding("cl100k_base")

        return cls._encoders[model]

    @classmethod
    def count(cls, text: str, model: str = "cl100k_base") -> int:
        """Calculate the number of tokens in text"""
        if not text:
            return 0

        enc = cls.get_encoder(model)
        return len(enc.encode(text))

    @classmethod
    def count_messages(
        cls,
        messages: list[dict],
        model: str = "cl100k_base"
    ) -> int:
        """
        Calculate the number of tokens in a message list

        Follows OpenAI message format for calculation
        """
        enc = cls.get_encoder(model)

        total = 0
        for msg in messages:
            # Base overhead per message
            total += 4

            # role
            total += len(enc.encode(msg.get("role", "")))

            # content
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(enc.encode(content))
            elif isinstance(content, list):
                # Multimodal content
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += len(enc.encode(part["text"]))

        # Initial message overhead
        total += 2

        return total

    @classmethod
    def truncate_to_budget(
        cls,
        text: str,
        max_tokens: int,
        model: str = "cl100k_base"
    ) -> str:
        """
        Truncate to within budget - preserve complete tokens

        Note: Only use when necessary; prefer compression over truncation
        """
        enc = cls.get_encoder(model)
        tokens = enc.encode(text)

        if len(tokens) <= max_tokens:
            return text

        # Truncate and decode
        truncated = tokens[:max_tokens]
        return enc.decode(truncated)
