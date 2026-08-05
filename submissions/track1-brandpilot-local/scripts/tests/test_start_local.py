from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_windows_start_script_is_safe_and_explicit():
    script = (ROOT / "scripts" / "start-local.ps1").read_text(encoding="utf-8")
    assert "Assert-PortAvailable 3000" in script
    assert "Assert-PortAvailable 8000" in script
    assert '"--host", "127.0.0.1", "--port", "8000"' in script
    assert '"Frontend: http://localhost:3000"' in script
    assert '"Backend docs: http://localhost:8000/docs"' in script
    assert '"Health: http://localhost:8000/health"' in script
    assert "Stop-SpawnedProcessTree $process" in script
    assert 'Win32_Process -Filter "ParentProcessId=$($Process.Id)"' in script
    assert '& $backendPython -c "import fastapi, uvicorn"' in script
    assert '-ArgumentList "install"' not in script
    assert '"-m", "pip", "install"' not in script
