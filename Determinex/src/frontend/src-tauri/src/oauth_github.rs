//! GitHub OAuth via the Device Authorization Grant (RFC 8628).
//!
//! Ryan registered the OAuth App and supplied the client id, so this replaces
//! "paste a personal access token" with a real sign-in.
//!
//! Device Flow specifically, not the web/redirect flow, because:
//!   * a desktop app cannot keep a client secret -- shipping one in the binary
//!     is the same as publishing it, and Device Flow needs no secret at all;
//!   * it needs no loopback HTTP server and no custom URL-scheme registration,
//!     both of which are extra attack surface and extra Windows install steps.
//!
//! The client id is NOT a secret. It is transmitted in plaintext as part of
//! every device-code request and is visible to anyone who inspects the traffic;
//! GitHub's own docs treat it as public. It is still overridable via
//! DETERMINEX_GITHUB_CLIENT_ID so a fork can point at its own app.
//!
//! The resulting token is written to the SAME `api_keys` row that
//! `save_service_key("GITHUB", ...)` uses (`GITHUB_TOKEN`), so a token obtained
//! by signing in is indistinguishable downstream from one pasted by hand --
//! `get_api_key_status`, the Passport panel and every git integration keep
//! working with no further wiring.

use serde::{Deserialize, Serialize};
use tauri::State;

use crate::db::DbState;

const DEFAULT_CLIENT_ID: &str = "Ov23liC1d8R3BCGzhDFu";
const DEVICE_CODE_URL: &str = "https://github.com/login/device/code";
const ACCESS_TOKEN_URL: &str = "https://github.com/login/oauth/access_token";
/// `repo` for git operations, `read:user` to show who is signed in.
const SCOPES: &str = "repo read:user";


/// Minimal `application/x-www-form-urlencoded` body builder.
///
/// reqwest's `.form()` is not available in this build's feature set, and
/// guessing at feature flags to get it would be a worse dependency change than
/// six lines of encoding. Only the unreserved set is left as-is; everything
/// else is percent-encoded, which covers the space in `scope` and the colons
/// and slashes in the device-flow `grant_type` URN.
fn form_body(pairs: &[(&str, &str)]) -> String {
    fn enc(s: &str) -> String {
        s.bytes()
            .map(|b| match b {
                b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                    (b as char).to_string()
                }
                _ => format!("%{b:02X}"),
            })
            .collect()
    }
    pairs
        .iter()
        .map(|(k, v)| format!("{}={}", enc(k), enc(v)))
        .collect::<Vec<_>>()
        .join("&")
}

const FORM_CT: &str = "application/x-www-form-urlencoded";

fn client_id() -> String {
    std::env::var("DETERMINEX_GITHUB_CLIENT_ID").unwrap_or_else(|_| DEFAULT_CLIENT_ID.to_string())
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeviceCodeStart {
    /// Shown to the user to type into GitHub.
    pub user_code: String,
    /// Where they type it.
    pub verification_uri: String,
    /// Opaque handle the poll step needs. Not shown to the user.
    pub device_code: String,
    /// Minimum seconds between polls, per RFC 8628.
    pub interval: u64,
    pub expires_in: u64,
}

#[derive(Deserialize)]
struct RawDeviceCode {
    device_code: String,
    user_code: String,
    verification_uri: String,
    expires_in: u64,
    interval: u64,
}

/// Step 1: ask GitHub for a device code + a user code to display.
#[tauri::command]
pub async fn github_device_start() -> Result<DeviceCodeStart, String> {
    let res = reqwest::Client::new()
        .post(DEVICE_CODE_URL)
        // Without this GitHub replies form-encoded and serde sees garbage.
        .header("Accept", "application/json")
        .header("Content-Type", FORM_CT)
        .body(form_body(&[("client_id", &client_id()), ("scope", SCOPES)]))
        .send()
        .await
        .map_err(|e| format!("could not reach GitHub: {e}"))?;

    let status = res.status();
    let body = res.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!("GitHub returned {status}: {body}"));
    }
    // A 200 can still carry an error object (e.g. device flow disabled on the app).
    if let Ok(err) = serde_json::from_str::<serde_json::Value>(&body) {
        if let Some(e) = err.get("error").and_then(|v| v.as_str()) {
            if e == "device_flow_disabled" {
                return Err(
                    "This GitHub OAuth App does not have Device Flow enabled. \
                     Turn it on under the app's General → Device flow setting."
                        .to_string(),
                );
            }
            return Err(format!(
                "GitHub refused the device-code request: {e}{}",
                err.get("error_description")
                    .and_then(|v| v.as_str())
                    .map(|d| format!(" ({d})"))
                    .unwrap_or_default()
            ));
        }
    }

    let raw: RawDeviceCode =
        serde_json::from_str(&body).map_err(|e| format!("malformed device-code response: {e}"))?;

    Ok(DeviceCodeStart {
        user_code: raw.user_code,
        verification_uri: raw.verification_uri,
        device_code: raw.device_code,
        interval: raw.interval.max(1),
        expires_in: raw.expires_in,
    })
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevicePoll {
    /// "pending" | "slow_down" | "authorized" | "denied" | "expired"
    pub status: String,
    /// Present only when the caller should back off further.
    pub interval: Option<u64>,
    pub message: Option<String>,
}

