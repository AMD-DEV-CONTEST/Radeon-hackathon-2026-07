"""Portable replay bundles with a tamper-evident SHA-256 manifest."""
from dataclasses import dataclass
from pathlib import Path
import hashlib, hmac, json, os, platform, re, subprocess, sys

_BUNDLE_FILES = (
    "normalized_input.json",
    "sources.json",
    "results.json",
    "tool_trace.json",
    "metadata.json",
)


class ReplayVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerificationResult:
    valid: bool


def _dump(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ReplayVerificationError(f"bundle file must not be a symbolic link: {path.name}")
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path):
    def reject_constant(value):
        raise ValueError(f"non-finite JSON value: {value}")

    return json.loads(Path(path).read_text(), parse_constant=reject_constant)


@dataclass(frozen=True)
class ReplayBundle:
    path: Path

    @property
    def manifest_sha256(self) -> str:
        """Digest to retain externally as the bundle's trusted integrity root."""
        return _sha(self.path / "manifest.json")

    @classmethod
    def write(cls, path, normalized_input, sources, results, tool_trace=(), metadata=None):
        path = Path(path)
        if path.is_symlink():
            raise ReplayVerificationError("bundle path must not be a symbolic link")
        path.mkdir(parents=True, exist_ok=True)
        _dump(path / "normalized_input.json", normalized_input)
        _dump(path / "sources.json", sources)
        _dump(path / "results.json", results)
        _dump(path / "tool_trace.json", list(tool_trace))
        meta = metadata if metadata is not None else {"python": sys.version, "platform": platform.platform()}
        try:
            meta = {**meta, "git": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
        except (OSError, subprocess.CalledProcessError):
            pass
        _dump(path / "metadata.json", meta)

        files = {name: _sha(path / name) for name in _BUNDLE_FILES}
        temporary_manifest = path / f".manifest-{os.getpid()}.tmp"
        try:
            _dump(temporary_manifest, {"algorithm": "sha256", "files": files})
            os.replace(temporary_manifest, path / "manifest.json")
        finally:
            temporary_manifest.unlink(missing_ok=True)
        return cls(path)


def verify_bundle(path, rerun=None, *, expected_manifest_sha256=None):
    """Verify consistency and optionally bind it to an external trusted root.

    The root digest is not a signature and does not authenticate an author.
    """
    path = Path(path)
    if path.is_symlink():
        raise ReplayVerificationError("bundle path must not be a symbolic link")
    try:
        manifest = _load(path / "manifest.json")
    except (OSError, ValueError, TypeError) as exc:
        raise ReplayVerificationError("invalid manifest") from exc
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256, str) or re.fullmatch(
                r"[0-9a-f]{64}", expected_manifest_sha256) is None:
            raise ReplayVerificationError("trusted manifest root must be lowercase SHA-256")
        actual_root = _sha(path / "manifest.json")
        if not hmac.compare_digest(actual_root, expected_manifest_sha256):
            raise ReplayVerificationError("trusted manifest root mismatch")
    expected = set(_BUNDLE_FILES)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"algorithm", "files"}
        or manifest["algorithm"] != "sha256"
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != expected
    ):
        raise ReplayVerificationError("manifest schema mismatch")
    expected_entries = expected | {"manifest.json"}
    try:
        entries = list(path.iterdir())
    except OSError as exc:
        raise ReplayVerificationError("bundle directory unavailable") from exc
    if {entry.name for entry in entries} != expected_entries or len(entries) != len(expected_entries):
        raise ReplayVerificationError("bundle file set mismatch")
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ReplayVerificationError("bundle entries must be regular non-symlink files")
    for name, digest in manifest["files"].items():
        if (
            Path(name).name != name
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest.lower())
            or not (path / name).is_file()
            or (path / name).is_symlink()
            or _sha(path / name) != digest
        ):
            raise ReplayVerificationError(f"manifest mismatch: {name}")
    try:
        payloads = {name: _load(path / name) for name in _BUNDLE_FILES}
    except (OSError, ValueError, TypeError) as exc:
        raise ReplayVerificationError("invalid bundle JSON") from exc
    results = payloads["results.json"]
    if isinstance(results, dict) and "qualification_content_sha256" in results:
        if set(results) != {"qualification_content", "qualification_content_sha256"}:
            raise ReplayVerificationError("qualification result schema mismatch")
        encoded = json.dumps(results["qualification_content"], allow_nan=False, sort_keys=True,
                             separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != results["qualification_content_sha256"]:
            raise ReplayVerificationError("qualification content digest mismatch")
    if rerun is not None:
        if rerun(payloads["normalized_input.json"]) != payloads["results.json"]:
            raise ReplayVerificationError("deterministic rerun mismatch")
    return VerificationResult(True)
