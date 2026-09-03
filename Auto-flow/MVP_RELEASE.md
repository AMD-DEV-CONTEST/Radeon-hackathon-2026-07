# AutoFlow 0.6 MVP Release

Release date: 2026-08-06

## Status

- Installation: PASS
- Demo: PASS
- Automated tests: PASS (40 tests)
- Python syntax: PASS
- Browser JavaScript syntax: PASS

## MVP capabilities

- Natural-language computer tasks through a model-driven observe, plan, act, and verify loop.
- Window and UI-control discovery without requiring prerecorded mouse coordinates.
- Background keyboard actions where Windows supports them, with safe foreground fallback.
- Local file, folder, application, URL, text, PDF, and PowerShell tools.
- Eleven explicit model-provider entries, including custom OpenAI-compatible endpoints and local Ollama.
- Separate home, task, and model pages in the local web interface.
- Local-only server at `http://127.0.0.1:8765/`.

## Release hardening

- Fixed the single-agent lock lifecycle when a task pauses for user input or is stopped.
- Restored the correct target window before foreground fallback and restored the user's previous window afterward.
- Restricted local API calls to exact same-origin JSON requests.
- Prevented built-in providers from silently sending credentials to overridden endpoints.
- Required HTTPS for remote custom endpoints that carry an API key.
- Restricted PowerShell authorization to explicit, literal paths from the user's original request.
- Added concurrency, window-routing, provider-security, origin, and content-type regression tests.

## Run

```powershell
cd C:\Users\智囊圈\Desktop\autoflow-code
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\autoflow-gui.exe
```

Then open `http://127.0.0.1:8765/`.

## Known boundaries

- A compatible model and network connection are required for cloud-model tasks.
- Windows may block UI automation against elevated applications unless AutoFlow has matching permission.
- Background interaction is limited by each target application's Windows message support; AutoFlow falls back to controlled foreground interaction when needed.
