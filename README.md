# Track 2: Radeon Requirement Guardian

Radeon Requirement Guardian is a privacy-first, document-to-action agent that turns a requirement document into an evidence-backed execution checklist. It plans the task, searches the local document with tools, recalls local memory, writes a report, and independently verifies its own output. Every language-model call is served by vLLM on an AMD Radeon PRO W7900D through ROCm; no cloud AI API is used.

## Why It Matters

Dense submission rules, procurement documents, compliance policies, and internal procedures are easy to misread. A normal chatbot can summarize them, but it does not expose a reliable execution process. This project produces a visible plan, evidence references, tool calls, a persistent memory record, and a final coverage check. The design is useful for private enterprise documents that cannot be sent to a cloud model.

## Agentic Capabilities

1. **Reasoning and planning** - the local model converts the user's goal into an executable plan and targeted search queries.
2. **Tool use** - the agent reads PDF/TXT/MD/CSV/LOG files, chunks and searches the document, recalls prior work, and writes a Markdown report.
3. **Local memory** - SQLite stores concise outcomes and recalls relevant decisions in later runs.
4. **Task execution** - the agent creates a submission-ready checklist instead of returning only a conversational answer.
5. **Independent verification** - a separate model pass checks coverage and unsupported claims.
6. **Auditable UX** - the Gradio interface exposes the final report, verification JSON, complete agent trace, and AMD inference metrics.

## Architecture

```text
Requirement document + user goal
               |
               v
        Local planner (LLM)
               |
               v
  +------------+-------------+
  | read_document            |
  | search_document          |---- Local evidence chunks
  | recall_memory            |---- SQLite memory
  +------------+-------------+
               |
               v
   Evidence-grounded report writer
               |
               v
      Independent verifier
               |
               v
 Report + checklist + trace + metrics

All LLM stages -> vLLM OpenAI-compatible endpoint -> Qwen3 -> ROCm -> AMD Radeon
```

## AMD Radeon Deployment

The tested target environment is:

- Hardware: AMD Radeon PRO W7900D, RDNA 3, gfx1100, 48 GB VRAM
- Software: ROCm 7.2.1 and a ROCm-compatible vLLM build
- Model: `Qwen/Qwen3-0.6B`
- Precision: FP16
- Endpoint: `http://127.0.0.1:8000/v1/chat/completions`

Start the model server in the Radeon workspace:

```bash
vllm serve Qwen/Qwen3-0.6B \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --enforce-eager
```

`--enforce-eager` is used for reliable execution on the provided short-lived workshop image. After the baseline is captured, remove it and benchmark the default compiled execution path if the environment supports it.

Verify that the endpoint is local:

```bash
curl http://127.0.0.1:8000/v1/models
rocm-smi --showproductname --showmeminfo vram
```

## Run the Application

```bash
python -m pip install -r requirements.txt
python agent.py
```

Open `http://localhost:7862`, upload `sample_requirements.txt`, keep the default task, and select **Run Local Agent**.

If notebook port forwarding is unavailable, use the terminal demo:

```bash
python demo_cli.py \
  --file sample_requirements.txt \
  --task "Extract all mandatory requirements and create a submission-ready checklist."
```

Environment variables can override the defaults:

```bash
export VLLM_ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
export VLLM_MODEL=Qwen/Qwen3-0.6B
```

## Radeon Optimization and Measurement

The implementation keeps the model loaded in Radeon VRAM behind vLLM and makes all three reasoning stages use the same local server. FP16 reduces memory traffic relative to FP32. vLLM provides continuous batching and a reusable serving process, while ROCm supplies the Radeon execution backend.

The app records the following values for every run:

- Number of local model calls
- Prompt and completion tokens reported by vLLM
- Aggregate inference time
- End-to-end agent time
- Effective output throughput (`completion tokens / aggregate inference seconds`)

The effective throughput is an application-level measurement, not a claim about raw kernel decode speed. The demo pairs it with live `rocm-smi` output to prove GPU execution. Actual measurements should be copied from the target workspace into the submission evidence; this repository intentionally contains no invented benchmark number.

Suggested last-mile comparison if time permits:

```text
Configuration A: FP16 + --enforce-eager
Configuration B: FP16 + default compiled execution

For each configuration, run the same sample task three times and report the median.
```

## Repository Layout

```text
track2-local-agent-on-radeon/
|- agent.py                         Agent, tools, memory, verifier, and UI
|- demo_cli.py                      Terminal-first demo with Radeon evidence
|- sample_requirements.txt          Reproducible evaluation input
|- requirements.txt
|- docs/
|  `- project_specification.pdf     Required English specification
|- assets/
|  `- demo_video_link.txt           Playable 3-5 minute demo URL
`- tests/
   `- test_core.py                  Offline unit tests
```

## Evaluation

The included sample has explicit submission constraints. A successful run should:

- Identify all four required deliverables
- Preserve the pull-request title rule
- Identify English-only materials and the 3-5 minute video constraint
- Cite local evidence for factual requirements
- Produce planner, tool, writer, verifier, and memory events in the trace
- Write `output/latest_report.md`

Run offline unit tests with:

```bash
python -m unittest discover -s tests -v
```

## Privacy and Safety

- No cloud LLM or cloud embedding API is called.
- Source documents and SQLite memory remain inside the local workspace.
- Reports separate cited requirements from missing or uncertain information.
- The verifier flags unsupported claims for human review.

## Demo Video

The playable link is stored in [`assets/demo_video_link.txt`](assets/demo_video_link.txt).

## Limitations and Next Steps

- The lightweight lexical retriever is reliable for the demo but can be replaced by ROCm-accelerated embeddings or hipVS.
- The 0.6B model favors low latency and reproducibility; a larger local Qwen model can improve complex reasoning on the 48 GB card.
- The current tools are read-only except for the local report and memory database. Human approval should be added before external actions in a production version.

## License

This hackathon submission is provided for evaluation and demonstration purposes.
