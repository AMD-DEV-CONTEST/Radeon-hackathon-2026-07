//! L1: File format parsing — XML parse check

use agent_core::event::ValidationResult;

/// Validate that the candidate content is well-formed XML.
pub fn validate_xml_parse(content: &str) -> ValidationResult {
    let start = std::time::Instant::now();

    let mut buf = Vec::new();
    let mut reader = quick_xml::Reader::from_str(content);
    reader.config_mut().check_end_names = true;
    let mut errors = Vec::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(quick_xml::events::Event::Eof) => break,
            Ok(_) => {}
            Err(e) => {
                errors.push(format!(
                    "XML parse error at position {}: {e}",
                    reader.error_position()
                ));
                break;
            }
        }
        buf.clear();
    }

    let elapsed = start.elapsed().as_secs_f64();
    if errors.is_empty() {
        super::pass(1, "parse", elapsed)
    } else {
        let diagnostic = errors.join("\n");
        super::fail(1, "parse", errors, diagnostic, elapsed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_xml_returns_one_error_instead_of_looping() {
        let result = validate_xml_parse("<root><child></root>");
        assert!(!result.passed);
        assert_eq!(result.error_count, 1);
    }
}
