"""Shared domain enums for ORM models."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    RECRUITER = "recruiter"


class Recommendation(StrEnum):
    STRONG_HIRE = "strong_hire"
    HIRE = "hire"
    NO_HIRE = "no_hire"
    MAYBE = "maybe"


class ResumeStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    FAILED = "failed"


class InterviewStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DifficultyLevel(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ASKED = "asked"
    SKIPPED = "skipped"


class TranscriptSpeaker(StrEnum):
    AGENT = "agent"
    CANDIDATE = "candidate"


class AgentLogStatus(StrEnum):
    SUCCESS = "success"
    PENDING = "pending"
    RETRY = "retry"
    ERROR = "error"
