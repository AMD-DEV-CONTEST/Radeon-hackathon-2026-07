# Extending CodeRisk Agent

## Why Extensibility Matters in Security

Security threats evolve daily. A static rule set quickly becomes outdated. CodeRisk Agent is designed to be **extended by security teams without modifying core code** — enabling rapid response to new CVE disclosures and emerging attack patterns.

---

## Adding Custom Detection Rules

CodeRisk Agent's static analysis engine (Agent 1) supports custom rule definitions. Rules are Python regex patterns with associated CWE mappings.

### Quick Start: Add a Custom Rule

```bash
# 1. Create custom rule
cat > rules/custom/my_rule.json << 'EOF'
{
  "id": "CUSTOM-001",
  "language": "Python",
  "pattern": "eval\\s*\\(",
  "severity": "CRITICAL",
  "cwe": "CWE-95",
  "description": "Dangerous eval() usage",
  "fix": "Use ast.literal_eval() for safe evaluation"
}
EOF

# 2. Run with custom rules
python main.py analyze ./src --custom-rules rules/custom/
```

### Example: Responding to a Zero-Day

On August 1, 2026, a new vulnerability (CVE-2026-XXXXX) is disclosed. A security engineer can respond **without waiting for a new release**:

```json
{
  "id": "CVE-2026-XXXXX",
  "language": "Python",
  "pattern": "eval\\(.*request\\.(args|form).*\\)",
  "severity": "CRITICAL",
  "cwe": "CWE-95",
  "description": "Zero-day: Unsafe eval() with user input in web framework",
  "fix": "Use ast.literal_eval() or validate input before processing"
}
```

The rule is loaded immediately and applied in the next scan.

### Built-in Rule Structure

```python
# core/rules.py (simplified example)
RULES = {
    "C": [
        {
            "id": "CWE-120",
            "pattern": r"strcpy\s*\([^,]+,\s*[^)]+\)",
            "severity": "CRITICAL",
            "description": "Buffer overflow via strcpy()",
            "fix": "Use strncpy() or strlcpy() with size limit",
        },
        # ... 12 more C rules
    ],
    "Python": [
        {
            "id": "CWE-78",
            "pattern": r"os\.system\s*\(",
            "severity": "CRITICAL",
            "description": "Command injection via os.system()",
            "fix": "Use subprocess.run() with shell=False",
        },
        # ... 13 more Python rules
    ],
}
```

### Supported Languages

| Language | Rules | Coverage |
|----------|-------|----------|
| C/C++ | 13 | Buffer overflow, format string, double free, command injection, etc. |
| Python | 14 | SQL injection, command injection, unsafe deserialization, etc. |

Adding a new language requires:
1. Defining regex patterns for the target language
2. Configuring tree-sitter parser (if available)
3. Creating test cases in `tests/test_cases/`

---

## Plugin Discovery System

CodeRisk Agent uses Python entry points for plugin discovery:

```python
# pyproject.toml (planned — see Future Roadmap)
[project.entry-points."coderisk.agents"]
my_custom_agent = "my_plugin.agent:CustomAgent"
```

*Note: Entry point registration is planned for v1.1. Current version loads custom rules from JSON files via `--custom-rules` flag.*

---

## Adding a Custom Agent

*Note: Pipeline.add_agent is a planned API for v1.1. Current architecture uses the Orchestrator's sequential pipeline.*

```python
# Planned API (v1.1)
class Pipeline:
    def __init__(self):
        self.agents = [
            StaticAnalyzer(),
            SemanticAnalyzer(),
            DeepVerifier(),
            ReportGenerator()
        ]

    def add_agent(self, agent: Agent, position: int = -1):
        """Insert custom agent at any pipeline position."""
        self.agents.insert(position, agent)
```

---

## Extending the LLM Backend

CodeRisk Agent supports pluggable LLM backends via the `core/llm_client.py` interface:

```python
class LLMClient(Protocol):
    def generate(self, prompt: str, **kwargs) -> str: ...
    def health_check(self) -> bool: ...
```

### Current Backends

| Backend | Config | Use Case |
|---------|--------|----------|
| `local_llama_cpp` | GGUF model path | Direct GPU inference |
| `local_http` | llama-server URL | HTTP API inference |

### Adding a New Backend

1. Implement the `LLMClient` protocol
2. Register in `core/llm_client.py`
3. Add configuration to `.env.example`

---

## Extending Report Formats

Agent 4 (Report Generator) supports multiple output formats:

- **JSON**: Machine-readable, for CI/CD integration
- **Markdown**: Human-readable, for documentation
- **Rich terminal**: Interactive CLI output
- **SARIF**: GitHub Code Scanning compatible

Adding a new format requires implementing a `format_report(findings: list[Risk]) -> str` function in `agents/report_generator.py`.
