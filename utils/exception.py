"""Custom exceptions for the GraphVoice agent pipeline."""


class GraphVoiceError(Exception):
    """Base exception for all GraphVoice errors."""


class CypherGenerationError(GraphVoiceError):
    """Failed to generate a valid Cypher query."""


class DatabaseExecutionError(GraphVoiceError):
    """Failed to execute a database query."""


class InterpretationError(GraphVoiceError):
    """Failed to interpret database results."""


class ConfigError(GraphVoiceError):
    """Configuration error (missing API keys, etc.)."""
