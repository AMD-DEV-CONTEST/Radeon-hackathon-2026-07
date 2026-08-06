# ToolGuard

A reliability layer for AI agents running locally on AMD (ROCm) GPUs.

Built for the AMD AI DevMaster Hackathon 2026, Track 2: Development & Local Deployment of Private AI Agents.

## Submission Materials

- Project Specification Document: [ToolGuard_Project_Specification](docs/ToolGuard_Project_Specification.pdf)
- Slides: [ToolGuard_Slides](docs/ToolGuard_Slides.pdf)
- Demo Video: [All About ToolGuard](https://youtu.be/BdFQvmEUnK0?si=BktMk_uLhSkha4ij)

---

## 1. The problem, in plain words

When an AI agent needs to actually do something - search the web, check the weather, run a calculation - the AI model has to output a special, structured message saying "run this tool with these inputs." The software running the agent then has to read that message correctly and execute it.

This step breaks, silently, right now, across the AI agent ecosystem. A tool call can come back malformed, get cut off mid-stream, or leak internal details instead of a real answer - and when it does, most agent frameworks don't even show an error. The call just vanishes.

We didn't invent this problem. We found it directly in public developer complaints:

- continuedev/continue#5508 - a valid tool call was silently ignored, no error shown - https://github.com/continuedev/continue/issues/5508
- GLM-5.1 discussion #1 - reports of wrong tool names and leaked schema definitions - https://huggingface.co/zai-org/GLM-5.1-FP8/discussions/1
- ROCm#4909 - a device error that took months to partially resolve - https://github.com/ROCm/ROCm/issues/4909
- ROCm#6148 - multi-GPU communication errors, still open - https://github.com/ROCm/ROCm/issues/6148
- vLLM discuss threads reporting general ROCm reliability complaints

The oldest core issue was opened in June 2025. Related bugs are still being reported as of April 2026 - this is a live, ongoing pain point, not old history.

## 2. Our idea: ToolGuard

Think of ToolGuard like an old telephone switchboard operator. It sits between an AI agent and the tools it tries to use, and:

1. Watches every tool-call attempt in real time
2. Detects when a call is broken (wrong format, leaked schema, dropped mid-stream, wrong tool name)
3. Repairs it - by handing the broken output back to the model itself and asking it to correctly re-route the call, using its own understanding of intent, not brittle string matching
4. Shows a live dashboard of what's happening: how many calls came through, how many were caught, how many were fixed

We are not trying to fix AMD's driver-level bugs - that requires specialized kernel engineering, out of scope for this project. We're building the missing developer-experience layer that makes hitting these bugs instantly recoverable instead of a silent failure or an hours-long GitHub scavenger hunt.

## 3. Core capabilities (per hackathon requirements)

Our project implements 2 of the 5 listed Agent capabilities:

- Tool invocation - the agent calls real (in this demo, simulated) tools: search, calculate, get_weather, read_file, via a real local model
- Clear permission control - toolguard/detector.py maintains an explicit allow-list of real tool names. Any call to a name outside that list is rejected and flagged, never silently executed. This is what catches our "wrong tool name" failure pattern - it is a genuine access-control mechanism, not just a bug detector

## 4. Real results, not simulated numbers

### Reliability benchmark
We ran 50 real trials against our live model (normal calls plus every failure pattern), measuring success rate with ToolGuard off vs on:

    Without ToolGuard: 32% success rate
    With ToolGuard:    100% success rate
    Improvement:       +68 percentage points

Every trial is a real API call to a real model running on a real AMD GPU - nothing here is scripted or faked. Full raw results: benchmarks/benchmark_results.json

One honest caveat: the "wrong tool name" pattern is a bonus, not part of our reliable core (see Scope below) - well-tuned models sometimes self-correct this on their own, before ToolGuard even needs to act. We kept this pattern in the benchmark anyway rather than cherry-picking a cleaner number, because it reflects a real, messier edge case rather than an idealized one.

### Inference speed benchmark
Measured over 5 real trials against our live model, steady state (excluding one-time model warmup on the very first request):

    Time to first token:      ~0.04 seconds
    Tokens per second:        ~32.8

### Repair latency
Measured over 9 real trials spanning all 3 core failure patterns - every trial successfully repaired:

    Average repair latency: ~0.67 seconds

This is the real, end-to-end cost of the detect-and-fix step: classifying the failure, sending a targeted corrective instruction back to the model, and verifying the repair - not a blind retry. Full raw results: benchmarks/repair_latency_results.json

This is enabled by ROCm-compatible vLLM optimizations active throughout our setup, confirmed directly in server logs (not assumed): chunked prefill (max_num_batched_tokens=2048), prefix caching, and ahead-of-time CUDA graph compilation specific to this GPU's architecture. Full raw results: benchmarks/inference_speed_results.json

## 5. Architecture
![ToolGuard Architecture](docs/toolguard_architecture.svg)

The agent sends a request to the local model. If the model's response is a valid tool call, ToolGuard passes it straight through untouched. If it's broken, ToolGuard detects exactly how, then hands the broken output back to the model with corrective instructions, gets a repaired response, and verifies the repair before passing it on. Every outcome (fixed or not) is logged and shown live on the dashboard.

## 6. Complete file structure and what each file does

    ToolGuard/
    |-- README.md              - this file
    |-- requirements.txt       - exact pinned Python dependencies
    |-- setup_env.sh           - sets environment variables pointing model/build caches at persistent storage
    |-- .gitignore             - excludes model weights, caches, logs, and local clutter from git
    |
    |-- agent/
    |   |-- fake_tools.py      - defines the 4 simulated tools (search, calculate, get_weather, read_file),
    |   |                        their schemas (how the model is told they exist), and the system prompt
    |   |-- test_agent.py      - talks to the real local model; contains the trigger functions that create
    |   |                        real conditions for each of the 3 core failure patterns plus the bonus
    |   |                        pattern, and the classifier that identifies which outcome occurred
    |   |-- live_demo.py       - runs forever in a loop: every few seconds, randomly picks a scenario
    |                            (normal call or one of the failure patterns), sends it through the model
    |                            and ToolGuard, and logs the result - this is what keeps the dashboard
    |                            showing continuous activity during a live demo
    |
    |-- toolguard/
    |   |-- detector.py        - reads a model response and identifies what happened: a valid call, or
    |   |                        which specific failure pattern. Contains no model calls itself
    |   |-- fixer.py           - the actual repair logic. Hands a broken response back to the model with
    |   |                        corrective instructions and returns the model's second attempt
    |   |-- guard.py           - the main coordinator: calls detector, then fixer if needed, then detector
    |   |                        again to confirm the repair worked, then logs the final outcome
    |   |-- demo_guard.py      - a one-shot script: runs each of the 3 core patterns once and prints
    |                            whether ToolGuard caught and fixed each one - used to verify the system
    |                            works end to end
    |
    |-- dashboard/
    |   |-- logger.py          - writes every result from guard.py to call_log.jsonl
    |   |-- terminal_dashboard.py - reads call_log.jsonl every 2 seconds and redraws a live, color-coded
    |                            table in the terminal: total calls, how many were normal, how many were
    |                            caught and fixed, and the most recent individual calls
    |
    |-- benchmarks/
    |   |-- run_benchmark.py           - runs 50 trials across all scenarios, measuring success rate with
    |   |                                 ToolGuard off vs on, saves results as JSON
    |   |-- benchmark_results.json     - saved output of the above (the 32% -> 100% result)
    |   |-- measure_inference_speed.py - runs 5 trials measuring real time-to-first-token and tokens/sec
    |   |-- inference_speed_results.json - saved output of the above
    |   |-- measure_repair_latency.py  - runs 9 trials measuring real repair latency across all 3 core patterns
    |   |-- repair_latency_results.json - saved output of the above
    |
    |-- scripts/
        |-- bootstrap.sh        - prepares a fresh instance to RUN the code: installs system packages
        |                         (tmux, ca-certificates) and Python dependencies, caching what it can in
        |                         persistent storage so future fresh instances need less from the internet
        |-- start_vllm.sh       - starts just the model server in the background (a tmux session), for
        |                         clean testing/benchmarking with nothing else running alongside it
        |-- start_toolguard.sh  - the one-command full launch: starts the model, waits until it's ready,
        |                         starts the continuous live-traffic loop, and opens the live dashboard -
        |                         everything running with a single command
        |-- stop_toolguard.sh   - cleanly stops the dashboard, the live-traffic loop, and the model server
        |-- audit_repo.sh       - a repository hygiene check: confirms no secrets, keys, or credentials
                                  were ever committed, and lists exactly what is/isn't tracked by git
    
    

## 7. Step-by-step: setting up and running this project

### First time on a brand new machine/instance

    bash scripts/bootstrap.sh

This installs everything needed to run the code: system packages and Python dependencies. Safe to re-run; it skips anything already installed.

### Bring the whole system to life (recommended way to see it working)

    scripts/start_toolguard.sh

What this actually does, in order:
1. Loads environment variables
2. Starts the model server in the background and waits until it responds
3. Starts a background loop that continuously sends real requests through the model and ToolGuard
4. Opens the live dashboard in your terminal - this is what you watch

### Stop everything cleanly when done

    scripts/stop_toolguard.sh

### Run just the model (for isolated testing or benchmarking)

    scripts/start_vllm.sh

### Reproduce our reliability benchmark (32% -> 100%)

    python3 benchmarks/run_benchmark.py

### Reproduce our inference speed benchmark

    python3 benchmarks/measure_inference_speed.py

### Run the one-shot proof-of-concept (each pattern, once)

    python3 toolguard/demo_guard.py

## 8. Scope - 3 reliable core patterns, 1 bonus

Core (target ~100% live reproducibility):
1. Plain text instead of a structured tool call
2. Schema leak (model reveals tool definitions instead of a result)
3. Dropped/incomplete streamed tool call (forced deliberately, to guarantee reproducibility)

Bonus (real, but lower-frequency to trigger live):
4. Wrong/malformed tool name - kept in our benchmark for honesty, not part of the guaranteed-reliable core

## 9. AMD / ROCm notes

- Runs on Qwen2.5-7B-Instruct via vLLM, using ROCm's Triton Attention backend (confirmed in server logs, not a generic fallback)
- A real, documented gotcha we hit and fixed: a plain pip install vllm silently installs the CUDA (Nvidia) build, which cannot see an AMD GPU at all. The fix is using AMD's pre-built ROCm Python environment directly - this is automated in scripts/bootstrap.sh
- Model and compiled-graph caches persist across instance restarts, so a fresh instance doesn't need to re-download the ~14GB model every time - confirmed by timing an actual restart (model load dropped from ~3 minutes to a few seconds)
- ToolGuard's own codebase is approximately 128KB total (~1,300 lines) - negligible next to the multi-gigabyte model it supervises. The reliability layer adds effectively no extra memory or storage burden to an existing ROCm setup
- Total GPU memory footprint: approximately 41.3 GiB (14.37 GiB model weights + ~27 GiB KV cache) out of 48 GiB available VRAM on the AMD Radeon Pro GPU used

## 10. Honest limitations / future work

- A web-based dashboard was attempted but blocked by a platform-specific port-exposure limitation on our specific cloud instance. The terminal dashboard is fully functional and was used for all testing and demos
- We deliberately did not attempt driver/OS-level integration (e.g. a background service baked into the GPU driver itself) - that is a legitimate long-term vision, but a multi-year systems engineering effort, well outside a hackathon's scope
- Testing a smaller or quantized model for the same task is a natural next optimization step identified but not yet benchmarked

## 11. Team

Team JINX - AMD AI DevMaster Hackathon 2026, Track 2: Development & Local Deployment of Private AI Agents.