/// Step 2: poll until the user finishes in the browser.
///
/// Returns a *status*, never the token: on success the token is stored
/// server-side in the same row a pasted PAT uses, so it never crosses the IPC
/// boundary into JS memory or a devtools network pane.
#[tauri::command]
pub async fn github_device_poll(
    device_code: String,
    state: State<'_, DbState>,
) -> Result<DevicePoll, String> {
    let res = reqwest::Client::new()
        .post(ACCESS_TOKEN_URL)
        .header("Accept", "application/json")
        .header("Content-Type", FORM_CT)
        .body(form_body(&[
            ("client_id", &client_id()),
            ("device_code", &device_code),
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
        ]))
        .send()
        .await
        .map_err(|e| format!("could not reach GitHub: {e}"))?;

    let body = res.text().await.unwrap_or_default();
    let json: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("malformed token response: {e}"))?;

    if let Some(err) = json.get("error").and_then(|v| v.as_str()) {
        // These are the normal, expected states of a device flow in progress --
        // not failures. Reporting them as errors is what makes a sign-in dialog
        // look broken while it is simply waiting for the user.
        return Ok(match err {
            "authorization_pending" => DevicePoll {
                status: "pending".into(),
                interval: None,
                message: None,
            },
            "slow_down" => DevicePoll {
                status: "slow_down".into(),
                interval: json.get("interval").and_then(|v| v.as_u64()),
                message: None,
            },
            "expired_token" => DevicePoll {
                status: "expired".into(),
                interval: None,
                message: Some("The code expired. Start again.".into()),
            },
            "access_denied" => DevicePoll {
                status: "denied".into(),
                interval: None,
                message: Some("Authorization was declined on GitHub.".into()),
            },
            other => DevicePoll {
                status: "denied".into(),
                interval: None,
                message: Some(format!("GitHub returned: {other}")),
            },
        });
    }

    let token = json
        .get("access_token")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "GitHub response contained no access_token".to_string())?;

    // Same row as save_service_key("GITHUB", ..) so everything downstream --
    // get_api_key_status, Passport, git integrations -- sees it immediately.
    {
        let conn = state
            .conn
            .lock()
            .map_err(|e| format!("DbState mutex poisoned: {e}"))?;
        conn.execute(
            "INSERT INTO api_keys (provider, api_key) VALUES (?1, ?2)
             ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP",
            ("GITHUB_TOKEN", token),
        )
        .map_err(|e| format!("could not store token: {e}"))?;
    }

    Ok(DevicePoll {
        status: "authorized".into(),
        interval: None,
        message: None,
    })
}


/// Open the GitHub verification page in the user's browser.
///
/// Deliberately NOT a general "open any URL" command. An unrestricted opener
/// reachable from the webview is a launcher for arbitrary URIs, so this accepts
/// only https://github.com/... -- enough for the device-flow page and nothing
/// else. The user can always copy the code and navigate manually.
#[tauri::command]
pub fn github_open_verification(url: String) -> Result<(), String> {
    if !url.starts_with("https://github.com/") {
        return Err(format!("refusing to open a non-GitHub URL: {url}"));
    }
    opener::open(&url).map_err(|e| format!("could not open browser: {e}"))
}

/// Forget the stored token. Sign-out has to exist wherever sign-in does.
#[tauri::command]
pub fn github_sign_out(state: State<'_, DbState>) -> Result<(), String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {e}"))?;
    conn.execute("DELETE FROM api_keys WHERE provider = ?1", ("GITHUB_TOKEN",))
        .map_err(|e| format!("could not clear token: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn client_id_defaults_to_the_registered_app() {
        // Public by design -- it is sent in cleartext on every device-code
        // request. Pinned so a typo cannot silently break sign-in.
        std::env::remove_var("DETERMINEX_GITHUB_CLIENT_ID");
        assert_eq!(client_id(), "Ov23liC1d8R3BCGzhDFu");
    }

    #[test]
    fn client_id_is_overridable_for_forks() {
        std::env::set_var("DETERMINEX_GITHUB_CLIENT_ID", "Iv1_someotherapp");
        assert_eq!(client_id(), "Iv1_someotherapp");
        std::env::remove_var("DETERMINEX_GITHUB_CLIENT_ID");
    }

    #[test]
    fn verification_opener_refuses_non_github_urls() {
        // This command is reachable from the webview; it must not become a
        // general-purpose URI launcher.
        assert!(github_open_verification("https://evil.example/x".into()).is_err());
        assert!(github_open_verification("file:///C:/Windows/System32".into()).is_err());
        assert!(github_open_verification("http://github.com/login".into()).is_err()); // not https
    }

    #[test]
    fn form_body_percent_encodes_reserved_characters() {
        // The space in `scope` and the colons in the grant_type URN must be
        // encoded or GitHub parses the parameters wrong.
        let b = form_body(&[("scope", "repo read:user")]);
        assert_eq!(b, "scope=repo%20read%3Auser");
        let g = form_body(&[("grant_type", "urn:ietf:params:oauth:grant-type:device_code")]);
        assert!(g.contains("%3A"), "colons must be encoded: {g}");
        assert!(!g.contains(":"), "raw colon leaked into body: {g}");
    }

    #[test]
    fn form_body_joins_pairs_with_ampersands() {
        assert_eq!(form_body(&[("a", "1"), ("b", "2")]), "a=1&b=2");
    }

    #[test]
    fn requests_only_the_scopes_it_needs() {
        // repo for git operations, read:user for identity. No admin, no delete,
        // no org scopes -- a token minted here cannot do more than the app does.
        assert_eq!(SCOPES, "repo read:user");
        assert!(!SCOPES.contains("admin"));
        assert!(!SCOPES.contains("delete"));
    }
}
