import pytest
import os
from unittest.mock import MagicMock, patch
from src.tools import (
    ToolRegistry,
    file_read,
    file_write,
    file_list,
    file_search,
    email_draft,
    calendar_query,
    web_search,
)


@pytest.fixture
def registry():
    return ToolRegistry()


def test_registry_register(registry):
    """registered tool appears in list_tools()"""
    def mock_tool(x: str): pass
    registry.register("mock_tool", mock_tool, "description", {"x": {"type": "string"}}, False)
    tools = registry.list_tools()
    assert "mock_tool" in [t["name"] for t in tools]


def test_registry_execute_no_permission(registry):
    """tool without requires_permission executes immediately returning envelope dict"""
    def my_tool(x): return x * 2
    registry.register("my_tool", my_tool, "desc", {"x": {"type": "integer"}}, False)
    result = registry.execute("my_tool", {"x": 2})
    assert result == {"success": True, "result": 4, "tool": "my_tool"}


def test_registry_execute_with_permission(registry):
    """tool with requires_permission calls permission_controller"""
    def secret_tool(): return "secret"
    registry.register("secret_tool", secret_tool, "desc", {}, True)

    perm_ctrl = MagicMock()
    perm_ctrl.request_approval.return_value = True
    registry.permission_controller = perm_ctrl

    result = registry.execute("secret_tool", {})
    assert result == {"success": True, "result": "secret", "tool": "secret_tool"}
    perm_ctrl.request_approval.assert_called_once()


def test_registry_execute_unknown_tool(registry):
    """returns error dict for unknown tool name"""
    result = registry.execute("invalid_tool", {})
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "not found" in result["error"]


def test_registry_rejects_missing_required_params(registry):
    """tool registry rejects missing required params"""
    called = False
    def req_tool(path: str):
        nonlocal called
        called = True
        return "ok"

    registry.register("req_tool", req_tool, "desc", {
        "path": {"type": "string", "required": True}
    })
    result = registry.execute("req_tool", {})
    assert result["success"] is False
    assert "Invalid parameters for req_tool" in result["error"]
    assert result["tool"] == "req_tool"
    assert called is False


def test_registry_rejects_unknown_additional_params(registry):
    """tool registry rejects unknown/additional params"""
    called = False
    def strict_tool(path: str):
        nonlocal called
        called = True
        return "ok"

    registry.register("strict_tool", strict_tool, "desc", {
        "path": {"type": "string"}
    })
    result = registry.execute("strict_tool", {"path": "a.txt", "extra_param": 123})
    assert result["success"] is False
    assert "Invalid parameters for strict_tool" in result["error"]
    assert result["tool"] == "strict_tool"
    assert called is False


def test_registry_descriptions_text(registry):
    """get_descriptions_text() returns non-empty string"""
    registry.register("tool1", lambda: None, "Description 1", {}, False)
    text = registry.get_descriptions_text()
    assert isinstance(text, str)
    assert "tool1" in text
    assert "Description 1" in text


def test_file_read_valid(tmp_path):
    """reads existing file correctly"""
    f = tmp_path / "test.txt"
    f.write_text("content")
    assert file_read("test.txt", base_dir=str(tmp_path)) == "content"


def test_file_read_path_traversal(tmp_path):
    """rejects path traversal attempts (../../etc/passwd)"""
    with pytest.raises(PermissionError):
        file_read("../../etc/passwd", base_dir=str(tmp_path))


def test_file_read_sibling_prefix_bypass(tmp_path):
    """rejects a sibling dir whose name shares the base dir name prefix"""
    base = tmp_path / "data"
    base.mkdir()
    (base / "safe.txt").write_text("safe")
    sibling = tmp_path / "data_secret"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret")
    with pytest.raises(PermissionError):
        file_read("../data_secret/secret.txt", base_dir=str(base))


def test_file_read_absolute_path_rejected(tmp_path):
    """rejects an absolute path outside base_dir"""
    base = tmp_path / "data"
    base.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    with pytest.raises(PermissionError):
        file_read(str(secret), base_dir=str(base))


def test_file_write_traversal_rejected(tmp_path):
    """file_write rejects path traversal escapes"""
    base = tmp_path / "data"
    base.mkdir()
    with pytest.raises(PermissionError):
        file_write("../escaped.txt", "content", base_dir=str(base))
    assert not (tmp_path / "escaped.txt").exists()


def test_file_list_sibling_prefix_bypass(tmp_path):
    """file_list rejects escaping to a sibling dir via .."""
    base = tmp_path / "data"
    base.mkdir()
    sibling = tmp_path / "data_secret"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret")
    with pytest.raises(PermissionError):
        file_list("../data_secret", base_dir=str(base))


def test_file_read_symlink_escape_rejected(tmp_path):
    """a symlink inside base_dir pointing outside is rejected"""
    base = tmp_path / "data"
    base.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    try:
        (base / "link.txt").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PermissionError):
        file_read("link.txt", base_dir=str(base))


def test_file_read_symlink_within_base_allowed(tmp_path):
    """a symlink inside base_dir pointing to another in-base file works"""
    base = tmp_path / "data"
    base.mkdir()
    target = base / "target.txt"
    target.write_text("hello")
    try:
        (base / "link.txt").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert file_read("link.txt", base_dir=str(base)) == "hello"


def test_file_read_nested_subdir_allowed(tmp_path):
    """a legitimate in-base subdirectory path still works"""
    base = tmp_path / "data"
    sub = base / "docs"
    sub.mkdir(parents=True)
    (sub / "a.txt").write_text("nested")
    assert file_read("docs/a.txt", base_dir=str(base)) == "nested"


def test_file_write_creates_file(tmp_path):
    """creates file in allowed directory"""
    result = file_write("new.txt", "hello", base_dir=str(tmp_path))
    assert "Written" in result
    assert (tmp_path / "new.txt").read_text() == "hello"


def test_file_list_returns_files(tmp_path):
    """lists files in directory"""
    (tmp_path / "a.txt").touch()
    (tmp_path / "b.txt").touch()
    files = file_list(".", base_dir=str(tmp_path))
    assert isinstance(files, list)
    names = [f["name"] for f in files]
    assert "a.txt" in names
    assert "b.txt" in names


def test_file_search_by_content(tmp_path):
    """finds files containing query string"""
    (tmp_path / "file1.txt").write_text("hello world")
    (tmp_path / "file2.txt").write_text("goodbye")
    results = file_search("hello", base_dir=str(tmp_path))
    assert len(results) == 1
    assert results[0]["path"] == "file1.txt"


def test_email_draft_saves_file(tmp_path):
    """creates draft file"""
    with patch("os.makedirs"), patch("builtins.open", MagicMock()):
        result = email_draft("test@example.com", "Subject", "Body")
        assert "draft_id" in result
        assert result["to"] == "test@example.com"


def test_calendar_query_returns_list():
    """returns list (empty if no events file)"""
    events = calendar_query("2026-01-01")
    assert isinstance(events, list)


def test_web_search_demo_mode():
    """returns mock results when no API key set"""
    with patch.dict(os.environ, {}, clear=True):
        results = web_search("test query")
        assert isinstance(results, list)
        assert len(results) > 0
        assert "mock" in str(results).lower() or "demo" in str(results).lower()
