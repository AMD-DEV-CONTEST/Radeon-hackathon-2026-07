# KlintCode Model Simulator

The simulator is a persistent, in-process model backend for development,
testing, demos, and air-gapped environments where vLLM is unavailable. It is
selected through a normal model profile and never opens a network connection.

## Quick start

Check the simulator profile:

```bash
cargo run -p klintcode-cli -- health --profile profiles/simulator.toml
```

Run a task through the normal Pipeline:

```bash
cargo run -p klintcode-cli -- run \
  --task benchmarks/tasks/simple-greeting \
  --profile profiles/simulator.toml \
  --output runs/simulator
```

Run the TUI with the simulator and automatically load a task:

```bash
KLINTCODE_PROFILE=profiles/simulator.toml \
KLINTCODE_TASK=benchmarks/tasks/simple-greeting \
cargo run -p klintcode-tui
```

Omit `KLINTCODE_TASK` to start with the interactive prompt composer. Type a
task and press `Enter`; `Shift+Enter` or `Alt+Enter` inserts a new line.

The model call is simulated, but TeaQL and compiler validation remain real.
This separation allows UI, reducer, repair-loop, context-budget, artifact, and
validation behavior to be exercised without hiding failures in local tools.

## Scenario format

A scenario is a TOML file containing an ordered response script:

```toml
name = "example"
repeat_last = false
default_latency_ms = 20
stream_chunk_chars = 16
stream_delay_ms = 2

[[responses]]
id = "first-call"
when_contains = "required prompt substring"
content_file = "../fixtures/result.xml"
reasoning_content = "Optional simulated reasoning"

[responses.usage]
prompt_tokens = 12000
completion_tokens = 1500
total_tokens = 13500
```

`content` can be used instead of `content_file`. Fixture paths are relative to
the scenario file. Missing usage values are conservatively estimated by the
local tokenizer.

Set `repeat_last = true` for an open-ended development scenario. Otherwise,
exhausting the response list fails loudly so tests cannot silently consume the
wrong response.

## Prompt matching

`when_contains` asserts that the current request contains a specific substring.
A mismatch does not consume the response and produces an actionable simulator
error. This is useful for verifying multi-call workflows.

## Failure injection

Failures use a tagged `error` table:

```toml
[[responses]]
id = "failure"

[responses.error]
kind = "transport"
status = 503
body = "simulated failure"
```

Supported error kinds:

- `transport`
- `timeout`
- `infrastructure`
- `incomplete`

## Maintained scenarios

- `happy-path.toml` — reusable valid response;
- `repair-loop.toml` — invalid XML followed by a repaired response;
- `error-injection.toml` — deterministic transport failure.

Keep scenario files small. Put large model outputs in `fixtures/` so they can
be reviewed, diffed, and reused independently.
