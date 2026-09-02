"""
determinex_forge.py — Vanguard Vault Decryption CLI

Decrypts the AES-256-GCM encrypted DPO training pairs written by the Rust
telemetry_logger, converts them from ShareGPT format to train_unsloth JSONL,
and appends them to the corpus. Processed .enc files are moved to
.determinex_staging/outbox/processed/ so they are never double-counted.

Encryption envelope format (must match telemetry_logger.rs exactly):
    Base64( nonce[12 bytes] || ciphertext+GCM-tag[n+16 bytes] )

Key: 32 raw bytes at .determinex_staging/vault/vault.key (AES-256-GCM)

Usage:
    python scripts/determinex_forge.py                   # flush outbox -> JSONL
    python scripts/determinex_forge.py --dry-run         # decrypt and count, no writes
    python scripts/determinex_forge.py --outbox PATH     # custom outbox dir
    python scripts/determinex_forge.py --key PATH        # custom vault key path
    python scripts/determinex_forge.py --output PATH     # custom JSONL output file
"""

import argparse
import base64
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── UTF-8 terminal fix (Windows) ────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Paths ────────────────────────────────────────────────────────────────────
_DETERMINEX_ROOT = Path(__file__).resolve().parent.parent
_STAGING = _DETERMINEX_ROOT / ".determinex_staging"
_DEFAULT_OUTBOX = _STAGING / "outbox"
_DEFAULT_KEY = _STAGING / "vault" / "vault.key"
_DEFAULT_OUTPUT = _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_vanguard_dpo.jsonl"
_PROCESSED_DIR = _DEFAULT_OUTBOX / "processed"


# ── Crypto ───────────────────────────────────────────────────────────────────


def _load_key(key_path: Path) -> bytes:
    """Load the 32-byte AES-256-GCM vault key from disk."""
    if not key_path.exists():
        raise FileNotFoundError(
            f"[FORGE] vault.key not found at {key_path}\n"
            "       The Tauri app generates this on first Vanguard-enabled run.\n"
            "       Enable Vanguard telemetry in the app settings and run at least one task."
        )
    raw = key_path.read_bytes()
    if len(raw) != 32:
        raise ValueError(
            f"[FORGE] vault.key is corrupt ({len(raw)} bytes, expected 32). "
            "Delete it and let the app regenerate."
        )
    return raw


