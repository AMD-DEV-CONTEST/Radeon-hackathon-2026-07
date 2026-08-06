# Contributing to CNC-AI-Brain

Thank you for your interest in contributing to CNC-AI-Brain v12.0 Fusion! This document describes how to report bugs, submit pull requests, and the coding standards we follow.

---

## Table of Contents

- [Reporting Bugs](#reporting-bugs)
- [Submitting Pull Requests](#submitting-pull-requests)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Development Setup](#development-setup)

---

## Reporting Bugs

Before submitting a bug report, please:

1. Search existing issues to avoid duplicates.
2. Reproduce the bug on the latest `main` branch.
3. Collect the following information:
   - OS and Python version
   - Steps to reproduce
   - Expected vs. actual behavior
   - Relevant log output (from `logs/` or console)
   - Screenshots if applicable

Open a new issue with the **bug** label and include all the information above.

---

## Submitting Pull Requests

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Write code** following the [Coding Standards](#coding-standards).
3. **Add or update tests** for your change. See [Testing Requirements](#testing-requirements).
4. **Run tests locally** and ensure they pass:
   ```bash
   pytest tests/ -v
   ```
5. **Commit** with a clear message:
   ```bash
   git commit -m "feat: add XYZ quoting rule for titanium"
   ```
   Use conventional commit prefixes:
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation only
   - `refactor:` code refactor
   - `test:` test only
   - `chore:` build / tooling
6. **Push** and open a pull request against `main`.
7. **Describe** the change, motivation, and any breaking changes in the PR description.
8. Wait for CI / review feedback.

---

## Coding Standards

### Python Style

- **Python 3.11** target.
- Follow **PEP 8** (line length 100).
- Use **snake_case** for variables and functions:
  ```python
  cad_extract = parse_step(file_path)
  part_spec = build_part_spec(bolt_holes, bolt_pcd)
  cad_tot_chain = run_tot_pipeline(part_spec)
  ```
- Use **PascalCase** for classes.
- Use **UPPER_SNAKE_CASE** for module-level constants.

### No Hardcoding Principle

All ports, URLs, ratios, and configuration values must come from:

- Environment variables, or
- Shared constants in `config/`, or
- `config/models.json` / `config/tolerance.yaml`

```python
# BAD
port = 7862

# GOOD
import os
port = int(os.getenv("CNC_PORT", "7862"))
```

### DRY Principle

- Do not duplicate JSON parsing patterns.
- Do not repeat imports across modules.
- Do not duplicate cost-split ratios across files — extract to a shared constant.

### Type Safety

- Prefer explicit type hints.
- Avoid unsafe type conversions.
- Validate inputs with pydantic models.

### Error Handling

- Use `try/except` with specific exceptions (not bare `except:`).
- Log errors via `loguru`.
- Never swallow exceptions silently.

### Comments

- Comments inside source files may remain in Chinese (existing code is preserved).
- New public API docstrings should be in English.

---

## Testing Requirements

- All new features and bug fixes must include tests.
- Tests live under `tests/`.
- Use **pytest**.

```bash
# CAD TOT tests
pytest tests/test_cad_tot.py -v

# End-to-end API tests
pytest tests/e2e_api_test_task7.py -v

# All tests
pytest tests/ -v
```

A PR is acceptable only if all tests pass.

---

## Development Setup

```bash
# 1. Clone your fork
git clone https://github.com/<your-username>/CNC-AI-Brain.git cnc-ai-brain
cd cnc-ai-brain

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Install Ollama for local model testing
# https://ollama.com
ollama pull qwen2.5:1.5b

# 5. Run the server
python run_server.py
# Open http://127.0.0.1:7862

# 6. Run tests
pytest tests/ -v
```

---

Thank you for contributing!