from pathlib import Path

import pytest


@pytest.fixture
def config_tree(tmp_path: Path) -> Path:
    (tmp_path / "app.yaml").write_text(
        """
app:
  name: TestGuard
  environment: test
  log_level: INFO
  seed: 7
  data_dir: test-data
llm_config_path: llm.yaml
permission_config_path: permissions.yaml
monitoring_config_path: monitoring.yaml
""",
        encoding="utf-8",
    )
    (tmp_path / "llm.yaml").write_text(
        """
llm:
  mode: mock
  endpoint: http://127.0.0.1:8080/v1
  model: test-model
  api_key: secret
  timeout_seconds: 10
  allowed_hosts: [localhost, 127.0.0.1, "::1"]
  max_tokens: 16
  temperature: 0
""",
        encoding="utf-8",
    )
    (tmp_path / "permissions.yaml").write_text(
        "permissions:\n  allow_network: false\n  allow_lan_llm: false\n"
        "  allowed_lan_cidrs: []\n  audit_enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "monitoring.yaml").write_text(
        "monitoring:\n  enabled: true\n  sample_interval_seconds: 0.1\n"
        "  command_timeout_seconds: 1\n  output_path: output.jsonl\n",
        encoding="utf-8",
    )
    return tmp_path / "app.yaml"