def _decrypt_envelope(key_bytes: bytes, encoded: str) -> str:
    """
    Decrypt a Base64-encoded AES-256-GCM envelope.
    Envelope format: Base64( nonce[12] || ciphertext+tag[n+16] )
    Returns the plaintext as a UTF-8 string.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "[FORGE] 'cryptography' package required.\n       pip install cryptography"
        )

    envelope = base64.b64decode(encoded.strip())
    if len(envelope) < 28:  # 12 nonce + 16 tag minimum
        raise ValueError(f"[FORGE] Envelope too short ({len(envelope)} bytes) — corrupt .enc file.")

    nonce = envelope[:12]
    ciphertext = envelope[12:]  # includes GCM tag at the end (Python cryptography handles this)

    aesgcm = AESGCM(key_bytes)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ── Format Conversion ────────────────────────────────────────────────────────


def _sharegpt_to_training(record: dict) -> dict | None:
    """
    Convert a ShareGPT-format record to train_unsloth JSONL format.

    ShareGPT input:
        {"conversations": [
            {"from": "system",    "value": "..."},
            {"from": "user",      "value": "..."},
            {"from": "assistant", "value": "..."}
        ]}

    train_unsloth output:
        {"system": "...", "user": "...", "assistant": "..."}

    Returns None if the record is malformed.
    """
    conversations = record.get("conversations", [])
    if not conversations:
        return None

    result = {}
    for turn in conversations:
        role = turn.get("from", "").lower()
        value = turn.get("value", "").strip()
        if role in ("system", "user", "assistant") and value:
            result[role] = value

    # All three roles required
    if not all(k in result for k in ("system", "user", "assistant")):
        return None

    return result


# ── Main Flush Logic ─────────────────────────────────────────────────────────


def flush_outbox(
    outbox_dir: Path,
    key_path: Path,
    output_jsonl: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """
    Decrypt all .enc files in outbox_dir, convert to JSONL, append to output_jsonl.
    Moves processed files to outbox_dir/processed/.
    Returns the number of samples successfully flushed.
    """
    enc_files = sorted(outbox_dir.glob("*.enc"))

    if not enc_files:
        print("[FORGE] Outbox empty — nothing to flush.", flush=True)
        return 0

    print(f"[FORGE] Found {len(enc_files)} encrypted payload(s) in outbox.", flush=True)

    # Load key once — fail fast if missing
    try:
        key_bytes = _load_key(key_path)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), flush=True)
        return 0

    flushed = 0
    skipped = 0
    processed = _PROCESSED_DIR if not dry_run else None

    if processed and not dry_run:
        processed.mkdir(parents=True, exist_ok=True)

    lines_to_append = []

    for enc_file in enc_files:
        try:
            encoded = enc_file.read_text(encoding="utf-8").strip()
            plaintext = _decrypt_envelope(key_bytes, encoded)
            record = json.loads(plaintext)
            converted = _sharegpt_to_training(record)

            if converted is None:
                print(f"[FORGE] SKIP {enc_file.name} — malformed ShareGPT record.", flush=True)
                skipped += 1
                continue

            lines_to_append.append(json.dumps(converted, ensure_ascii=False))
            flushed += 1

            if verbose:
                preview = converted["user"][:80].replace("\n", " ")
                print(f"[FORGE] OK   {enc_file.name} | {preview}…", flush=True)

        except Exception as e:
            print(f"[FORGE] ERROR {enc_file.name} — {e}", flush=True)
            skipped += 1
            continue

        # Move to processed (only when not dry-run)
        if not dry_run and processed:
            dest = processed / enc_file.name
            shutil.move(str(enc_file), str(dest))

    if lines_to_append and not dry_run:
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with output_jsonl.open("a", encoding="utf-8") as f:
            for line in lines_to_append:
                f.write(line + "\n")
        print(
            f"[FORGE] Flushed {flushed} sample(s) → {output_jsonl.name}  ({skipped} skipped)",
            flush=True,
        )
    elif lines_to_append and dry_run:
        print(
            f"[FORGE] DRY RUN — would flush {flushed} sample(s)  "
            f"({skipped} skipped, nothing written)",
            flush=True,
        )
    else:
        print(f"[FORGE] No valid samples decoded. ({skipped} skipped)", flush=True)

    return flushed


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="determinex-forge — Vanguard vault decryption and JSONL flush"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="decrypt-outbox",
        choices=["decrypt-outbox"],
        help="Command to run (default: decrypt-outbox)",
    )
    parser.add_argument(
        "--outbox",
        type=Path,
        default=_DEFAULT_OUTBOX,
        help=f"Outbox directory (default: {_DEFAULT_OUTBOX})",
    )
    parser.add_argument(
        "--key", type=Path, default=_DEFAULT_KEY, help=f"Vault key path (default: {_DEFAULT_KEY})"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output JSONL file (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt and count without writing JSONL or moving files",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print a preview of each decrypted sample"
    )
    args = parser.parse_args()

    if not args.outbox.exists():
        print(f"[FORGE] Outbox directory does not exist: {args.outbox}", flush=True)
        print("[FORGE] Nothing to flush — outbox is empty.", flush=True)
        sys.exit(0)

    print(f"\n[FORGE] {'DRY RUN — ' if args.dry_run else ''}Determinex Vanguard Vault Flush")
    print(f"[FORGE] Outbox : {args.outbox}")
    print(f"[FORGE] Key    : {args.key}")
    print(f"[FORGE] Output : {args.output}")
    print(f"[FORGE] Time   : {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n", flush=True)

    count = flush_outbox(
        outbox_dir=args.outbox,
        key_path=args.key,
        output_jsonl=args.output,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print(f"\n[FORGE] Done. {count} sample(s) flushed.", flush=True)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
