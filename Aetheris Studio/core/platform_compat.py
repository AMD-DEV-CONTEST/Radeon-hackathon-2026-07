import os
import signal
import stat
import subprocess
import platform

IS_WINDOWS = os.name == "nt"

def safe_chmod(path, mode):
    """
    Apply chmod only if not on Windows, or just silently pass.
    """
    if not IS_WINDOWS:
        try:
            os.chmod(path, mode)
        except Exception:
            pass

def pid_alive(pid: int) -> bool:
    """Check if a given PID is alive."""
    if IS_WINDOWS:
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # Fallback
            import subprocess
            try:
                output = subprocess.check_output(f'tasklist /FI "PID eq {pid}"', shell=True, text=True)
                return str(pid) in output
            except Exception:
                return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

def find_bash() -> str:
    """Find a valid bash executable."""
    if IS_WINDOWS:
        # Check common Git Bash locations
        paths = [
            "C:\\Program Files\\Git\\bin\\bash.exe",
            "C:\\Program Files\\Git\\usr\\bin\\bash.exe"
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return "bash"
    else:
        return "bash"


def git_bash_path(path) -> str:
    """Convert a native path to the POSIX form Git Bash/MSYS expects
    (`C:\\Users\\foo\\bar.sh` -> `/c/Users/foo/bar.sh`). A no-op on POSIX,
    where native paths are already what `bash` wants."""
    s = str(path)
    if not IS_WINDOWS:
        return s
    s = s.replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = "/" + s[0].lower() + s[2:]
    return s


def detached_popen_kwargs() -> dict:
    """Extra `subprocess.Popen` kwargs to detach a child from this
    process's lifecycle, so it keeps running after the parent request/
    process ends: `setsid` on POSIX (new session, new process group),
    `DETACHED_PROCESS` on Windows (no inherited console)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_process_tree(pid) -> None:
    """Cross-platform process-tree teardown: POSIX `killpg` (works because
    `detached_popen_kwargs()` put the child in its own session/process
    group via `start_new_session`), Windows `taskkill /T` (walks the tree
    by parent PID, independent of process groups)."""
    if pid is None:
        return
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
