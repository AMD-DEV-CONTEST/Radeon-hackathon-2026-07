use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::os::unix::fs::PermissionsExt;

pub enum ForgeCredentialProvider {
    EnvVar,
    CredentialsFile(String),
    MissingCredential,
}

pub struct CredentialsParser;

impl CredentialsParser {
    /// Primary entry point used by the worker.
    /// Priority: Environment Variable → credentials.sh → MissingCredential.
    pub fn get_credentials() -> (ForgeCredentialProvider, Vec<String>) {
        if env::var("AMD_CLOUD_USER").is_ok() && env::var("AMD_CLOUD_PASS").is_ok() {
            return (
                ForgeCredentialProvider::EnvVar,
                vec![
                    "AMD_CLOUD_USER".to_string(),
                    "AMD_CLOUD_PASS".to_string(),
                ],
            );
        }
        let path = env::var("FORGE_CREDENTIALS_PATH")
            .unwrap_or_else(|_| "credentials.sh".to_string());
        Self::get_credentials_from(&path)
    }

    /// Parse a specific credentials file path.
    /// Used directly by tests to supply an isolated file.
    pub fn get_credentials_from(path: &str) -> (ForgeCredentialProvider, Vec<String>) {
        if !Path::new(path).exists() {
            return (ForgeCredentialProvider::MissingCredential, vec![]);
        }

        let metadata = match std::fs::metadata(path) {
            Ok(m) => m,
            Err(_) => return (ForgeCredentialProvider::MissingCredential, vec![]),
        };
        let mode = metadata.permissions().mode();

        // Require 600 or 400 — no group/other bits.
        if mode & 0o077 != 0 {
            println!(
                "[WARNING] {} has permissive permissions (mode {:o}). Rejecting.",
                path, mode
            );
            return (ForgeCredentialProvider::MissingCredential, vec![]);
        }

        let file = match File::open(path) {
            Ok(f) => f,
            Err(_) => return (ForgeCredentialProvider::MissingCredential, vec![]),
        };
        let reader = BufReader::new(file);
        let mut keys = Vec::new();

        for line in reader.lines() {
            let l = match line {
                Ok(l) => l,
                Err(_) => return (ForgeCredentialProvider::MissingCredential, vec![]),
            };
            let trimmed = l.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }

            // Reject any shell metacharacters that could trigger execution.
            if trimmed.contains('$')
                || trimmed.contains('|')
                || trimmed.contains('<')
                || trimmed.contains('>')
                || trimmed.contains('\\')
                || trimmed.contains('`')
            {
                println!(
                    "[ERROR] Shell execution detected in credentials file line. Rejecting."
                );
                return (ForgeCredentialProvider::MissingCredential, vec![]);
            }

            if let Some((key, _)) = trimmed.split_once('=') {
                let k = key.trim();
                if k.contains(' ') {
                    println!("[ERROR] Invalid KEY format in credentials file. Rejecting.");
                    return (ForgeCredentialProvider::MissingCredential, vec![]);
                }
                keys.push(k.to_string());
            }
        }

        if keys.contains(&"AMD_CLOUD_USER".to_string())
            && keys.contains(&"AMD_CLOUD_PASS".to_string())
        {
            return (
                ForgeCredentialProvider::CredentialsFile(path.to_string()),
                keys,
            );
        }

        (ForgeCredentialProvider::MissingCredential, vec![])
    }
}
