"""
Tests for Tier 2 GBNF grammar validity and JSON parsing fallbacks.
"""

import pytest
from warden.tiers.tier2_llm import Tier2LLM
from warden.config import ModelConfig


def test_gbnf_grammar_syntax_injection():
    """Verify injection GBNF grammar string compiles cleanly via LlamaGrammar."""
    llama_cpp = pytest.importorskip("llama_cpp", reason="llama-cpp-python not installed locally")
    
    grammar_str = r"""root ::= "{" ws "\"is_injection\"" ws ":" ws boolean ws "," ws "\"confidence\"" ws ":" ws number ws "," ws "\"evidence\"" ws ":" ws string ws "}"
boolean ::= "true" | "false"
ws ::= [ \t\n]*
number ::= [0-9]+ ("." [0-9]+)?
string ::= "\"" ( [^"\\] | "\\" . )* "\""
"""

    # If this syntax is wrong, from_string raises an exception
    grammar = llama_cpp.LlamaGrammar.from_string(grammar_str)
    assert grammar is not None


def test_gbnf_grammar_syntax_code():
    """Verify code vulnerabilities array GBNF grammar string compiles cleanly."""
    llama_cpp = pytest.importorskip("llama_cpp", reason="llama-cpp-python not installed locally")
    
    grammar_str = r"""root ::= "{" ws "\"vulnerabilities\"" ws ":" ws "[" ws vulns ws "]" ws "}"
vulns ::= (vuln (ws "," ws vuln)*)?
vuln ::= "{" ws "\"type\"" ws ":" ws string ws "," ws "\"severity\"" ws ":" ws severity ws "," ws "\"line\"" ws ":" ws number ws "," ws "\"explanation\"" ws ":" ws string ws "}"
severity ::= "\"critical\"" | "\"high\"" | "\"medium\"" | "\"low\""
ws ::= [ \t\n]*
string ::= "\"" ( [^"\\] | "\\" . )* "\""
number ::= [0-9]+
"""

    grammar = llama_cpp.LlamaGrammar.from_string(grammar_str)
    assert grammar is not None


def test_tier2_parse_injection_response():
    tier2 = Tier2LLM()
    # Test valid JSON with integer number and escaped quotes
    raw = '{"is_injection": true, "confidence": 1, "evidence": "Found \\"ignore instructions\\" command"}'
    parsed = tier2._parse_injection_response(raw)
    assert parsed["is_injection"] is True
    assert parsed["confidence"] == 1


def test_tier2_parse_code_response_empty():
    tier2 = Tier2LLM()
    raw = '{"vulnerabilities": []}'
    parsed = tier2._parse_code_response(raw)
    assert parsed == []


def test_tier2_parse_code_response_finding():
    tier2 = Tier2LLM()
    raw = '{"vulnerabilities": [{"type": "sql_injection", "severity": "critical", "line": 42, "explanation": "Unsanitized input"}]}'
    parsed = tier2._parse_code_response(raw)
    assert len(parsed) == 1
    assert parsed[0]["line"] == 42
