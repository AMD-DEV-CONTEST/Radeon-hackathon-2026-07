# Technical specification

- Level: S1
- Status: implemented

## Findings

Cloud diagnostics found a 35B Q4 model using approximately 46.7 GB of 49.1 GB VRAM with a 32K chat context. The llama.cpp log showed task prompts close to 2,000 tokens, while the application default timeout was only 15 seconds. Some task explanations therefore timed out and fell back to rule-only output.

## Design

The profile reduces avoidable generation and prompt work before changing model quality or task rules:

- `LLM_MAX_TOKENS=384` is attached to every OpenAI-compatible chat request.
- `LLM_TIMEOUT_SECONDS=90` accommodates the local 35B response budget.
- Evidence passed to the explanation-only prompt is shortened from 300 to 180 characters per item.
- The default recommended llama.cpp command uses `--ctx-size 16384`, reducing KV-cache pressure. This remains an operator setting, so rollback is a one-line restart with `32768`.
- `scripts/benchmark.py` uses distinct chat and embedding URLs and the shared ROCm parser.

## Risks and rollback

Shorter model responses may omit nonessential prose, but task status is already determined by rules and citations use unmodified source evidence. Set `LLM_MAX_TOKENS=768` or restart llama.cpp with `--ctx-size 32768` if a long-document evaluation requires more detail or context.

## Verification

- Configuration, LLM client, report prompt, and Stage J regression tests.
- Benchmark CLI syntax check, frontend build, and strict specification validation.
- Cloud before/after benchmark is recorded after the optimized service profile is started.
