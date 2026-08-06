import logging

import services.logger as logger_service
from api.logs import get_logs
from services.logger import _RedactingFormatter, redact_sensitive_text


def test_redact_sensitive_text_covers_key_headers_and_untrusted_identifiers():
    source = (
        "task=audio-task-sk-example "
        "Authorization: Bearer token-value "
        "X-API-Key=nvk_admin_example "
        "password=plain-value"
    )

    redacted = redact_sensitive_text(source)

    assert "sk-example" not in redacted
    assert "token-value" not in redacted
    assert "nvk_admin_example" not in redacted
    assert "plain-value" not in redacted
    assert redacted.count("[REDACTED]") >= 4


def test_redacting_formatter_sanitizes_rendered_arguments():
    formatter = _RedactingFormatter(logging.Formatter("%(levelname)s %(message)s"))
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "request path=%s",
        ("/api/tasks/task-sk-secret/results",),
        None,
    )

    rendered = formatter.format(record)

    assert "sk-secret" not in rendered
    assert rendered == "INFO request path=/api/tasks/task-[REDACTED_CREDENTIAL]/results"


def test_task_identifier_text_is_not_itself_a_secret():
    assert redact_sensitive_text("/api/audio/tasks/audio-task-123/results") == (
        "/api/audio/tasks/audio-task-123/results"
    )


def test_log_api_redacts_file_content_before_returning(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text(
        "INFO Authorization: Bearer secret-token\n"
        "ERROR X-API-Key=nvk_admin_secret\n"
        "INFO model_key=sk-secret-value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(logger_service, "LOG_DIR", str(logs))

    response = get_logs(log_type="app", lines=20)
    rendered = "\n".join(response["lines"])

    assert response["line_count"] == 3
    assert "secret-token" not in rendered
    assert "nvk_admin_secret" not in rendered
    assert "sk-secret-value" not in rendered
