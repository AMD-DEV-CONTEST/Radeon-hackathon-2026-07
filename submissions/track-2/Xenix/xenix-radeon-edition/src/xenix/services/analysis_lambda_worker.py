from __future__ import annotations

import ast
import base64
import builtins
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import sklearn
import statsmodels
from matplotlib.figure import Figure

from .dataset_inspection import detect_source_format, load_dataframe


ALLOWED_IMPORT_ROOTS = {
    "collections",
    "datetime",
    "functools",
    "io",
    "itertools",
    "json",
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "statistics",
    "statsmodels",
    "typing",
    "xgboost",
    "lightgbm",
}

SAFE_BUILTINS = {
    "abs": builtins.abs,
    "all": builtins.all,
    "any": builtins.any,
    "bool": builtins.bool,
    "dict": builtins.dict,
    "enumerate": builtins.enumerate,
    "float": builtins.float,
    "int": builtins.int,
    "isinstance": builtins.isinstance,
    "len": builtins.len,
    "list": builtins.list,
    "max": builtins.max,
    "min": builtins.min,
    "pow": builtins.pow,
    "range": builtins.range,
    "round": builtins.round,
    "set": builtins.set,
    "sorted": builtins.sorted,
    "str": builtins.str,
    "sum": builtins.sum,
    "tuple": builtins.tuple,
    "zip": builtins.zip,
}


@dataclass(frozen=True)
class _ArtifactRef:
    id: str
    uri: str
    kind: str


