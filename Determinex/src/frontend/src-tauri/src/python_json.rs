//! Tolerant JSON extraction from a Python child process's stdout.
//!
//! Every Rust bridge in this app shells out to a Python script and then hands
//! the *entire* stdout to `serde_json::from_str`. That treats stdout as a
//! strict, single-value channel -- which it is by convention, and isn't in
//! practice, because any library anywhere under that script can `print()`.
//!
//! This is not hypothetical. `build_idea` reaches
//! `determinex_verified_search`, whose per-sample progress lines
//! ("[vs] r1 s1/6 t=0.0 gen 3s verify 1s -> 1 fail") go to stdout. A real run
//! emitted 12 of them ahead of a perfectly valid response and the whole thing
//! was rejected with "expected value at line 1 column 6" -- column 6 being the
//! "[vs]" prefix. The work had been done; only the transport failed.
//!
//! `scripts/ide/_tauri_driver.py` was fixed to redirect stdout during dispatch,
//! but that only protects the one bridge that goes through it. The other
//! scripts (agent registry, agent chat, hive workspace, passport, toolchain
//! installer, project audit) each have their own entrypoint and no such
//! guarantee, so this makes the Rust side resilient regardless of what any
//! script decides to print.
//!
//! Policy: prefer the whole buffer (the correct, common case); otherwise take
//! the LAST line that parses, because these scripts print their result last
//! and any noise precedes it. Never silently return a default -- an
//! unparseable buffer is still an error, and the message quotes the leading
//! noise so the offending print is easy to find.

use serde::de::DeserializeOwned;

/// Longest prefix of stray output quoted back in an error message.
const NOISE_PREVIEW: usize = 200;

/// Parse `stdout` as JSON, tolerating stray non-JSON lines before the payload.
pub fn parse_python_json<T: DeserializeOwned>(stdout: &str, what: &str) -> Result<T, String> {
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return Err(format!("{what}: the script produced no output on stdout"));
    }

    // Fast path: a well-behaved script whose stdout is exactly one JSON value.
    if let Ok(v) = serde_json::from_str::<T>(trimmed) {
        return Ok(v);
    }

    // Fall back to the last line that parses. Last, not first: the result is
    // printed after any progress output, and an early line could itself be
    // valid JSON (a progress record, say) that is not the response.
    let mut noise: Vec<&str> = Vec::new();
    for line in trimmed.lines().rev() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if let Ok(v) = serde_json::from_str::<T>(line) {
            return Ok(v);
        }
        noise.push(line);
    }

    // Nothing parsed. Report the real error against the whole buffer, and quote
    // the head of the output so the stray print is identifiable.
    // `.err()` rather than `.unwrap_err()`: the latter formats the Ok value on
    // failure and would force a `T: Debug` bound on every caller.
    let err = match serde_json::from_str::<T>(trimmed).err() {
        Some(e) => e.to_string(),
        None => "unexpected: buffer parsed on retry".to_string(),
    };
    let mut preview: String = trimmed.chars().take(NOISE_PREVIEW).collect();
    if trimmed.chars().count() > NOISE_PREVIEW {
        preview.push_str(" ...");
    }
    Err(format!(
        "{what}: no JSON found in script output ({err}). stdout began: {preview}"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Debug, Deserialize, PartialEq)]
    struct Resp {
        ok: bool,
        n: u32,
    }

    #[test]
    fn parses_clean_single_value_stdout() {
        let got: Resp = parse_python_json(r#"{"ok":true,"n":1}"#, "test").unwrap();
        assert_eq!(got, Resp { ok: true, n: 1 });
    }

    #[test]
    fn tolerates_surrounding_whitespace() {
        let got: Resp = parse_python_json("\n  {\"ok\":true,\"n\":2}  \n", "test").unwrap();
        assert_eq!(got.n, 2);
    }

    /// The exact shape that broke build_idea in production.
    #[test]
    fn skips_progress_lines_printed_before_the_payload() {
        let stdout = concat!(
            "    [vs] r1 s1/6 t=0.0 gen 3s verify 1s -> 1 fail (score 0.00)\n",
            "    [vs] r1 s2/6 t=0.2 gen 4s -> duplicate, skipped\n",
            "{\"ok\":true,\"n\":12}\n"
        );
        let got: Resp = parse_python_json(stdout, "build").unwrap();
        assert_eq!(got, Resp { ok: true, n: 12 });
    }

    /// Last-not-first matters: an earlier line can be valid JSON of the same
    /// shape without being the response.
    #[test]
    fn prefers_the_last_parsable_line() {
        let stdout = "{\"ok\":false,\"n\":1}\nnoise\n{\"ok\":true,\"n\":99}\n";
        let got: Resp = parse_python_json(stdout, "test").unwrap();
        assert_eq!(got.n, 99, "must take the final record, not an earlier one");
    }

    #[test]
    fn empty_stdout_is_an_error_not_a_default() {
        let got = parse_python_json::<Resp>("   \n ", "test");
        assert!(got.is_err());
        assert!(got.unwrap_err().contains("no output"));
    }

    #[test]
    fn unparseable_output_errors_and_quotes_the_noise() {
        let got = parse_python_json::<Resp>("Traceback (most recent call last):\n  File ...", "cmd");
        let err = got.unwrap_err();
        assert!(err.contains("no JSON found"));
        assert!(err.contains("Traceback"), "error should quote the real output: {err}");
    }

    /// A JSON value that parses but is the wrong shape must NOT be accepted
    /// just because it is syntactically valid.
    #[test]
    fn wrong_shape_is_rejected() {
        assert!(parse_python_json::<Resp>(r#"{"unrelated":1}"#, "test").is_err());
    }
}
