"""Global chat-model loading status and download helpers.

This module provides a thread-safe-ish global status dictionary used by the
chat backend to report download / load progress, and a helper to download
GGUF models from HuggingFace with progress callbacks.
"""
import os
import threading
from pathlib import Path
from typing import Any, Optional


class ChatModelStatus:
    """Singleton-like status object for the chat model lifecycle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "state": "idle",  # idle | downloading | loading | ready | error
            "progress": 0.0,  # 0.0 - 1.0 when downloading/loading
            "message": "No chat model configured.",
            "model_path": None,
            "model_name": None,
        }

    def reset(self, model_name: Optional[str] = None):
        with self._lock:
            self._state.update(
                {
                    "state": "idle",
                    "progress": 0.0,
                    "message": "Initializing chat model...",
                    "model_path": None,
                    "model_name": model_name,
                }
            )

    def set_downloading(self, message: str = "Downloading model..."):
        with self._lock:
            self._state.update({"state": "downloading", "progress": 0.0, "message": message})

    def set_download_progress(self, progress: float, message: Optional[str] = None):
        with self._lock:
            self._state["progress"] = max(0.0, min(1.0, progress))
            if message:
                self._state["message"] = message

    def set_loading(self, message: str = "Loading model into memory..."):
        with self._lock:
            self._state.update({"state": "loading", "progress": 0.0, "message": message})

    def set_loading_progress(self, progress: float, message: Optional[str] = None):
        with self._lock:
            self._state["progress"] = max(0.0, min(1.0, progress))
            if message:
                self._state["message"] = message

    def set_ready(self, model_path: str, message: str = "Chat model ready.", model_name: Optional[str] = None):
        with self._lock:
            update = {"state": "ready", "progress": 1.0, "message": message, "model_path": model_path}
            if model_name is not None:
                update["model_name"] = model_name
            self._state.update(update)

    def set_error(self, error: str):
        with self._lock:
            self._state.update({"state": "error", "progress": 0.0, "message": error})

    def get(self) -> dict[str, Any]:
        with self._lock:
            return self._state.copy()


# Global status instance used by chat backend and API.
CHAT_STATUS = ChatModelStatus()


def download_gguf_model(
    repo_id: str,
    filename: str,
    local_dir: Optional[str] = None,
    cache_dir: Optional[str] = None,
) -> str:
    """Download a GGUF file from HuggingFace with progress tracking.

    Returns the absolute path to the downloaded file.
    """
    try:
        from huggingface_hub import hf_hub_download, hf_hub_url
        import requests  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Required download dependencies are missing.") from exc

    CHAT_STATUS.set_downloading(f"Downloading {filename} from {repo_id}...")

    # Fetch remote file size via HEAD request for progress tracking.
    total_size = 0
    try:
        url = hf_hub_url(repo_id=repo_id, filename=filename)
        head = requests.head(url, timeout=30, allow_redirects=True)
        if head.status_code == 200:
            total_size = int(head.headers.get("content-length", 0))
    except Exception:
        total_size = 0

    result: dict[str, Any] = {"path": None, "error": None}

    def _download():
        try:
            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=local_dir,
                cache_dir=cache_dir,
            )
            result["path"] = str(path)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=_download, name="gguf-download", daemon=True)
    thread.start()

    # Poll the destination file size until download finishes.
    while thread.is_alive():
        thread.join(timeout=0.5)
        if result["error"] is not None:
            raise result["error"]

        current_size = _estimate_local_file_size(local_dir, filename, cache_dir)
        if total_size > 0:
            progress = current_size / total_size
            CHAT_STATUS.set_download_progress(
                progress,
                f"Downloading {filename}: {progress * 100:.1f}% ({current_size / (1024 ** 2):.1f} / {total_size / (1024 ** 2):.1f} MB)",
            )
        else:
            CHAT_STATUS.set_download_progress(
                0.0,
                f"Downloading {filename}: {current_size / (1024 ** 2):.1f} MB downloaded...",
            )

    if result["error"] is not None:
        raise result["error"]
    if result["path"] is None:
        raise RuntimeError("Download finished but no path was returned.")
    return result["path"]


def _estimate_local_file_size(
    local_dir: Optional[str],
    filename: str,
    cache_dir: Optional[str],
) -> int:
    """Best-effort estimate of bytes already written for the target file."""
    candidates = []
    if local_dir:
        candidates.append(Path(local_dir) / filename)
    if cache_dir:
        candidates.append(Path(cache_dir) / filename)
    # Fallback to current working directory / models/chat
    candidates.append(Path(os.getcwd()) / "models" / "chat" / filename)
    for path in candidates:
        if path.exists():
            return path.stat().st_size
    return 0


def resolve_chat_model_path(model_name: str, default_filename: str = "Bonsai-27B-Q1_0.gguf") -> str:
    """Resolve CHAT_MODEL value to a local GGUF file path.

    Accepted forms:
    - Absolute or relative path to an existing .gguf file.
    - HuggingFace repo id (e.g. 'prism-ml/Bonsai-27B-gguf'). In this case the
      default filename is downloaded.
    - repo_id:filename (e.g. 'prism-ml/Bonsai-27B-gguf:Bonsai-27B-Q1_0.gguf').
    """
    candidate = Path(model_name)
    if candidate.exists() and candidate.suffix == ".gguf":
        return str(candidate.resolve())

    if ":" in model_name:
        repo_id, filename = model_name.split(":", 1)
    else:
        repo_id = model_name
        filename = default_filename

    cache_dir = os.environ.get("HF_HOME")
    local_dir = os.path.join(os.getcwd(), "models", "chat")
    os.makedirs(local_dir, exist_ok=True)
    return download_gguf_model(repo_id, filename, local_dir=local_dir, cache_dir=cache_dir)
