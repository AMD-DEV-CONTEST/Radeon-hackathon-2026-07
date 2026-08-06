"""CodeRisk Agent — Core Data Models

All data flow between agents uses these models.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ─── Language & Severity ─────────────────────────────────────────

class Language(str, Enum):
    C = "c"
    PYTHON = "python"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """Risk severity, from low to high."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Confidence(str, Enum):
    """Detection confidence level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ─── Input Models ────────────────────────────────────────────────

class CodeFile(BaseModel):
    """Source code file to be analyzed."""
    path: Path
    content: str
    language: Language = Language.UNKNOWN

    @computed_field
    @property
    def hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    @computed_field
    @property
    def line_count(self) -> int:
        return self.content.count("\n") + 1

    @classmethod
    def from_path(cls, path: Path) -> CodeFile:
        content = path.read_text(encoding="utf-8", errors="replace")
        lang = _detect_language(path)
        return cls(path=path, content=content, language=lang)


class AnalysisRequest(BaseModel):
    """Analysis request."""
    files: list[CodeFile]
    rules: list[str] = Field(default_factory=lambda: ["p/default"])
    depth: int = Field(default=2, ge=1, le=5, description="Analysis depth, 1=shallow 5=deep")
    enable_ai: bool = True
    custom_rules: list[dict] = Field(default_factory=list, description="Custom detection rules loaded from JSON files")


# ─── Risk & Evidence ─────────────────────────────────────────────

class Evidence(BaseModel):
    """Single evidence — source and reasoning chain of a risk."""
    source: str = Field(description="Source: semgrep/tree-sitter/ai/manual")
    rule_id: Optional[str] = None
    snippet: str = Field(description="Relevant code snippet")
    line_start: int
    line_end: int
    reasoning: str = Field(description="Reasoning process")


class Risk(BaseModel):
    """A risk item."""
    id: str = Field(description="Unique ID, e.g. RISK-001")
    title: str
    description: str
    severity: Severity
    confidence: Confidence
    cwe_id: Optional[str] = Field(default=None, description="CWE ID, e.g. CWE-120")
    language: Language
    file_path: Path
    line_start: int
    line_end: int
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str = Field(description="Fix suggestion")

    @computed_field
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


# ─── Agent Messages ──────────────────────────────────────────────

class AgentRole(str, Enum):
    STATIC = "static_analyzer"
    SEMANTIC = "semantic_analyzer"
    PATTERN = "pattern_matcher"
    REPORTER = "report_generator"
    ORCHESTRATOR = "orchestrator"


class AgentMessage(BaseModel):
    """Inter-agent communication message."""
    sender: AgentRole
    receiver: AgentRole
    content: dict
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: str = Field(description="Correlation ID, tracking the same analysis round")


# ─── Analysis Result ─────────────────────────────────────────────

class AnalysisResult(BaseModel):
    """Complete analysis result."""
    request_id: str
    files_analyzed: int
    risks: list[Risk] = Field(default_factory=list)
    analysis_time_ms: int = 0
    model_used: str = ""
    perf_timings: dict[str, float] = Field(default_factory=dict, description="Phase timing in ms")
    timestamp: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def risk_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for risk in self.risks:
            summary[risk.severity.value] = summary.get(risk.severity.value, 0) + 1
        return summary

    @computed_field
    @property
    def total_risks(self) -> int:
        return len(self.risks)

    @computed_field
    @property
    def has_critical(self) -> bool:
        return any(r.severity == Severity.CRITICAL for r in self.risks)


# ─── LLM Configuration ──────────────────────────────────────────

class LLMBackend(str, Enum):
    LOCAL_HTTP = "local_http"          # llama-server HTTP API
    LOCAL_LLAMA_CPP = "local_llama_cpp"  # llama-cpp-python direct load


class LLMConfig(BaseModel):
    """LLM client configuration."""
    backend: LLMBackend = LLMBackend.LOCAL_LLAMA_CPP
    api_url: str = ""
    api_key: str = ""
    model: str = ""
    model_path: str = Field(default="", description="Local GGUF model path")
    n_gpu_layers: int = Field(default=999, description="GPU layers, 999=all offload")
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    timeout: int = Field(default=180, ge=5, le=600)


# ─── Utility Functions ───────────────────────────────────────────

def _detect_language(path: Path) -> Language:
    """Detect language based on file extension."""
    suffix_map = {
        ".c": Language.C,
        ".h": Language.C,
        ".py": Language.PYTHON,
    }
    return suffix_map.get(path.suffix, Language.UNKNOWN)


# ─── LLM Structured Output Schemas ──────────────────────────────

class ValidatedRisk(BaseModel):
    """LLM validation result for existing risks."""
    id: str = Field(description="Risk ID, e.g. RISK-001")
    is_true_positive: bool = Field(default=True)
    reasoning: str = Field(default="")
    attack_scenario: str = Field(default="")
    impact: str = Field(default="")
    notes: str = Field(default="")
    adjusted_severity: Optional[str] = Field(default=None)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class NewRisk(BaseModel):
    """New risk discovered by LLM."""
    title: str
    description: str = Field(default="")
    severity: str = Field(default="medium")
    cwe_id: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    attack_scenario: str = Field(default="")
    suggestion: str = Field(default="Review this code section.")


class SemanticResponse(BaseModel):
    """SemanticAnalyzer LLM output schema."""
    validated_risks: list[ValidatedRisk] = Field(default_factory=list)
    new_risks: list[NewRisk] = Field(default_factory=list)


class VerifiedRisk(BaseModel):
    """DeepVerifier risk validation result."""
    id: str
    confirmed: bool = Field(default=True)
    confidence_reason: str = Field(default="")
    false_positive_likelihood: str = Field(default="medium")


class MissedRisk(BaseModel):
    """Missed risk discovered by DeepVerifier."""
    title: str
    description: str = Field(default="")
    severity: str = Field(default="medium")
    cwe_id: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    reasoning: str = Field(default="")
    suggestion: str = Field(default="Review this code section.")


class ReflectionResponse(BaseModel):
    """DeepVerifier self-reflection loop LLM output schema."""
    verified_risks: list[VerifiedRisk] = Field(default_factory=list)
    missed_risks: list[MissedRisk] = Field(default_factory=list)
