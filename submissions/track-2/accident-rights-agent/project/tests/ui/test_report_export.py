def test_markdown_and_html_report_include_traceability(golden_ui_runtime):
    artifact = golden_ui_runtime.reports.export(
        golden_ui_runtime.case_id, golden_ui_runtime.state
    )
    markdown = artifact.markdown_path.read_text(encoding="utf-8")
    html = artifact.html_path.read_text(encoding="utf-8")
    assert "Fact ID" in markdown or "FACT-" in markdown
    assert "Evidence ID" in markdown
    assert "法律引用" in markdown
    assert "Policy Gate" in markdown
    assert "免责声明" in markdown
    assert "submitted" not in markdown
    assert "SourceRole." not in markdown
    assert "SourceKind." not in markdown
    assert "ProcessingStatus." not in markdown
    assert "<!doctype html>" in html
    assert artifact.audit_event_id.startswith("AUDIT-")
