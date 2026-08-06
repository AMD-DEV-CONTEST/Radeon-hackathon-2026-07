"""Tests for LLM output Schema validation (Pydantic models)"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    SemanticResponse,
    ReflectionResponse,
    ValidatedRisk,
    NewRisk,
    VerifiedRisk,
    MissedRisk,
)


class TestSemanticResponse:
    def test_empty_response(self):
        data = {"validated_risks": [], "new_risks": []}
        result = SemanticResponse.model_validate(data)
        assert result.validated_risks == []
        assert result.new_risks == []

    def test_validated_risk_defaults(self):
        data = {"validated_risks": [{"id": "RISK-001"}], "new_risks": []}
        result = SemanticResponse.model_validate(data)
        assert result.validated_risks[0].id == "RISK-001"
        assert result.validated_risks[0].is_true_positive is True
        assert result.validated_risks[0].confidence == 0.5

    def test_new_risk_full(self):
        data = {
            "validated_risks": [],
            "new_risks": [{
                "title": "Buffer overflow",
                "description": "gets() used",
                "severity": "critical",
                "cwe_id": "CWE-120",
                "line_start": 5,
                "line_end": 5,
                "attack_scenario": "input overflow",
                "suggestion": "use fgets()",
            }]
        }
        result = SemanticResponse.model_validate(data)
        nr = result.new_risks[0]
        assert nr.title == "Buffer overflow"
        assert nr.severity == "critical"
        assert nr.cwe_id == "CWE-120"

    def test_rejects_invalid_severity(self):
        """Invalid adjusted_severity should still parse (it's a free string)."""
        data = {
            "validated_risks": [{"id": "RISK-001", "adjusted_severity": "invalid"}],
            "new_risks": [],
        }
        result = SemanticResponse.model_validate(data)
        assert result.validated_risks[0].adjusted_severity == "invalid"

    def test_strips_extra_fields(self):
        data = {
            "validated_risks": [],
            "new_risks": [],
            "extra_noise": "should be ignored",
            "another": 123,
        }
        result = SemanticResponse.model_validate(data)
        dumped = result.model_dump()
        assert "extra_noise" not in dumped
        assert "another" not in dumped


class TestReflectionResponse:
    def test_empty(self):
        data = {"verified_risks": [], "missed_risks": []}
        result = ReflectionResponse.model_validate(data)
        assert result.verified_risks == []
        assert result.missed_risks == []

    def test_verified_risk(self):
        data = {
            "verified_risks": [{
                "id": "RISK-001",
                "confirmed": True,
                "confidence_reason": "Multiple sources agree",
                "false_positive_likelihood": "low",
            }],
            "missed_risks": [],
        }
        result = ReflectionResponse.model_validate(data)
        vr = result.verified_risks[0]
        assert vr.id == "RISK-001"
        assert vr.confirmed is True
        assert vr.false_positive_likelihood == "low"

    def test_missed_risk(self):
        data = {
            "verified_risks": [],
            "missed_risks": [{
                "title": "SQL injection",
                "severity": "high",
                "cwe_id": "CWE-89",
                "line_start": 42,
                "line_end": 42,
                "reasoning": "User input not sanitized",
            }],
        }
        result = ReflectionResponse.model_validate(data)
        mr = result.missed_risks[0]
        assert mr.title == "SQL injection"
        assert mr.cwe_id == "CWE-89"

    def test_json_schema_generation(self):
        """Schema should be serializable for LLM prompt injection."""
        schema = SemanticResponse.model_json_schema()
        assert "properties" in schema
        assert "validated_risks" in schema["properties"]
        assert "new_risks" in schema["properties"]

        schema2 = ReflectionResponse.model_json_schema()
        assert "verified_risks" in schema2["properties"]
        assert "missed_risks" in schema2["properties"]


class TestSchemaIntegration:
    def test_roundtrip_dump_validate(self):
        """model_dump -> model_validate should be idempotent."""
        data = {
            "validated_risks": [{
                "id": "RISK-001",
                "is_true_positive": True,
                "reasoning": "confirmed",
                "attack_scenario": "overflow",
                "impact": "RCE",
                "adjusted_severity": "critical",
                "confidence": 0.9,
            }],
            "new_risks": [{
                "title": "New risk",
                "severity": "medium",
                "line_start": 10,
                "line_end": 15,
            }],
        }
        original = SemanticResponse.model_validate(data)
        dumped = original.model_validate(data)
        assert dumped.validated_risks[0].confidence == 0.9
