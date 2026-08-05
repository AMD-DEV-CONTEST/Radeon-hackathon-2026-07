"""
forge_watcher.py — Determinex Training Flywheel Watcher

Polls the encrypted outbox produced by the Rust telemetry logger, decrypts
each .enc file, normalises role names to ShareGPT format, and appends to the
JSONL dataset consumed by train_observer.py. When accumulated sample count
reaches the configured threshold, fires train_observer.py automatically.

Data Flow:
    Rust orchestrator
        → AES-256-GCM encrypt
        → ~/.determinex_staging/outbox/telemetry_<ts>.enc

    forge_watcher.py (this script)
        → decrypt with ~/.determinex_staging/vault/vault.key
        → normalise roles  (from/user/assistant → role/human/gpt)
        → append to .determinex_staging/training_data/observer_dpo.jsonl
        → if new_samples >= threshold → run train_observer.py
        → archive processed .enc files to ~/.determinex_staging/processed/

Usage:
    python forge_watcher.py                        # defaults, polls forever
    python forge_watcher.py --threshold 20         # train every 20 samples
    python forge_watcher.py --once                 # drain outbox once and exit
    python forge_watcher.py --dry-run              # decrypt + normalise, no write
    python forge_watcher.py --poll-secs 60         # check every 60s (default: 30)

State file:
    scripts/fine_tuning/forge_state.json
    Tracks how many samples existed at the last training trigger so the
    threshold counter resets correctly across restarts.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent  # scripts/fine_tuning/
_DETERMINEX_ROOT = _SCRIPT_DIR.parent.parent

_DEFAULT_OUTBOX = Path.home() / ".determinex_staging" / "outbox"
_DEFAULT_VAULT = Path.home() / ".determinex_staging" / "vault" / "vault.key"
_DEFAULT_STAGING = _DETERMINEX_ROOT / ".determinex_staging" / "training_data" / "observer_dpo.jsonl"
_DEFAULT_ARCHIVE = Path.home() / ".determinex_staging" / "processed"

_STATE_FILE = _SCRIPT_DIR / "forge_state.json"
_TRAIN_SCRIPT = _SCRIPT_DIR / "train_observer.py"

# ─────────────────────────────────────────────────────────────────────────────
# DECRYPTION
# ─────────────────────────────────────────────────────────────────────────────


def load_vault_key(vault_path: Path) -> bytes:
    """Read the 32-byte AES-256-GCM key written by the Rust telemetry logger."""
    if not vault_path.exists():
        raise FileNotFoundError(
            f"[WATCHER] vault.key not found at {vault_path}\n"
            "  The key is generated on first Determinex app launch.\n"
            "  Run the Tauri app at least once to initialise the vault."
        )
    raw = vault_path.read_bytes()
    if len(raw) != 32:
        raise ValueError(
            f"[WATCHER] vault.key is corrupt ({len(raw)} bytes, expected 32). "
            "Delete it and relaunch the Determinex app to regenerate."
        )
    return raw


def decrypt_enc_file(vault_key: bytes, enc_path: Path) -> dict:
    """
    Decrypt one .enc file produced by telemetry_logger.rs.

    Envelope format (from the Rust source):
        Base64( nonce[12 bytes] || ciphertext || GCM-tag[16 bytes] )

    Returns the parsed JSON payload as a dict.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit(
            "[WATCHER] FATAL: 'cryptography' package not installed.\n"
            "  Run: pip install cryptography"
        )

    b64_line = enc_path.read_text(encoding="utf-8").strip()
    envelope = base64.b64decode(b64_line)

    nonce = envelope[:12]
    ciphertext_and_tag = envelope[12:]

    aesgcm = AESGCM(vault_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
    return json.loads(plaintext.decode("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# ROLE NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

# The Rust telemetry logger writes ShareGPT entries using the "from" key and
# "user"/"assistant" role names. train_observer.py and Unsloth's chat template
# expect the "role" key with "human"/"gpt" names.
_ROLE_MAP = {
    "system": "system",
    "user": "human",
    "human": "human",
    "assistant": "gpt",
    "gpt": "gpt",
}


def normalise_conversation(raw: dict) -> dict:
    """
    Convert a telemetry payload into the ShareGPT format expected by
    train_observer.py:
      {"conversations": [{"role": "...", "value": "..."}, ...]}

    Accepts both "from"/"role" key variants and normalises role names.
    Raises ValueError if any turn has an unrecognised role.
    """
    turns = raw.get("conversations", [])
    normalised = []
    for turn in turns:
        # Accept either "from" (Rust writer) or "role" (already normalised)
        raw_role = turn.get("from") or turn.get("role", "")
        role = _ROLE_MAP.get(raw_role.lower())
        if role is None:
            raise ValueError(f"Unrecognised role '{raw_role}' in conversation turn")
        normalised.append({"role": role, "value": turn["value"]})
    return {"conversations": normalised}


# ─────────────────────────────────────────────────────────────────────────────
# STATE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────


def load_state() -> dict:
    """Load persisted watcher state, returning defaults on first run."""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"samples_at_last_train": 0, "total_decrypted": 0, "training_runs": 0}


def save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE COUNT
# ─────────────────────────────────────────────────────────────────────────────


def count_jsonl_lines(path: Path) -> int:
    """Count non-empty lines in a JSONL file without loading it into memory."""
    if not path.exists():
        return 0
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# OUTBOX DRAIN
# ─────────────────────────────────────────────────────────────────────────────


def drain_outbox(
    outbox_dir: Path,
    vault_key: bytes,
    staging_jsonl: Path,
    archive_dir: Path,
    dry_run: bool,
) -> int:
    """
    Decrypt all unprocessed .enc files in outbox_dir and append them to
    staging_jsonl. Archives each file to archive_dir on success.

    Returns the number of new samples successfully processed.
    """
    enc_files = sorted(outbox_dir.glob("*.enc"))
    if not enc_files:
        return 0

    new_samples = 0
    staging_jsonl.parent.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    for enc_path in enc_files:
        try:
            raw = decrypt_enc_file(vault_key, enc_path)
            entry = normalise_conversation(raw)
        except Exception as e:
            print(f"[WATCHER] SKIP {enc_path.name}: {e}", flush=True)
            continue

        if not dry_run:
            with staging_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Archive the processed file so it isn't re-processed on next poll
            dest = archive_dir / enc_path.name
            shutil.move(str(enc_path), str(dest))
        else:
            print(f"[WATCHER] [DRY-RUN] Would write: {json.dumps(entry)[:120]}...", flush=True)

        new_samples += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"[WATCHER] [{ts}] Decrypted → {enc_path.name} ({new_samples} new this drain)",
            flush=True,
        )

    return new_samples


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING TRIGGER
# ─────────────────────────────────────────────────────────────────────────────


def trigger_training(staging_jsonl: Path, dry_run: bool) -> bool:
    """
    Launch train_observer.py with the accumulated JSONL dataset.
    Returns True if training completed successfully.
    """
    # Pass the data path relative to the scripts/fine_tuning/ dir so that
    # train_observer.py's safe_resolve() can validate it against _DETERMINEX_ROOT.
    rel_data_path = os.path.relpath(staging_jsonl, _SCRIPT_DIR)

    cmd = [sys.executable, str(_TRAIN_SCRIPT), "--data_path", rel_data_path]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[WATCHER] [{ts}] Threshold reached — firing training forge.", flush=True)
    print(f"[WATCHER] Command: {' '.join(cmd)}\n", flush=True)

    if dry_run:
        print("[WATCHER] [DRY-RUN] Skipping actual training invocation.", flush=True)
        return True

    result = subprocess.run(cmd, cwd=str(_SCRIPT_DIR))
    if result.returncode == 0:
        print("[WATCHER] Training run completed successfully.", flush=True)
        return True
    else:
        print(f"[WATCHER] Training run exited with code {result.returncode}.", flush=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────


def run(args: argparse.Namespace) -> None:
    outbox_dir = Path(args.outbox).expanduser().resolve()
    vault_path = Path(args.vault).expanduser().resolve()
    staging_jsonl = Path(args.staging).expanduser().resolve()
    archive_dir = Path(args.archive).expanduser().resolve()
    threshold = args.threshold
    poll_secs = args.poll_secs
    dry_run = args.dry_run
    once = args.once

    print("[WATCHER] Determinex Training Flywheel Watcher", flush=True)
    print(f"[WATCHER] Outbox  : {outbox_dir}", flush=True)
    print(f"[WATCHER] Staging : {staging_jsonl}", flush=True)
    print(f"[WATCHER] Archive : {archive_dir}", flush=True)
    print(f"[WATCHER] Threshold: {threshold} new samples per training run", flush=True)
    if dry_run:
        print(
            "[WATCHER] DRY-RUN mode — no files will be written or training triggered.", flush=True
        )

    if not outbox_dir.exists():
        print(f"[WATCHER] Outbox directory does not exist yet: {outbox_dir}", flush=True)
        print(
            "[WATCHER] Waiting for the Determinex app to create it on first training pair...",
            flush=True,
        )

    vault_key: bytes | None = None
    state = load_state()

    while True:
        if outbox_dir.exists() and any(outbox_dir.glob("*.enc")):
            # Load the vault key on first actual use, not at startup.
            # This lets the watcher boot before the Tauri app has run once.
            if vault_key is None:
                vault_key = load_vault_key(vault_path)
                print("[WATCHER] Vault key loaded.", flush=True)

        if outbox_dir.exists() and vault_key is not None:
            new = drain_outbox(outbox_dir, vault_key, staging_jsonl, archive_dir, dry_run)
            if new > 0:
                state["total_decrypted"] += new
                if not dry_run:
                    save_state(state)

                total_samples = count_jsonl_lines(staging_jsonl)
                since_last = total_samples - state["samples_at_last_train"]

                print(
                    f"[WATCHER] Dataset: {total_samples} total samples "
                    f"({since_last} since last train, threshold {threshold})",
                    flush=True,
                )

                if since_last >= threshold:
                    success = trigger_training(staging_jsonl, dry_run)
                    if success and not dry_run:
                        state["samples_at_last_train"] = total_samples
                        state["training_runs"] += 1
                        save_state(state)
                        print(
                            f"[WATCHER] Training run #{state['training_runs']} complete. "
                            f"Counter reset at {total_samples} samples.",
                            flush=True,
                        )

        if once:
            print("[WATCHER] --once flag set. Exiting.", flush=True)
            break

        time.sleep(poll_secs)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Determinex forge watcher — auto-triggers LoRA fine-tuning when outbox fills."
    )
    parser.add_argument(
        "--outbox",
        default=str(_DEFAULT_OUTBOX),
        help=f"Path to the encrypted outbox directory (default: {_DEFAULT_OUTBOX})",
    )
    parser.add_argument(
        "--vault",
        default=str(_DEFAULT_VAULT),
        help=f"Path to vault.key (default: {_DEFAULT_VAULT})",
    )
    parser.add_argument(
        "--staging",
        default=str(_DEFAULT_STAGING),
        help=f"Destination JSONL path for decrypted training data (default: {_DEFAULT_STAGING})",
    )
    parser.add_argument(
        "--archive",
        default=str(_DEFAULT_ARCHIVE),
        help=f"Directory to archive processed .enc files (default: {_DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=50,
        help="Number of new samples to accumulate before triggering training (default: 50)",
    )
    parser.add_argument(
        "--poll-secs",
        type=int,
        default=30,
        help="Seconds between outbox polls (default: 30)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain the outbox once and exit (no polling loop)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt and print samples without writing to disk or triggering training",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
