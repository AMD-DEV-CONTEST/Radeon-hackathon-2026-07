"""Tests for tree-sitter code parsing."""

import pytest
from pathlib import Path

from src.index.parser import CodeParser, CodeChunk


SAMPLE_CODE = b'''\
"""Module docstring."""
import os


def hello_world():
    """Print hello."""
    print("Hello, World!")


class Calculator:
    """A simple calculator."""

    def add(self, a, b):
        """Add two numbers."""
        return a + b

    def multiply(self, a, b):
        """Multiply two numbers."""
        return a * b


def fibonacci(n):
    """Compute fibonacci."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''


@pytest.fixture
def parser():
    return CodeParser()


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "sample.py"
    f.write_bytes(SAMPLE_CODE)
    return f


class TestCodeParser:
    def test_parser_available(self, parser):
        """Parser should be available if tree-sitter is installed."""
        # This test passes either way — it just documents the state
        assert isinstance(parser.available, bool)

    def test_parse_returns_chunks(self, parser, sample_file):
        chunks = parser.parse_file(sample_file)
        assert len(chunks) > 0

    def test_chunk_has_required_fields(self, parser, sample_file):
        chunks = parser.parse_file(sample_file)
        for chunk in chunks:
            assert isinstance(chunk, CodeChunk)
            assert chunk.file_path
            assert chunk.content
            assert chunk.content_hash
            assert chunk.start_line >= 1
            assert chunk.end_line >= chunk.start_line

    def test_extracts_function_names(self, parser, sample_file):
        chunks = parser.parse_file(sample_file)
        names = [c.symbol_name for c in chunks]
        assert "hello_world" in names
        assert "fibonacci" in names

    def test_extracts_class_name(self, parser, sample_file):
        chunks = parser.parse_file(sample_file)
        names = [c.symbol_name for c in chunks]
        assert "Calculator" in names

    def test_extracts_methods(self, parser, sample_file):
        chunks = parser.parse_file(sample_file)
        qualified = [c.qualified_name for c in chunks]
        assert any("Calculator" in q and "add" in q for q in qualified)
        assert any("Calculator" in q and "multiply" in q for q in qualified)

    def test_content_hash_is_consistent(self, parser, sample_file):
        chunks1 = parser.parse_file(sample_file)
        chunks2 = parser.parse_file(sample_file)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1.content_hash == c2.content_hash

    def test_get_symbols(self, parser, sample_file):
        symbols = parser.get_symbols(sample_file)
        names = [s.name for s in symbols]
        assert "hello_world" in names
        assert "Calculator" in names
        assert "fibonacci" in names

    def test_parse_empty_file(self, parser, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_bytes(b"")
        chunks = parser.parse_file(empty)
        # Should return at least one chunk (module-level)
        assert len(chunks) >= 1
