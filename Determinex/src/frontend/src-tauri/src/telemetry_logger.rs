/// telemetry_logger.rs — Vanguard Vault: Encrypted DPO Training Data Flywheel
///
/// Every time the Determinex pipeline recovers from a compiler failure — i.e. the
/// Engineer produces broken code, the Observer identifies the error, and a
/// subsequent attempt produces accepted code — this module captures the
/// (bad_code, compiler_error) → good_code transition as a ShareGPT-format
/// training pair, encrypts it locally, and writes it to an outbox.
///
/// ENCRYPTION MODEL (Vanguard Vault):
///   Algorithm: AES-256-GCM (AEAD — authenticated encryption with associated data)
///   Key storage: <workspace_root>/.determinex_staging/vault/vault.key
///   The key is generated once on first run using OsRng (CSPRNG) and stays on
///   the user's machine. No key ever leaves the device in plaintext.
///   The payload envelope format is:
///     Base64( nonce[12 bytes] || ciphertext[n bytes] || GCM-tag[16 bytes] )
///   The nonce is freshly randomised for every payload (nonce reuse would break
///   AES-GCM confidentiality — this design prevents that structurally).
///
/// OUTBOX LAYOUT:
///   .determinex_staging/
///     vault/
///       vault.key                        ← 256-bit AES key (binary, never leaves device)
///     outbox/
///       telemetry_<timestamp>.enc        ← Base64(nonce || ciphertext)
///
/// The plaintext JSONL dataset path is NO LONGER WRITTEN. All output goes
/// to the encrypted outbox. A future `determinex-forge decrypt-outbox` CLI
/// command (using the local vault.key) will reconstitute the JSONL for training.
use std::io::Write;
use std::path::Path;

use aes_gcm::{
    aead::{Aead, AeadCore, KeyInit, OsRng},
    Aes256Gcm, Key,
};
use base64::{engine::general_purpose::STANDARD as B64, Engine as _};

// ─────────────────────────────────────────────────────────────────────────────
// VAULT KEY MANAGEMENT
// ─────────────────────────────────────────────────────────────────────────────

/// Load the AES-256-GCM key from disk, or generate and persist a fresh one.
///
/// The key file contains exactly 32 raw bytes — no encoding, no header.
/// Generation uses `OsRng` (CSPRNG backed by the OS entropy source: CryptGenRandom
/// on Windows, getrandom/urandom on Linux/macOS).
///
/// # Security note
/// The key file should be protected by OS-level permissions. On a single-user
/// machine this is satisfied by the user's home directory ACL. A future hardening
/// pass could seal it inside the OS keychain (Windows DPAPI / macOS Keychain).
fn load_or_generate_key(workspace_root: &Path) -> Result<[u8; 32], String> {
    let vault_dir = workspace_root.join(".determinex_staging").join("vault");
    std::fs::create_dir_all(&vault_dir)
        .map_err(|e| format!("[VAULT] Failed to create vault dir: {}", e))?;

    let key_path = vault_dir.join("vault.key");

    if key_path.exists() {
        let raw = std::fs::read(&key_path)
            .map_err(|e| format!("[VAULT] Failed to read vault.key: {}", e))?;

        if raw.len() != 32 {
            return Err(format!(
                "[VAULT] vault.key is corrupt ({} bytes, expected 32). Delete it to regenerate.",
                raw.len()
            ));
        }

        let mut key_bytes = [0u8; 32];
        key_bytes.copy_from_slice(&raw);
        return Ok(key_bytes);
    }

    // First run: generate a fresh 256-bit key from OS entropy.
    log::info!(
        "[VAULT] Generating new AES-256-GCM vault key at: {}",
        key_path.display()
    );
    let key = Aes256Gcm::generate_key(OsRng);
    let key_bytes: [u8; 32] = key.into();

    std::fs::write(&key_path, &key_bytes)
        .map_err(|e| format!("[VAULT] Failed to persist vault.key: {}", e))?;

    log::info!("[VAULT] vault.key written. Protect this file — it is the only decryption key.");
    Ok(key_bytes)
}

