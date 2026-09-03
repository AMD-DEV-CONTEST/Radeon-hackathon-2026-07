# AutoFlow 0.6 Project Specification

## 1. Project Overview

AutoFlow is a Windows desktop AI agent that converts natural-language requests into observable computer actions. It follows an observe, plan, act, and verify loop instead of relying only on prerecorded mouse coordinates.

## 2. Application Scenarios

AutoFlow is designed for office workers and general Windows users.

Typical scenarios include:

- Opening applications, files, folders, and websites
- Converting PDF documents to text
- Entering text and executing keyboard shortcuts
- Locating Windows UI controls dynamically
- Automating multi-step desktop workflows
- Using local or cloud language models

## 3. Agent Architecture

AutoFlow contains the following components:

1. Local web user interface
2. Model-provider management
3. Agent planner
4. Computer-observation layer
5. Registered computer tools
6. Permission and risk-control layer
7. Execution-result verification
8. Final-response generator

The agent repeatedly observes the computer, requests a structured action from the selected model, executes the registered tool, and observes the result again.

## 4. Core Capabilities

- Natural-language task planning
- Windows UI Automation control discovery
- Application, file, folder, and URL launching
- Keyboard input and shortcuts
- Local file operations
- PDF-to-text conversion
- Eleven model-provider configurations
- Windows Credential Manager integration
- Local Ollama support
- Custom OpenAI-compatible endpoints
- Task-level authorization and emergency stopping

## 5. Model and Local Deployment

AutoFlow supports cloud model providers, local Ollama models, and custom OpenAI-compatible endpoints.

A local deployment can use:

- AutoFlow running on Windows
- Ollama or another OpenAI-compatible local inference server
- A locally deployed language model
- Windows UI Automation for desktop interaction

## 6. AMD Radeon / ROCm Deployment Plan

The current development machine does not contain an AMD Radeon GPU. Therefore, AMD Radeon/ROCm hardware execution has not been verified.

The proposed AMD deployment uses a ROCm-compatible inference server exposed through an OpenAI-compatible API. AutoFlow can connect to this endpoint through its custom-provider configuration.

## 7. AMD Inference Optimization Plan

Potential optimization methods include:

- Quantized model weights
- Reduced model context length
- Prompt-history truncation
- Reusing the local inference process
- Reducing unnecessary observation data
- KV-cache optimization where supported
- Selecting ROCm-compatible models and inference runtimes

No fabricated AMD performance results are included in this submission.

## 8. Environment and Installation

Requirements:

- Windows 10 or Windows 11
- Python 3.10 or newer

Installation:

```powershell
python -m pip install -e ".[dev]"
```

Launch:

```powershell
autoflow-gui
```

Open:

```text
http://127.0.0.1:8765/
```

## 9. Testing

```powershell
pytest
python examples/demo_mvp.py
```

Verified automated-test result:

```text
40 passed
```

## 10. Known Limitations

- Cloud models require network access.
- Elevated applications may require matching AutoFlow permissions.
- Background interaction depends on target-application support.
- AMD Radeon/ROCm execution has not been verified on physical AMD hardware.
