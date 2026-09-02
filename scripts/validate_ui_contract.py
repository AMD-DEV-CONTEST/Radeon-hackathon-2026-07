"""Validate the UI-0 frontend contract against the backend Schema.

Two independent, server-less checks back the UI-0 acceptance criteria:

1. DTO field consistency -- every ``export interface`` in
   ``web/src/api/dto.ts`` annotated with ``// maps: <Model>`` must use ONLY
   field names that exist on the corresponding Pydantic model exposed by
   ``app.schemas.models``. This enforces the UI-0 rule: frontend DTO field
   names MUST NOT diverge from the backend Pydantic Schema.

2. Path consistency -- every path constant declared in
   ``web/src/api/paths.ts`` must match a real route registered in
   ``app/api/*.py`` (router prefix + route path, with ``{param}`` placeholders
   ignored). This guards against the backend's NON-UNIFORM prefixes being
   guessed wrong on the frontend.

Exit code is non-zero when any inconsistency is found.
"""
from __future__ import annotations

import inspect
import os
import re

import pydantic

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_backend_field_index():
    """Map Pydantic model name -> set of field names (from app.schemas.models)."""
    import app.schemas.models as models_mod

    index: dict[str, set[str]] = {}
    for _name, obj in inspect.getmembers(models_mod, inspect.isclass):
        if obj is pydantic.BaseModel:
            continue
        if isinstance(obj, type) and issubclass(obj, pydantic.BaseModel):
            index[obj.__name__] = set(getattr(obj, "model_fields", {}).keys())
    return index


# A `// maps:` annotation must sit on the line directly above its interface.
BLOCK_RE = re.compile(
    r"//\s*maps:\s*(\w+)\s*\n\s*export\s+interface\s+(\w+)\s*\{(.*?)\n\}",
    re.DOTALL,
)


def parse_dtos(dto_path: str):
    """Return list of (interface_name, maps_to, [field_names])."""
    with open(dto_path, encoding="utf-8") as fh:
        text = fh.read()

    results: list[tuple[str, str | None, list[str]]] = []
    for m in BLOCK_RE.finditer(text):
        maps_to = m.group(1)
        name = m.group(2)
        body = m.group(3)
        fields = [
            f
            for f in re.findall(r"^\s{2,}(\w+)\s*:", body, re.MULTILINE)
            if not f.startswith("//")
        ]
        results.append((name, maps_to, fields))
    return results


def validate_dto_fields(web_dir: str | None = None) -> list[str]:
    web_dir = web_dir or os.path.join(REPO_ROOT, "web")
    dto_path = os.path.join(web_dir, "src", "api", "dto.ts")
    if not os.path.exists(dto_path):
        return [f"DTO file not found: {dto_path}"]

    index = build_backend_field_index()
    errors: list[str] = []
    for name, maps_to, fields in parse_dtos(dto_path):
        if maps_to is None:
            # Not all interfaces must map; only mapped ones are checked.
            continue
        if maps_to not in index:
            errors.append(
                f"DTO '{name}' maps to unknown backend model '{maps_to}'. "
                f"Available: {sorted(index)}"
            )
            continue
        allowed = index[maps_to]
        for field in fields:
            if field not in allowed:
                errors.append(
                    f"DTO '{name}' field '{field}' is not a field of backend "
                    f"model '{maps_to}'. Allowed fields: {sorted(allowed)}"
                )
    return errors


def _normalize_path(path: str) -> str:
    """Strip {param} names so structure can be compared regardless of naming."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def build_backend_routes(api_dir: str | None = None) -> set[str]:
    api_dir = api_dir or os.path.join(REPO_ROOT, "app", "api")
    routes: set[str] = set()
    for fname in sorted(os.listdir(api_dir)):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(api_dir, fname), encoding="utf-8") as fh:
            text = fh.read()
        prefix = ""
        # Capture the APIRouter(...) constructor (stop at first ')'; routers
        # without a prefix have none, and that is fine).
        cm = re.search(r"APIRouter\(([^)]*)\)", text, re.DOTALL)
        if cm:
            pfx = re.search(r"prefix\s*=\s*[\"']([^\"']*)[\"']", cm.group(1))
            if pfx:
                prefix = pfx.group(1)
        for rm in re.finditer(
            r"@router\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']*)[\"']",
            text,
        ):
            route = rm.group(1)
            # FastAPI always concatenates prefix + path, even when the path
            # starts with '/', so we always join (normalising a double slash).
            full = prefix.rstrip("/") + route
            routes.add(_normalize_path(full))
    return routes


def parse_paths(paths_path: str) -> list[str]:
    with open(paths_path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"export\s+const\s+API_PATHS\s*=\s*\{(.*?)\n\}", text, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    paths: list[str] = []
    for mm in re.finditer(r"(\w+):\s*'([^']*)'", body):
        paths.append(mm.group(2))
    for mm in re.finditer(r"(\w+):\s*\([^)]*\)\s*=>\s*`([^`]*)`", body):
        tpl = re.sub(r"\$\{([^}]+)\}", lambda x: "{%s}" % x.group(1), mm.group(2))
        paths.append(tpl)
    return paths


def validate_paths(web_dir: str | None = None, api_dir: str | None = None) -> list[str]:
    web_dir = web_dir or os.path.join(REPO_ROOT, "web")
    api_dir = api_dir or os.path.join(REPO_ROOT, "app", "api")
    paths_path = os.path.join(web_dir, "src", "api", "paths.ts")
    if not os.path.exists(paths_path):
        return [f"Paths file not found: {paths_path}"]

    backend = build_backend_routes(api_dir)
    errors: list[str] = []
    for raw in parse_paths(paths_path):
        norm = _normalize_path(raw)
        if norm not in backend:
            errors.append(
                f"Path '{raw}' (normalized '{norm}') is not a registered backend "
                f"route. Known route patterns: {sorted(backend)}"
            )
    return errors


def main() -> int:
    errors = validate_dto_fields() + validate_paths()
    if errors:
        print("UI contract validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("UI contract validation PASSED: DTO fields and API paths match backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