// ─────────────────────────────────────────────────────────────────────────────
// ENCRYPTION
// ─────────────────────────────────────────────────────────────────────────────

/// Encrypt a JSON string payload using AES-256-GCM.
///
/// Returns a Base64-encoded string of the form:
///   Base64( nonce[12 bytes] || ciphertext + GCM-tag[n+16 bytes] )
///
/// The nonce is freshly generated for each call. Nonce reuse under the same
/// key would catastrophically break AES-GCM — generating a new nonce per
/// payload makes this structurally impossible.
pub fn encrypt_payload(workspace_root: &Path, json_string: &str) -> Result<String, String> {
    let key_bytes = load_or_generate_key(workspace_root)?;

    let key = Key::<Aes256Gcm>::from_slice(&key_bytes);
    let cipher = Aes256Gcm::new(key);

    // Fresh 96-bit (12-byte) random nonce — AES-GCM standard nonce size.
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);

    let ciphertext = cipher
        .encrypt(&nonce, json_string.as_bytes())
        .map_err(|e| format!("[VAULT] AES-GCM encryption failed: {:?}", e))?;

    // Envelope: prepend the nonce so the decryptor can reconstruct it.
    // Layout: nonce[0..12] || ciphertext+tag[12..]
    let mut envelope = nonce.to_vec();
    envelope.extend_from_slice(&ciphertext);

    Ok(B64.encode(&envelope))
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Capture one DPO training pair, encrypt it, and write it to the outbox.
///
/// The record is formatted in the ShareGPT multi-turn conversation schema before
/// encryption:
/// ```json
/// {
///   "conversations": [
///     {"from": "system",    "value": "<system_prompt>"},
///     {"from": "user",      "value": "The following code failed...<bad_code>...<error>..."},
///     {"from": "assistant", "value": "<good_code>"}
///   ]
/// }
/// ```
///
/// The encrypted payload is written to:
///   `.determinex_staging/outbox/telemetry_<unix_timestamp_ms>.enc`
///
/// The outbox directory is created on first use. The `.enc` extension signals
/// that the file must be decrypted with the vault key before training use.
pub fn log_training_pair(
    workspace_root: &Path,
    system_prompt: &str,
    bad_code: &str,
    compiler_error: &str,
    good_code: &str,
) -> Result<(), String> {
    // ── Build plaintext ShareGPT entry ──────────────────────────────────────
    let user_message = format!(
        "The following code failed compilation.\n\nCode:\n{}\n\nError:\n{}\n\nOutput the corrected code.",
        bad_code, compiler_error
    );

    let entry = serde_json::json!({
        "conversations": [
            { "from": "system",    "value": system_prompt },
            { "from": "user",      "value": user_message  },
            { "from": "assistant", "value": good_code      }
        ]
    });

    let plaintext = serde_json::to_string(&entry)
        .map_err(|e| format!("[TELEMETRY] Failed to serialize training pair: {}", e))?;

    // ── Encrypt ─────────────────────────────────────────────────────────────
    let encrypted = encrypt_payload(workspace_root, &plaintext)?;

    // ── Write to outbox ─────────────────────────────────────────────────────
    let outbox_dir = workspace_root.join(".determinex_staging").join("outbox");

    std::fs::create_dir_all(&outbox_dir)
        .map_err(|e| format!("[TELEMETRY] Failed to create outbox dir: {}", e))?;

    // Millisecond timestamp gives unique filenames even under rapid successive calls.
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);

    let filename = format!("telemetry_{}.enc", ts);
    let outbox_path = outbox_dir.join(&filename);

    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        // Truncate — each `.enc` file contains exactly one payload.
        .truncate(true)
        .open(&outbox_path)
        .map_err(|e| {
            format!(
                "[TELEMETRY] Failed to open outbox file {}: {}",
                outbox_path.display(),
                e
            )
        })?;

    writeln!(file, "{}", encrypted).map_err(|e| {
        format!(
            "[TELEMETRY] Write failed on {}: {}",
            outbox_path.display(),
            e
        )
    })?;

    log::info!(
        "[TELEMETRY] Encrypted training pair written → {}",
        outbox_path.display()
    );
    Ok(())
}
