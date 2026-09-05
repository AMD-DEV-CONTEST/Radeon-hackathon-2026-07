/// Extracts file paths from `<_include file="...">` or `<_include file='...'>` tags.
pub fn extract_includes(content: &str) -> Vec<String> {
    let mut includes = Vec::new();
    let mut start = 0;
    while let Some(idx) = content[start..].find("<_include file=\"") {
        let open_quote = start + idx + 16;
        if let Some(close_quote) = content[open_quote..].find('"') {
            includes.push(content[open_quote..open_quote + close_quote].to_string());
            start = open_quote + close_quote + 1;
        } else {
            break;
        }
    }
    // Also handle single quotes just in case
    start = 0;
    while let Some(idx) = content[start..].find("<_include file='") {
        let open_quote = start + idx + 16;
        if let Some(close_quote) = content[open_quote..].find('\'') {
            includes.push(content[open_quote..open_quote + close_quote].to_string());
            start = open_quote + close_quote + 1;
        } else {
            break;
        }
    }
    includes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_double_quotes() {
        let content = r#"<_include file="test.xml">"#;
        assert_eq!(extract_includes(content), vec!["test.xml"]);
    }

    #[test]
    fn test_single_quotes() {
        let content = r#"<_include file='test.xml'>"#;
        assert_eq!(extract_includes(content), vec!["test.xml"]);
    }

    #[test]
    fn test_multiple_includes() {
        let content = r#"<_include file="test1.xml"> and <_include file="test2.xml"> <_include file='test3.xml'>"#;
        assert_eq!(extract_includes(content), vec!["test1.xml", "test2.xml", "test3.xml"]);
    }

    #[test]
    fn test_no_includes() {
        let content = "just some text";
        assert!(extract_includes(content).is_empty());
    }

    #[test]
    fn test_nested_malformed_includes() {
        // Missing closing quotes — the parser should break out and return empty.
        let content = r#"<_include file="test.xml > <_include file='test2.xml>"#;
        assert!(extract_includes(content).is_empty());
    }
}
