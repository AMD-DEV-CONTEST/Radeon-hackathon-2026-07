# Agent Harness Benchmark

## Admission

This document owns the local evaluation boundary for the Agent Harness
benchmark. The [LLM conversation boundary](../20-product-tdd/llm-conversation-boundary.md)
continues to own product conversation topology, authority, and sequences;
benchmark code observes public outcomes and does not alter that contract.

## Subject and Case Boundary

A subject is one isolated `AgentHarness × configured subject model × case`
cell. It uses the real provider path, then observes the settled public product
state. The runner is case-agnostic. `headless` submits through the public Harness
service directly; `headed` drives the same submission through the visible desktop
UI. Execution mode is recorded in result schema v4 and does not change the case,
oracle, Judge, or subject model.

`benchmarks/agent_harness/` is the benchmark home. Each `test_*.py` case
module is both the case definition and its explicitly collected pytest item;
pytest selects and controls the case matrix. Shared runner, contracts, judge,
and the deliberately small pytest fixture live in `_infra/`. There is no case
registry and no second case-specific test implementation.

A case owns its business intent, fixture validation, submission, terminal
output location, privacy-reviewed evidence projection, and rubric identity.
It must not require a prescribed Tool trace, exact Assistant wording, chart
grammar, or golden output. It may grade the semantic content of the terminal
answer when that is the user's requested deliverable. The regional-sales graph
case, for example, accepts an
appropriate presentation form rather than bars, a title, or a particular axis
layout.

A case may prepare isolated product state through a narrow public-service seam.
Preparation runs once per cell after the production graph and Thread exist, but
before subject timing begins. The rainy-season case uses this seam to index its
rule in the cell's global Knowledge Library; it does not add a per-Thread
enablement state or alter the production conversation boundary. In headed mode,
the adapter realizes that same intent through the Knowledge Workspace file-drop
surface and its real background task queue.

Knowledge-plus-data cases judge the Agent's final answer surfaces: terminal Assistant
content and the public Datasets, Artifacts, or charts it actually delivered. Tool
Calls and ToolResults are execution telemetry, not semantic pass criteria; they may
diagnose a failure but cannot make a case pass. The rainy-season case therefore
requires the exact derived Dataset linked to the attached source without inspecting
whether or how the Agent called `knowledge.lookup`; it also checks the terminal answer
for the governing rule and the exact SKU/quantity actions without prescribing wording
or formatting. Cases whose answer is primarily insight or advice evaluate the
terminal answer against bounded fixture facts and an explicit rubric, using the Judge
only when deterministic checks cannot express the semantic requirement.

## Evidence and Judge Boundary

Each judge-enabled case supplies only a bounded packet of user intent,
independent fixture facts, final public Dataset/Artifact semantics, and—only
when the rubric grades it—the terminal Assistant answer. For a text-only judge,
graph evidence is a semantic projection such as visible text and accessibility
labels, not pixels or raw SVG. It may assess task fulfilment, factual grounding,
and semantic comprehensibility, but not visual aesthetics.

Evidence is untrusted content. It must be delimited and treated as data, and
must exclude transcripts, intermediate Assistant content, Tool arguments/results,
raw fixture rows, raw artifacts, internal identifiers, paths, provider metadata,
and credentials. A terminal answer included for a matching rubric is a bounded
final-output projection, never the conversation transcript. Persist only bounded
verdict scores and reason codes; discard raw judge prompts, responses, and errors.

The judge is a rubric-based, pointwise evaluator after the subject cell has
settled. Its configuration is explicit and separate from the subject matrix;
same-model judging is allowed only when recorded as non-independent. A judge
uses no Tools and is not another participant in the Agent turn.

## Result Interpretation

Execution, integrity, semantic verdict, judge status, subject metrics, and
judge metrics are independent result channels. Integrity covers fixture and
settings fingerprints, isolated-runtime confinement, and safe serialization.
An integrity breach invalidates the measurement instead of becoming a model
quality result.

Headed integrity additionally proves that the real MainWindow was visible,
source attachments were accepted through the composer drop surface, the terminal
Assistant message was rendered, imported Knowledge appeared in the Workspace,
Knowledge tasks settled, window-owned services shut down, and the isolated SQLite
database remained readable. These are execution facts only. The case still grades
the final answer, Dataset, and Artifact outcomes and never passes because the UI
journey itself completed.

A semantic `fail` is a valid subject outcome. Missing terminal output may be
such a failure; insufficient final evidence is `inconclusive`. An evaluator
uses `fail` only for positive evidence of an irrelevant or materially
contradictory outcome, not merely because another score dimension is weak.
Missing judge configuration, provider failure, or malformed judgement is a
judge-status state and must not be collapsed into a semantic failure or
success.

Subject measurements include the Harness turn's latency, token usage, messages,
Tool calls/results, retries, and derived outputs. Judge latency, usage, and
retries are evaluation metadata and never contribute to subject performance.

## Offline and Live Policy

The default 30-case test suite is deterministic and offline. It does not collect
the benchmark case directory, open headed benchmark windows, or call a provider.
Static analysis and benchmark source own schema and option continuity; no ordinary
pytest case duplicates benchmark case logic, result schemas, types, or Tool checks.

Use `pdm run benchmark-agent-harness -- --collect-only` to prove discovery
without provider access. A live run is an explicit
`pdm run benchmark-agent-harness -- [pytest options]` action with external,
untracked subject and judge settings; normal pytest selection (`-k` or a node
id) selects its case. A live report must retain the separate channels above
without secrets or raw evidence. Calibrate a configured judge before using
scores for comparison; disagreement with clear fixtures is a signal to refine
the case evidence or rubric, not to add Tool-trajectory assertions.

Use `pdm run benchmark-agent-harness-headed -- --collect-only` for offline headed
discovery and `pdm run benchmark-agent-harness-headed -- [pytest options]` for
explicit visible E2E acceptance. Headed execution requires an interactive desktop
and uses the same external, untracked Subject, Embedding, and optional Judge
settings as headless execution. Every cell gets a fresh `XENIX_APP_HOME`; real
fixture files enter through Qt drop events, and no mock/replay provider is admitted.

## Change Guidance

Read `benchmarks/agent_harness/AGENTS.md` before changing the benchmark.
Source and focused dynamic-infrastructure tests own exact fields, request
shapes, and pytest options.
