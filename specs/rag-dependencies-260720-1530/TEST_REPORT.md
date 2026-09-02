# Verification Report

## Initial finding

On both local and cloud environments, `scripts/verify_phase_a.py` failed from
a normal `.[dev]` installation because `reportlab` was undeclared. After that
package was installed, the script next failed because `python-docx` was also
undeclared. This demonstrated that Phase A could not be reproduced from a
clean installation.

## Clean-environment cloud verification

```powershell
python -m venv <clean-venv>
<clean-venv>/bin/python -m pip install -e ".[dev]"
<clean-venv>/bin/python -m pytest -q
<clean-venv>/bin/python scripts/verify_phase_a.py
```

The cloud verification used a newly created isolated virtual environment,
`/workspace/office-agent/.venv-rag-verify-1530`, rather than the running API
environment. It installed only `-e ".[dev]"` from this branch.

- `pytest -q`: 57 passed, 3 skipped, 1 framework deprecation warning.
- `scripts/verify_phase_a.py`: all 10 acceptance criteria passed.
- The script successfully parsed generated Markdown, TXT, PDF, DOCX, and XLSX
  files; it also recorded a corrupt TXT file without aborting and rejected a
  symlink escape.
- The verification produced 48 citable chunks with page, heading, or sheet and
  cell-range locations as appropriate.
