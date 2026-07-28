from core.rag.structural_extract import extract_structure


def test_python_functions_and_classes():
    text = """
import os
from typing import Dict

class Foo:
    def bar(self):
        pass

def top_level():
    pass
"""
    result = extract_structure("mod.py", text)
    assert "Foo" in result["classes"]
    assert "bar" in result["functions"]
    assert "top_level" in result["functions"]
    assert any("import os" in i for i in result["imports"])


def test_dart_classes():
    text = """
class ChatSessionsNotifier extends StateNotifier<ChatSessionsState> {
  Future<void> sendMessage(String text) async {}
}
"""
    result = extract_structure("provider.dart", text)
    assert "ChatSessionsNotifier" in result["classes"]


def test_garbage_input_never_crashes():
    result = extract_structure("weird.bin", "\x00\x01\x02binary garbage\xff")
    assert result["functions"] == []
    assert result["classes"] == []


def test_empty_file():
    result = extract_structure("empty.py", "")
    assert result["line_count"] == 1
    assert result["functions"] == []


def test_unknown_extension_falls_back_gracefully():
    result = extract_structure("data.xyz", "some content\nmore content\n")
    assert result["functions"] == []
    assert result["classes"] == []
    assert result["line_count"] == 3
