/// ast_editor.rs — Tree-sitter powered surgical code edits.
///
/// The Problem:
///   At num_ctx: 2048, rewriting a 400-line file consumes the entire context
///   window and risks Context Amnesia — the LLM forgets the earlier parts of
///   the code it is writing. Result: truncated output, missing closing braces,
///   half-finished implementations.
///
/// The Solution:
///   The Engineer outputs a targeted function replacement instead of the full
///   file. This module uses tree-sitter to parse the existing source and splice
///   in only the changed function — reducing the Engineer's required output from
///   ~1000 tokens to ~50 tokens.
///
/// Fallback (Phase 1):
///   When tree-sitter fails on broken syntax (missing brace, half-finished impl
///   block, corrupted AST from a crashed Builder attempt), we fall back to
///   regex/line-number brace-counting.  The parse_mode:"degraded" marker in the
///   manifest alerts downstream consumers that the edit was approximate.
///
/// Supported languages:  Rust  (TypeScript grammar can be added via tree-sitter-javascript)
use regex::Regex;
use std::sync::OnceLock;
use tree_sitter::{Node, Parser};

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC API
// ─────────────────────────────────────────────────────────────────────────────

/// Replace the named function `function_name` in `source` with `new_function`.
///
/// `source`        — complete current file content
/// `language`      — "rust" (other languages return Err)
/// `function_name` — exact identifier of the function to replace
/// `new_function`  — complete replacement: signature + body (no need to match indentation)
///
/// Returns the full source string with only the target function swapped, or
/// an error describing why the edit could not be applied.
pub fn replace_function(
    source: &str,
    language: &str,
    function_name: &str,
    new_function: &str,
) -> Result<String, String> {
    let lang = resolve_language(language)?;

    let mut parser = Parser::new();
    parser
        .set_language(&lang)
        .map_err(|e| format!("tree-sitter grammar load failed: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("tree-sitter failed to parse source")?;

    let fn_node = find_named_function(tree.root_node(), source.as_bytes(), function_name)
        .ok_or_else(|| {
            format!(
                "Function '{}' not found in source ({} bytes)",
                function_name,
                source.len()
            )
        })?;

    let start_byte = fn_node.start_byte();
    let end_byte = fn_node.end_byte();

    // Detect and preserve the indentation of the replaced function so the
    // new code aligns with its surroundings without needing the Engineer to
    // count spaces.
    let indent = detect_indent(source, start_byte);
    let indented = apply_indent(new_function.trim(), &indent);

    let mut result = String::with_capacity(source.len() + new_function.len());
    result.push_str(&source[..start_byte]);
    result.push_str(&indented);
    result.push_str(&source[end_byte..]);

    log::info!(
        "[AST] Spliced '{}' ({} → {} bytes)",
        function_name,
        end_byte - start_byte,
        indented.len()
    );

    Ok(result)
}

/// High-level replacement: tries tree-sitter first, falls back to regex on failure.
///
/// Returns `(new_source, parse_mode)` where parse_mode is `"normal"` or `"degraded"`.
///
/// This is the function the Python side (`determinex_hive.py`) should call via IPC.
/// The separate `replace_function` and `replace_function_regex_fallback` remain
/// available for testing each path individually.
#[allow(dead_code)]
pub fn replace_function_with_fallback(
    source: &str,
    language: &str,
    function_name: &str,
    new_function: &str,
) -> Result<(String, &'static str), String> {
    // Try tree-sitter first
    match replace_function(source, language, function_name, new_function) {
        Ok(result) => return Ok((result, "normal")),
        Err(ts_err) => {
            log::warn!(
                "[AST] tree-sitter failed for '{}': {} — trying regex fallback",
                function_name,
                ts_err
            );
        }
    }

    // Regex fallback
    replace_function_regex_fallback(source, function_name, new_function)
}

/// Extract all top-level function/struct/enum/trait/impl signatures from source.
///
/// Returns `(signatures, parse_mode)`.  `parse_mode` is `"normal"` if tree-sitter
/// succeeded, `"degraded"` if we fell back to regex.
#[allow(dead_code)]
pub fn extract_signatures(source: &str, language: &str) -> (Vec<String>, &'static str) {
    // Try tree-sitter first
    if let Ok(lang) = resolve_language(language) {
        let mut parser = Parser::new();
        if parser.set_language(&lang).is_ok() {
            if let Some(tree) = parser.parse(source, None) {
                let root = tree.root_node();
                // Check error ratio — if >20% ERROR nodes, fall back
                let n_children = root.child_count();
                let n_errors = (0..n_children)
                    .filter(|&i| {
                        root.child(i as u32)
                            .map_or(false, |c| c.is_error() || c.is_missing())
                    })
                    .count();
                if n_children == 0 || n_errors * 5 <= n_children {
                    let mut sigs = Vec::new();
                    collect_signatures_ts(root, source.as_bytes(), &mut sigs);
                    return (sigs, "normal");
                }
            }
        }
    }

    log::warn!("[AST] tree-sitter parse failed for signature extraction — using regex fallback");
    (extract_signatures_regex(source, language), "degraded")
}

// ─────────────────────────────────────────────────────────────────────────────
// GRAMMAR RESOLUTION
// ─────────────────────────────────────────────────────────────────────────────

fn resolve_language(language: &str) -> Result<tree_sitter::Language, String> {
    match language.to_lowercase().as_str() {
        "rust" => Ok(tree_sitter_rust::language()),
        other => Err(format!("AST editing not supported for '{}'", other)),
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TREE TRAVERSAL
// ─────────────────────────────────────────────────────────────────────────────

/// Depth-first search for the first `function_item` node whose `name` field
/// byte-matches `function_name` exactly.
fn find_named_function<'a>(node: Node<'a>, source: &[u8], function_name: &str) -> Option<Node<'a>> {
    // tree-sitter-rust uses "function_item" for top-level and impl functions.
    if node.kind() == "function_item" {
        if let Some(name_node) = node.child_by_field_name("name") {
            let name_bytes = &source[name_node.start_byte()..name_node.end_byte()];
            if name_bytes == function_name.as_bytes() {
                return Some(node);
            }
        }
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if let Some(found) = find_named_function(child, source, function_name) {
            return Some(found);
        }
    }

    None
}

/// Collect signatures from tree-sitter AST.  Extracts text up to the first `{`
/// for function/struct/enum/trait/impl items.
#[allow(dead_code)]
fn collect_signatures_ts(node: Node, source: &[u8], acc: &mut Vec<String>) {
    let is_item = matches!(
        node.kind(),
        "function_item" | "struct_item" | "enum_item" | "trait_item" | "impl_item"
    );

    if is_item {
        let line_num = node.start_position().row + 1;
        let start = node.start_byte();
        let node_bytes = &source[start..node.end_byte()];
        let sig_end = node_bytes
            .iter()
            .position(|&b| b == b'{')
            .unwrap_or(node_bytes.len());
        let sig_text = String::from_utf8_lossy(&node_bytes[..sig_end])
            .trim()
            .to_string();
        let truncated = if sig_text.len() > 150 {
            format!("{}...", &sig_text[..147])
        } else {
            sig_text
        };
        acc.push(format!("L{}: {}", line_num, truncated));
    }

    // Recurse into children (including impl blocks to find methods)
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        collect_signatures_ts(child, source, acc);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// INDENTATION UTILITIES
// ─────────────────────────────────────────────────────────────────────────────

/// Measure the whitespace prefix on the line that contains `byte_offset`.
fn detect_indent(source: &str, byte_offset: usize) -> String {
    let before = &source[..byte_offset];
    let line_start = before.rfind('\n').map(|i| i + 1).unwrap_or(0);
    source[line_start..byte_offset]
        .chars()
        .take_while(|c| c.is_whitespace())
        .collect()
}

/// Apply `indent` to every non-empty line of `code` except the first
/// (the first line inherits its indentation from the splice position in the
/// surrounding source).
fn apply_indent(code: &str, indent: &str) -> String {
    if indent.is_empty() {
        return code.to_string();
    }
    code.lines()
        .enumerate()
        .map(|(i, line)| {
            if line.is_empty() {
                String::new()
            } else if i == 0 {
                line.to_string() // first line: already at the right column
            } else {
                format!("{}{}", indent, line)
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

// ─────────────────────────────────────────────────────────────────────────────
// REGEX / LINE-NUMBER FALLBACK — when tree-sitter fails on broken syntax
// ─────────────────────────────────────────────────────────────────────────────
//
// Strategy:
//   1. Scan lines for `fn <function_name>` (with optional pub/async/unsafe prefixes).
//   2. From that line, count brace nesting: `{` increments, `}` decrements.
//   3. When the counter returns to 0 after being positive, we've found the end.
//   4. Splice the replacement at [start_line..end_line].
//
// This is lossy — it doesn't handle:
//   - functions whose name appears inside a string literal (spurious match)
//   - #[cfg] attributes preceding the fn (they'll be left in place)
//   - macro-generated function items
//
// But it's strictly better than "replace the entire file," which is the
// alternative when tree-sitter panics.

/// Attempt to replace a function using regex/brace-counting when tree-sitter
/// fails.  Returns `Ok((new_source, "degraded"))` on success,
/// `Err(reason)` if the function cannot be located at all.
#[allow(dead_code)]
pub fn replace_function_regex_fallback(
    source: &str,
    function_name: &str,
    new_function: &str,
) -> Result<(String, &'static str), String> {
    let lines: Vec<&str> = source.lines().collect();
    let fn_pattern = Regex::new(&format!(
        r"^\s*(?:pub\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+{}\s*[\(<]",
        regex::escape(function_name)
    ))
    .map_err(|e| format!("regex build failed: {}", e))?;

    // Phase 1: find the line containing the function signature
    let start_line = lines
        .iter()
        .position(|line| fn_pattern.is_match(line))
        .ok_or_else(|| {
            format!(
                "regex fallback: 'fn {}' not found in {} lines",
                function_name,
                lines.len()
            )
        })?;

    // Phase 2: walk backward to include doc comments and attributes
    let mut actual_start = start_line;
    while actual_start > 0 {
        let prev = lines[actual_start - 1].trim();
        if prev.starts_with("///")
            || prev.starts_with("#[")
            || prev.starts_with("//")
            || prev.is_empty()
        {
            actual_start -= 1;
        } else {
            break;
        }
    }
    // Don't swallow blank lines that separate this fn from the previous item
    while actual_start < start_line && lines[actual_start].trim().is_empty() {
        actual_start += 1;
    }

    // Phase 3: brace-count from fn signature line forward to find the closing `}`
    let mut depth: i32 = 0;
    let mut found_open = false;
    let mut end_line = start_line;

    for (i, line) in lines.iter().enumerate().skip(start_line) {
        for ch in line.chars() {
            match ch {
                '{' => {
                    depth += 1;
                    found_open = true;
                }
                '}' => {
                    depth -= 1;
                }
                _ => {}
            }
        }
        if found_open && depth <= 0 {
            end_line = i;
            break;
        }
    }

    if !found_open || depth > 0 {
        return Err(format!(
            "regex fallback: could not find balanced braces for '{}' starting at line {} \
             (depth={}, found_open={})",
            function_name,
            start_line + 1,
            depth,
            found_open
        ));
    }

    // Phase 4: detect indentation and apply to replacement
    let indent: String = lines[start_line]
        .chars()
        .take_while(|c| c.is_whitespace())
        .collect();
    let indented = apply_indent(new_function.trim(), &indent);

    // Phase 5: splice
    let mut result_lines: Vec<String> = Vec::with_capacity(lines.len());
    for line in &lines[..actual_start] {
        result_lines.push(line.to_string());
    }
    result_lines.push(indented);
    for line in &lines[end_line + 1..] {
        result_lines.push(line.to_string());
    }

    log::warn!(
        "[AST] regex fallback: spliced '{}' (lines {}-{} → replacement), parse_mode=degraded",
        function_name,
        actual_start + 1,
        end_line + 1
    );

    Ok((result_lines.join("\n"), "degraded"))
}

static RUST_SIGNATURES: OnceLock<Vec<(&'static str, Regex)>> = OnceLock::new();

fn rust_signature_patterns() -> &'static Vec<(&'static str, Regex)> {
    RUST_SIGNATURES.get_or_init(|| {
        vec![
            (
                "fn",
                Regex::new(r"^\s*(?:pub\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+\w+")
                    .expect("static regex"),
            ),
            (
                "struct",
                Regex::new(r"^\s*(?:pub\s+)?struct\s+\w+").expect("static regex"),
            ),
            (
                "enum",
                Regex::new(r"^\s*(?:pub\s+)?enum\s+\w+").expect("static regex"),
            ),
            (
                "trait",
                Regex::new(r"^\s*(?:pub\s+)?trait\s+\w+").expect("static regex"),
            ),
            (
                "impl",
                Regex::new(r"^\s*impl(?:\s*<[^>]*>)?\s+\w+").expect("static regex"),
            ),
        ]
    })
}

/// Regex-based signature extraction for when tree-sitter fails.
#[allow(dead_code)]
fn extract_signatures_regex(source: &str, _language: &str) -> Vec<String> {
    // These patterns cover Rust; for Go/Python, the Python-side regex extractor
    // in determinex_hive.py handles it directly.
    let patterns = rust_signature_patterns();

    let mut sigs = Vec::new();
    for (i, line) in source.lines().enumerate() {
        for (_kind, pat) in patterns {
            if pat.is_match(line) {
                let text = line.trim().trim_end_matches('{').trim();
                let truncated = if text.len() > 150 {
                    format!("{}...", &text[..147])
                } else {
                    text.to_string()
                };
                sigs.push(format!("L{}: {}", i + 1, truncated));
                break; // only match one pattern per line
            }
        }
    }
    sigs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_replace_function_basic() {
        let source = "fn foo() {\n    println!(\"old\");\n}\n\nfn bar() { 42 }\n";
        let result = replace_function(
            source,
            "rust",
            "foo",
            "fn foo() {\n    println!(\"new\");\n}",
        )
        .unwrap();
        assert!(result.contains("new"));
        assert!(!result.contains("old"));
        assert!(result.contains("fn bar")); // bar untouched
    }

    #[test]
    fn test_regex_fallback_finds_function() {
        // Deliberately broken source — missing closing brace for bar
        let source = "fn foo(x: i32) {\n    x + 1\n}\n\nfn bar() {\n    // oops\n";
        // tree-sitter might still parse this, so test the regex path directly
        let result = replace_function_regex_fallback(
            "pub fn target(a: i32) {\n    old_body(a);\n}\n\nfn other() {}\n",
            "target",
            "pub fn target(a: i32) {\n    new_body(a);\n}",
        );
        assert!(result.is_ok());
        let (new_source, mode) = result.unwrap();
        assert_eq!(mode, "degraded");
        assert!(new_source.contains("new_body"));
        assert!(new_source.contains("fn other")); // other untouched
    }

    #[test]
    fn test_extract_signatures_basic() {
        let source =
            "pub fn alpha(x: i32) -> bool {\n    true\n}\n\nstruct Foo {\n    bar: i32,\n}\n";
        let (sigs, mode) = extract_signatures(source, "rust");
        assert_eq!(mode, "normal");
        assert!(sigs.len() >= 2);
        assert!(sigs.iter().any(|s| s.contains("alpha")));
        assert!(sigs.iter().any(|s| s.contains("Foo")));
    }

    #[test]
    fn test_brace_counting_handles_strings() {
        // Braces inside a string should still be counted by the naive counter,
        // but for well-formed Rust this doesn't matter because the tree-sitter
        // path handles it.  We just verify the regex path doesn't crash.
        let source = "fn tricky() {\n    let s = \"{ }\";\n}\n";
        let (result, _) = replace_function_regex_fallback(
            source,
            "tricky",
            "fn tricky() {\n    let s = \"replaced\";\n}",
        )
        .unwrap();
        assert!(result.contains("replaced"));
    }
}