class _ArtifactContext:
    def __init__(self, output_dir: Path, limits: dict[str, Any]) -> None:
        self._output_dir = output_dir
        self._max_artifacts = int(limits["max_artifacts"])
        self._max_artifact_bytes = int(limits["max_artifact_bytes"])
        self._max_dataframe_rows = int(limits["max_dataframe_artifact_rows"])
        self._artifacts: list[dict[str, Any]] = []

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        return list(self._artifacts)

    def create(self, *args: Any, **kwargs: Any) -> _ArtifactRef:
        name, content = self._normalize_create_args(args, kwargs)
        kind = kwargs.pop("kind", None)
        media_type = kwargs.pop("media_type", None)
        extension = kwargs.pop("extension", None)
        summary = kwargs.pop("summary", None)
        metadata = kwargs.pop("metadata", None)
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise RuntimeError(f"ctx.artifact.create got unexpected keyword argument(s): {unexpected}.")
        if len(self._artifacts) >= self._max_artifacts:
            raise RuntimeError(f"analysis.lambda can create at most {self._max_artifacts} artifacts.")
        title = str(name or "").strip()
        if not title:
            raise RuntimeError("ctx.artifact.create requires a non-empty name.")

        artifact_index = len(self._artifacts) + 1
        placeholder_id = f"lambda_artifact_{artifact_index}"
        inferred = self._materialize_content(
            placeholder_id,
            title,
            content,
            kind=kind,
            media_type=media_type,
            extension=extension,
        )
        path = inferred["path"]
        size = path.stat().st_size
        if size > self._max_artifact_bytes:
            try:
                path.unlink()
            except OSError:
                pass
            raise RuntimeError(
                f"Artifact '{title}' is {size} bytes; limit is {self._max_artifact_bytes} bytes."
            )

        descriptor = {
            "placeholder_id": placeholder_id,
            "title": title,
            "absolute_path": str(path.resolve()),
            "kind": inferred["kind"],
            "mime_type": inferred["mime_type"],
            "summary": str(summary).strip() if summary else None,
            "metadata_payload": _json_safe(metadata or {}),
        }
        self._artifacts.append(descriptor)
        return _ArtifactRef(
            id=placeholder_id,
            uri=f"artifact://{placeholder_id}",
            kind=descriptor["kind"],
        )

    def _normalize_create_args(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, Any]:
        if "value" in kwargs and "content" not in kwargs:
            kwargs["content"] = kwargs.pop("value")
        has_name = "name" in kwargs
        has_content = "content" in kwargs
        if len(args) == 2 and not has_name and not has_content:
            return str(args[0]), args[1]
        if len(args) == 1 and has_name and not has_content:
            return str(kwargs.pop("name")), args[0]
        if len(args) == 1 and has_content and not has_name:
            return str(args[0]), kwargs.pop("content")
        if len(args) == 0 and has_name and has_content:
            return str(kwargs.pop("name")), kwargs.pop("content")
        raise RuntimeError(
            "ctx.artifact.create expects (name, content), (content, name=...), "
            "or keyword arguments name=... and content=...."
        )

    def _materialize_content(
        self,
        placeholder_id: str,
        title: str,
        content: Any,
        *,
        kind: str | None,
        media_type: str | None,
        extension: str | None,
    ) -> dict[str, Any]:
        if isinstance(content, pd.DataFrame):
            if len(content.index) > self._max_dataframe_rows:
                raise RuntimeError(
                    f"DataFrame artifact '{title}' has {len(content.index)} rows; "
                    f"limit is {self._max_dataframe_rows}."
                )
            path = self._path_for(placeholder_id, title, extension or ".csv")
            content.to_csv(path, index=False)
            return {"path": path, "kind": kind or "dataset", "mime_type": media_type or "text/csv"}

        if isinstance(content, Figure):
            path = self._path_for(placeholder_id, title, extension or ".svg")
            content.savefig(path, format="svg", bbox_inches="tight")
            plt.close(content)
            return {"path": path, "kind": kind or "image", "mime_type": media_type or "image/svg+xml"}

        if isinstance(content, str):
            is_svg = content.lstrip().lower().startswith("<svg") or media_type == "image/svg+xml"
            path = self._path_for(placeholder_id, title, extension or (".svg" if is_svg else ".txt"))
            path.write_text(content, encoding="utf-8")
            return {
                "path": path,
                "kind": kind or ("image" if is_svg else "report"),
                "mime_type": media_type or ("image/svg+xml" if is_svg else "text/plain"),
            }

        if isinstance(content, io.BytesIO):
            content = content.getvalue()

        if isinstance(content, bytes):
            resolved_extension = extension or _extension_for_media_type(media_type) or ".bin"
            if extension is None and media_type is None:
                inferred_extension = _extension_for_title(title)
                if inferred_extension:
                    resolved_extension = inferred_extension
                    media_type = _media_type_for_extension(inferred_extension)
            path = self._path_for(placeholder_id, title, resolved_extension)
            path.write_bytes(content)
            return {
                "path": path,
                "kind": kind or ("image" if str(media_type or "").startswith("image/") else "file"),
                "mime_type": media_type or "application/octet-stream",
            }

        raise RuntimeError(
            "ctx.artifact.create content must be a pandas DataFrame, SVG/text string, bytes, "
            "or matplotlib.figure.Figure."
        )

    def _path_for(self, placeholder_id: str, title: str, extension: str) -> Path:
        clean_extension = extension if extension.startswith(".") else f".{extension}"
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-._") or "artifact"
        path = self._output_dir / f"{placeholder_id}-{slug[:48]}{clean_extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class _AnalysisContext:
    def __init__(self, output_dir: Path, limits: dict[str, Any]) -> None:
        self.artifact = _ArtifactContext(output_dir, limits)
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def warn(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self._warnings.append(text)


def main(input_path: str, output_path: str) -> None:
    response: dict[str, Any]
    try:
        request = json.loads(Path(input_path).read_text(encoding="utf-8"))
        response = _execute(request)
    except Exception as exc:  # pragma: no cover - parent tests assert the surfaced error
        response = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    Path(output_path).write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    code = str(request.get("code") or "")
    if not code.strip():
        raise RuntimeError("analysis.lambda code cannot be empty.")
    _validate_imports(code)

    limits = dict(request["limits"])
    output_dir = Path(request["artifact_output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = _load_inputs(request, limits)
    params = dict(request.get("params") or {})
    ctx = _AnalysisContext(output_dir, limits)

    globals_dict = _globals()
    exec(compile(code, "<analysis.lambda>", "exec"), globals_dict, globals_dict)
    analyze = globals_dict.get("analyze")
    if not callable(analyze):
        raise RuntimeError("analysis.lambda code must define callable analyze(ctx, inputs, params).")

    raw_output = analyze(ctx, inputs, params)
    if not isinstance(raw_output, dict):
        raise RuntimeError("analyze(ctx, inputs, params) must return a dict.")
    output = _json_safe(raw_output)
    if ctx.warnings:
        output.setdefault("warnings", ctx.warnings)

    return {
        "status": "succeeded",
        "output": output,
        "artifacts": ctx.artifact.artifacts,
    }


def _load_inputs(request: dict[str, Any], limits: dict[str, Any]) -> dict[str, pd.DataFrame]:
    max_rows = int(limits["max_input_rows_per_dataset"])
    inputs: dict[str, pd.DataFrame] = {}
    for dataset in request.get("datasets", []):
        alias = str(dataset.get("alias") or "").strip()
        if not alias:
            raise RuntimeError("Dataset alias cannot be empty.")
        source_path = Path(str(dataset.get("source_path") or "")).expanduser()
        source_format = detect_source_format(source_path)
        frame = load_dataframe(source_path, source_format).rename(columns=str)
        if len(frame.index) > max_rows:
            frame = frame.head(max_rows).copy()
        frame.read = lambda frame=frame: frame
        inputs[alias] = frame
    return inputs


def _globals() -> dict[str, Any]:
    safe_builtins = dict(SAFE_BUILTINS)
    safe_builtins["__import__"] = _safe_import
    return {
        "__builtins__": safe_builtins,
        "pd": pd,
        "pandas": pd,
        "np": np,
        "numpy": np,
        "plt": plt,
        "matplotlib": matplotlib,
        "scipy": scipy,
        "statsmodels": statsmodels,
        "sklearn": sklearn,
        "math": math,
        "io": io,
    }


def _safe_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # noqa: A002
    if level != 0:
        raise ImportError("Relative imports are not supported in analysis.lambda.")
    root = name.split(".", 1)[0]
    if root not in ALLOWED_IMPORT_ROOTS:
        raise ImportError(f"Import '{root}' is not allowed in analysis.lambda.")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _validate_imports(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    raise RuntimeError(f"Import '{root}' is not allowed in analysis.lambda.")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise RuntimeError("Relative imports are not supported in analysis.lambda.")
            root = str(node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                raise RuntimeError(f"Import '{root}' is not allowed in analysis.lambda.")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        normalized = float(value)
        return normalized if math.isfinite(normalized) else None
    if isinstance(value, date | datetime | pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, _ArtifactRef):
        return {
            "id": value.id,
            "uri": value.uri,
            "kind": value.kind,
        }
    raise RuntimeError(f"Value of type {type(value).__name__} is not JSON-serializable for analysis.lambda.")


def _extension_for_media_type(media_type: str | None) -> str | None:
    if media_type == "image/svg+xml":
        return ".svg"
    if media_type == "image/png":
        return ".png"
    if media_type == "image/jpeg":
        return ".jpg"
    if media_type == "text/csv":
        return ".csv"
    if media_type == "text/plain":
        return ".txt"
    return None


def _extension_for_title(title: str) -> str | None:
    suffix = Path(str(title)).suffix.lower()
    if suffix in {".svg", ".png", ".jpg", ".jpeg", ".csv", ".txt"}:
        return suffix
    return None


def _media_type_for_extension(extension: str) -> str | None:
    normalized = extension.lower()
    if normalized == ".svg":
        return "image/svg+xml"
    if normalized == ".png":
        return "image/png"
    if normalized in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if normalized == ".csv":
        return "text/csv"
    if normalized == ".txt":
        return "text/plain"
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m xenix.services.analysis_lambda_worker <input-json> <output-json>")
    main(sys.argv[1], sys.argv[2])
