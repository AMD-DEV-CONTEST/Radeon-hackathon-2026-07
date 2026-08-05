"""
validators/yaml_validator.py — YAML parse + optional schema check
==================================================================
Validates YAML output via:
  1. `yaml.safe_load_all` — catches all YAML syntax errors and tag misuse.
  2. Optional jsonschema validation against task_meta['yaml_schema'].
  3. Optional yamllint pass (if installed) for style/indentation rules.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.yaml")

_FENCE_RE = re.compile(r"^```(?:yaml|yml)?\s*\n|\n```\s*$", flags=re.MULTILINE)


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate YAML.

    task_meta keys:
        yaml_schema (dict):    JSON schema applied to each document.
        require_documents (int): minimum number of YAML documents expected.
        skip_yamllint (bool):  skip optional yamllint pass.
        yamllint_strict (bool): warnings fail.
    """
    try:
        import yaml
    except ImportError:
        return False, "PyYAML not installed — cannot validate"

    text = _strip_markdown_fences(output)
    if len(text) < 1:
        return False, "Empty output"

    # Stage 1 — parse
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = mark.line + 1 if mark else "?"
        return False, f"YAML parse error @ L{line}: {getattr(e, 'problem', e)}"
    except Exception as e:
        return False, f"YAML parse exception: {e}"

    min_docs = int(task_meta.get("require_documents", 1))
    if len([d for d in docs if d is not None]) < min_docs:
        return False, f"expected >={min_docs} non-empty YAML document(s), got {len(docs)}"

    # Stage 2 — optional schema
    schema = task_meta.get("yaml_schema")
    if schema:
        try:
            import jsonschema
        except ImportError:
            return True, "parse passed; jsonschema unavailable (skipped)"
        for idx, doc in enumerate(docs):
            if doc is None:
                continue
            try:
                jsonschema.validate(doc, schema)
            except jsonschema.ValidationError as e:
                return False, f"doc[{idx}] schema violation: {e.message}"

    # Stage 3 — optional yamllint
    if task_meta.get("skip_yamllint"):
        return True, "parse + schema passed"
    yamllint = shutil.which("yamllint") or shutil.which("yamllint.exe")
    if not yamllint:
        return True, "parse + schema passed (yamllint unavailable)"

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        result = subprocess.run(
            [yamllint, "--format", "parsable", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "parse + schema + yamllint clean"
        lines = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
        errors = [ln for ln in lines if "[error]" in ln]
        warnings = [ln for ln in lines if "[warning]" in ln]
        if errors:
            return False, f"yamllint error: {errors[0][:200]}"
        if task_meta.get("yamllint_strict") and warnings:
            return False, f"yamllint strict warning: {warnings[0][:200]}"
        return True, f"parse + schema passed; {len(warnings)} yamllint warnings"
    except subprocess.TimeoutExpired:
        return False, "yamllint timeout"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
