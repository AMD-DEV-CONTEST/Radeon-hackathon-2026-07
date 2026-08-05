"""
determinex_cloak/context.py — CloakContext + CloakAuditLogger.

CloakContext is the single object passed through an entire solve() call.
Created once at the start, shared by all agent turns (Observer/Architect/Builder).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from pathlib import Path

from .restoration import restore_file_content, restore_patch
from .safe_list import FRAMEWORK_KEEP_LIST
from .symbol_map import SymbolMap
from .transformer import obfuscate_issue_text, obfuscate_source

log = logging.getLogger("determinex_cloak")


@dataclasses.dataclass
class CloakContext:
    """
    Single object per solve() call. Created once at the start of solve(), never rebuilt.
    All agent turns (Observer, Architect, Builder) share the same symbol map.
    """

    instance_id: str
    symbol_map: SymbolMap
    star_import_warnings: list[str]
    _file_cache: dict[str, str] = dataclasses.field(default_factory=dict)

    def obfuscate_file(self, file_path: Path, repo_root: Path) -> str:
        """Return obfuscated source for file_path. Lazy: computed on first call, cached.

        FAIL-CLOSED: a read error or obfuscation crash raises CloakObfuscationError.
        The previous behavior (cache "" and continue) silently coerced obfuscation
        failure into "empty file" semantics that downstream callers could not
        distinguish from a legitimately-empty file. Now the caller must explicitly
        decide what to do.
        """
        key = (
            str(file_path.relative_to(repo_root))
            if file_path.is_relative_to(repo_root)
            else str(file_path)
        )
        if key not in self._file_cache:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                # I/O failure — distinct from obfuscation failure but still must
                # fail closed: the caller has no source to obfuscate, must NOT
                # silently treat as empty.
                from . import CloakObfuscationError

                log.error("Cloak: cannot read %s: %s — failing closed", file_path, e)
                raise CloakObfuscationError(path=str(file_path), cause=e, source_len=0) from e
            try:
                self._file_cache[key] = obfuscate_source(source, self.symbol_map)
            except Exception as e:
                # obfuscate_source already raises CloakObfuscationError on its
                # own failures; attach the file path context and re-raise.
                from . import CloakObfuscationError

                if isinstance(e, CloakObfuscationError):
                    raise CloakObfuscationError(
                        path=str(file_path),
                        cause=e.cause,
                        source_len=e.source_len or len(source),
                    ) from e
                raise CloakObfuscationError(
                    path=str(file_path), cause=e, source_len=len(source)
                ) from e
        return self._file_cache[key]

    def obfuscate_source_str(self, source: str, cache_key: str = "") -> str:
        """Obfuscate an already-loaded source string. Cached by cache_key if provided.

        FAIL-CLOSED: any obfuscation failure propagates a CloakObfuscationError.
        The caller MUST treat this as a non-recoverable signal: do not send the
        original source over the network.
        """
        if cache_key and cache_key in self._file_cache:
            return self._file_cache[cache_key]
        try:
            result = obfuscate_source(source, self.symbol_map)
        except Exception as e:
            from . import CloakObfuscationError

            if isinstance(e, CloakObfuscationError):
                # Re-raise with cache_key context attached
                raise CloakObfuscationError(
                    path=cache_key or "(raw-source)",
                    cause=e.cause,
                    source_len=e.source_len or len(source),
                ) from e
            raise CloakObfuscationError(
                path=cache_key or "(raw-source)",
                cause=e,
                source_len=len(source),
            ) from e
        if cache_key:
            self._file_cache[cache_key] = result
        return result

    def restore_content(self, obfuscated: str) -> str:
        return restore_file_content(obfuscated, self.symbol_map)

    def restore_diff(self, raw_patch: str) -> tuple[str | None, str | None]:
        return restore_patch(raw_patch, self.symbol_map)

    def obfuscate_text(self, text: str) -> str:
        return obfuscate_issue_text(text, self.symbol_map)

    def save(self, run_dir: Path) -> None:
        """Write per-instance cloak map to audit directory."""
        audit_dir = run_dir / "cloak_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        map_path = audit_dir / f"cloak_map_{self.instance_id}.json"

        # Scan cached sources for keep-list names that actually appeared in this repo.
        # Keep-list names pass through unobfuscated, so they're visible verbatim in the cache.
        import re as _re

        keep_list_hits: list[str] = []
        combined = " ".join(self._file_cache.values())
        for name in sorted(FRAMEWORK_KEEP_LIST):
            if _re.search(r"\b" + _re.escape(name) + r"\b", combined):
                keep_list_hits.append(name)

        map_path.write_text(
            json.dumps(
                {
                    "instance_id": self.instance_id,
                    "private_id_count": len(self.symbol_map.forward),
                    "star_import_warnings": self.star_import_warnings,
                    "files_obfuscated": list(self._file_cache.keys()),
                    "keep_list_preserved": keep_list_hits,
                    "symbol_map": self.symbol_map.to_dict(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.debug("Cloak: map saved → %s (keep_list_hits=%d)", map_path, len(keep_list_hits))


class CloakAuditLogger:
    """
    Logs restoration failures and (optionally) obfuscated API request excerpts.
    Restoration failures → cloak_failures.jsonl (always)
    API request excerpts → api_requests.jsonl (only when DETERMINEX_CLOAK_AUDIT=1)
    """

    def __init__(self, run_dir: Path | None = None) -> None:
        self._run_dir = run_dir
        self._api_audit = bool(os.getenv("DETERMINEX_CLOAK_AUDIT", ""))

    def log_failure(
        self,
        instance_id: str,
        attempt: int,
        error: str,
        raw_patch_excerpt: str = "",
    ) -> None:
        if not self._run_dir:
            return
        audit_dir = self._run_dir / "cloak_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "instance_id": instance_id,
            "attempt": attempt,
            "error": error,
            "raw_patch_excerpt": raw_patch_excerpt[:500],
        }
        with (audit_dir / "cloak_failures.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def log_request(self, instance_id: str, role: str, obfuscated_prompt: str) -> None:
        if not self._run_dir or not self._api_audit:
            return
        audit_dir = self._run_dir / "cloak_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "instance_id": instance_id,
            "role": role,
            "prompt_excerpt": obfuscated_prompt[:1000],
        }
        with (audit_dir / "api_requests.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
