# AutoFlow 0.6 MVP

AutoFlow is a general-purpose Windows desktop AI agent. After connecting a supported language model, it continuously follows an observe, plan, act, and verify loop instead of matching requests to a small set of hard-coded actions.

The local web interface provides separate Home, Task Center, and Model Center pages.

## Core Capabilities

- Observe active windows, visible windows, and Windows UI Automation controls
- Locate and click controls dynamically without prerecorded mouse coordinates
- Switch windows and open applications, files, folders, and URLs
- Enter text and execute keyboard shortcuts
- List directories, filter files, and read local text files
- Convert PDF documents to text
- Execute registered PowerShell operations within permission boundaries
- Observe the computer again after every action and continue planning
- Run tasks for up to 40 steps
- Display task progress, final responses, connection errors, and permission failures
- Provide emergency stopping and task-level authorization controls

## Model Providers

AutoFlow provides eleven explicit model-provider entries:

1. DeepSeek
2. Kimi China
3. Kimi Global
4. OpenAI
5. OpenRouter
6. SiliconFlow
7. Zhipu GLM
8. Alibaba Cloud Model Studio
9. Volcengine Ark
10. Ollama
11. Custom OpenAI-compatible endpoint

Cloud providers require the appropriate API credentials. Ollama can run locally without an API key. Custom providers support a configurable endpoint URL, model ID, and optional credentials.

All saved credentials are stored in Windows Credential Manager and are not written to project files or logs.

## Environment Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Internet access for cloud model providers
- A locally installed Ollama service when using local Ollama models

## Dependencies

The primary dependencies are:

- Typer
- Pydantic
- Rich
- Requests
- PyYAML
- OpenAI Python SDK
- pynput
- PyAutoGUI
- pypdf
- keyring
- pywinauto

Development and testing additionally use pytest and ReportLab. Exact dependency versions are defined in `pyproject.toml`.

## Installation

Clone or download the project, open PowerShell in the `Auto-flow` directory, and run:

```powershell
python -m pip install -e ".[dev]"
```

Windows users can also double-click `启动AutoFlow.bat`. On the first launch, the script creates a virtual environment and installs the required dependencies.

## Running AutoFlow

Start the local interface with:

```powershell
autoflow-gui
```

Then open:

```text
http://127.0.0.1:8765/
```

Use the Model Center to connect a model provider. Use the Task Center to enter and execute computer tasks.

## Local Deployment

For a fully local deployment, AutoFlow can connect to:

- Ollama running on the same computer
- A local OpenAI-compatible inference server
- A model server available on the local network

This allows task planning to remain local when a compatible local model and inference runtime are available.

## Autonomous Execution and Safety

- Sending a goal provides task-level authorization for the actions required to complete that goal.
- Keyboard input, shortcuts, coordinate actions, and non-destructive PowerShell operations can run automatically.
- Destructive or externally consequential actions must be explicitly authorized by the original goal.
- High-risk actions outside the original goal are blocked automatically.
- Models can only use registered AutoFlow tools and cannot obtain additional system permissions.
- Credentials remain in Windows Credential Manager.

## Testing

Run the automated tests:

```powershell
pytest
```

Run the MVP demonstration:

```powershell
python examples/demo_mvp.py
```

Current verified result:

```text
40 passed
```

## AMD Radeon / ROCm Status

The current development computer does not contain an AMD Radeon GPU. Therefore, physical AMD Radeon/ROCm execution and performance have not been verified.

AutoFlow supports a proposed AMD deployment through a ROCm-compatible inference server exposed through an OpenAI-compatible API. The deployment and inference-optimization plan is documented in:

```text
submission/PROJECT_SPECIFICATION.md
```

No fabricated AMD hardware performance results are included in this submission.

## Known Limitations

- Cloud models require network access.
- Desktop automation against elevated applications may require AutoFlow to run with matching permissions.
- Background interaction depends on the Windows message support of the target application.
- Model reliability affects the quality of task planning.
- AMD Radeon/ROCm hardware performance has not been physically verified.

## Additional Materials

- Project specification: `submission/PROJECT_SPECIFICATION.md`
- Release information: `MVP_RELEASE.md`
- Presentation: `AutoFlow_AMD_Track2_Presentation.pptx`
- Demo video: https://youtu.be/YrQ2k2cNXjo
