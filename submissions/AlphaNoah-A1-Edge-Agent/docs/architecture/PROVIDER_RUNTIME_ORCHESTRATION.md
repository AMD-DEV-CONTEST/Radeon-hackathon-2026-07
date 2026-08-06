# Provider Runtime Orchestration

## 1. Purpose

This document defines the provider composition boundary used by AlphaNoah
startup entry points. It closes a composition gap; it does not introduce a
second provider framework.

The implementation must reuse:

- `AIRuntimeConfig` and `ProviderSettings`;
- `ProviderDiscovery`;
- `ProviderSelector`;
- `AnalysisProviderFactory`;
- the existing Fake, Ollama and OpenAI-compatible adapters;
- the existing `ReliableAnalysisProvider` boundary when composing the business
  application.

The required data flow is:

```text
Startup options
        |
        v
ProviderRuntimeOrchestrator
        |
        +--> AIRuntimeConfig loading and validation
        +--> ProviderDiscovery (read-only candidates)
        +--> explicit selection resolution
        +--> AnalysisProviderFactory
        |
        v
ResolvedProviderRuntime
        |
        v
Web composition root
        |
        v
build_restaurant_aircon_golden_path(raw_provider=...)
        |
        v
AlphaNoah Runtime
```

Provider selection belongs to a composition root. `AlphaNoahRuntime`, Skills,
Knowledge, DecisionHook and the Web adapters must not discover services, read
credentials or branch on provider type.

## 2. Audit baseline

Before F03-D3, the repository already contained real provider components, but
the startup paths did not share them:

| Capability | Baseline |
|---|---|
| Configuration, discovery, selection and factory | Implemented and used by provider management/doctor |
| `demo analyze` and restaurant demo | Constructed Ollama directly; used a separate CLI/environment model |
| Standard `web_api` startup | Built the restaurant application without a raw provider and therefore received the restaurant Fake default |
| Saved provider selection | Did not influence `web_api` |
| vLLM | A distinct provider kind using the OpenAI-compatible adapter |
| Provider status projection | Not implemented |

The closure therefore adds a thin orchestration layer and connects it to
startup. It must not add `ProviderDiscoveryV2`, a Web-only factory, another
Ollama adapter or another persistent configuration format.

## 3. Existing component responsibilities

### `AIRuntimeConfig`

Owns versioned, non-secret provider configuration:

- selection mode and saved selection;
- enabled provider sections;
- endpoint and explicit model;
- bounded analysis timeout and optional Ollama model digest;
- the name of a credential environment variable.

It never stores:

- a credential value or Authorization header;
- database paths;
- prompts or model responses;
- Runtime, Event, Decision or Skill objects.

Configuration loading validates the full document before it can participate in
startup. An absent file means no saved selection; it does not authorize Fake.

### `ProviderDiscovery`

Performs bounded, read-only probes of configured endpoints. It reports facts
such as:

- endpoint availability;
- credential presence or rejection;
- available model identifiers;
- whether the explicitly configured model exists.

Discovery never:

- downloads a model;
- scans arbitrary LAN or public ports;
- persists configuration;
- chooses a provider or a model;
- turns Fake into a discovered real AI runtime.

### `ProviderSelector`

Validates one selection against discovery results. F03-D3 uses it only after
the orchestration layer has resolved an explicit selection source.

The previous `auto` policy that chose the first available kind in a fixed
priority is not a valid business-startup policy. Discovery results are
candidates, not authorization to run.

An explicit or saved provider that fails validation fails closed. It must not
fall through to another real provider or to Fake.

### `AnalysisProviderFactory`

Constructs one raw provider from already validated settings. It does not load
business state and does not select a provider.

- Fake produces the explicit synthetic readiness implementation.
- Ollama produces `OllamaAnalysisProvider`.
- vLLM and OpenAI-compatible produce
  `OpenAICompatibleAnalysisProvider` with different `provider_kind` values.

The factory reads a cloud credential only from the configured environment
variable name. A missing credential is a controlled startup error.

### `ReliableAnalysisProvider`

Wraps the selected raw provider with bounded retry, validation and audit
metadata. Retry means retrying the same provider. It never means selecting a
different provider or constructing Fake after a failure.

## 4. Thin orchestration boundary

`ProviderRuntimeOrchestrator` has exactly these responsibilities:

1. load and validate `AIRuntimeConfig`;
2. apply startup overrides without persisting them;
3. determine whether an explicit provider selection exists;
4. run `ProviderDiscovery` for configured candidates;
5. revalidate an explicit or saved selection;
6. call `AnalysisProviderFactory`;
7. return a safe resolved result for application composition and status
   projection.

It must not:

- create or update Event, Decision, Task, Notification or Audit records;
- write SQLite;
- invoke a Skill or model analysis;
- modify the user's saved configuration;
- select from a discovery list when no explicit selection exists;
- catch a resolution or factory failure and create Fake;
- expose credential values.

A resolved result carries only composition and safe status facts:

```text
ResolvedProviderRuntime
- provider_instance
- provider_type
- model
- execution_mode
- selection_source
- health_status
```

`provider_instance` remains internal. All externally projected values are
allowlisted separately.

## 5. Selection precedence

The system-wide precedence is:

```text
1. Explicit command-line provider configuration
2. Explicit provider configuration supplied through environment variables
3. A saved selection, after discovery revalidation
4. Discovery candidates, listed without selection
5. Unconfigured
```

This order resolves configuration; it does not create fallback behavior.

### Command-line selection

A command-line provider is explicit and process-local. Its accompanying model,
endpoint, timeout and credential environment-variable reference override lower
precedence values for that process only.

The standard Web composition root exposes:

```text
--config
--provider
--model
--base-url
--timeout-seconds
--model-digest
--credential-env
--discovery-timeout
```

`--credential-env` is an environment-variable name, never a credential value.

Incomplete explicit input is invalid configuration. The orchestrator must not
fill a missing model by choosing the first discovered model.

### Environment selection

Environment values may supply explicit startup configuration, including a
credential reference. Environment values are parsed and validated through the
same provider configuration types as file values.

A raw credential value is never copied into `AIRuntimeConfig`, status output,
logs or exceptions.

Generic startup variables are:

```text
ALPHANOAH_AI_PROVIDER
ALPHANOAH_AI_MODEL
ALPHANOAH_AI_BASE_URL
ALPHANOAH_AI_TIMEOUT_SECONDS
ALPHANOAH_AI_MODEL_DIGEST
ALPHANOAH_AI_CREDENTIAL_ENV
```

Existing Ollama-only variables remain compatibility inputs:

```text
ALPHANOAH_OLLAMA_BASE_URL
ALPHANOAH_OLLAMA_MODEL
ALPHANOAH_OLLAMA_MODEL_DIGEST
```

Generic `ALPHANOAH_AI_*` values define the unified environment layer.
Compatibility inputs must not create a second selection algorithm.

### Saved selection

A saved `selected` value is not permanently trusted. Every startup re-runs
discovery and verifies:

- the provider is enabled and fully configured;
- its endpoint is reachable under the bounded health policy;
- required credentials are present and accepted;
- the configured model is reported by the endpoint.

Failed revalidation produces `unavailable` or `invalid_configuration`. It does
not change the saved file and does not choose another provider.

### Discovery-only state

When no CLI, environment or saved selection exists, discovery may return zero,
one or many candidates. In every case no provider is constructed.

The externally visible state is `unconfigured`, optionally with a safe count or
kind list for operator diagnostics. The operator must explicitly select a
provider before business startup.

This rule deliberately means:

```text
one discovered Ollama service != selected Ollama
multiple discovered services   != priority-based selection
Fake available                 != Fake enabled
```

## 6. Provider semantics

| Provider label | Transport implementation | Endpoint policy | Selection boundary |
|---|---|---|---|
| `fake` | Synthetic Fake adapter | No endpoint or model | Explicit CLI/config selection or direct test injection only |
| `ollama` | Native Ollama `/api/tags` and `/api/generate` | Unauthenticated HTTP loopback only | Explicit model tag required |
| `vllm` | OpenAI-compatible `/v1/models` and `/v1/chat/completions` | Configured endpoint; no network scanning | Retains `vllm` identity |
| `openai_compatible` | OpenAI-compatible models/chat-completions | Configured endpoint and environment-only credential reference | Retains `openai_compatible` identity |

vLLM and OpenAI-compatible intentionally share transport code. They remain
separate product labels because execution location, health expectations,
operator intent and status presentation differ.

## 7. Fake boundary

Fake is not a discovered AI runtime and is never a fallback.

Allowed:

- `--provider fake`;
- a saved configuration explicitly selecting Fake for an identified synthetic
  demo;
- direct injection by tests.

Forbidden:

- selecting Fake because no real endpoint is reachable;
- selecting Fake because a configured model or credential is missing;
- selecting Fake as the final item in an automatic priority list;
- reporting Fake as healthy real inference;
- hiding Fake identity from `/api/runtime`.

Runtime status for Fake must identify a synthetic/demo execution mode. A Fake
result proves only offline composition behavior.

## 8. Web composition root

The standard Web startup resolves the provider before building the business
application:

```python
resolved = orchestrator.resolve(startup_options)
application = build_restaurant_aircon_golden_path(
    database_path,
    raw_provider=resolved.provider_instance,
)
server = create_server(
    database_path,
    application=application,
    runtime_status=resolved.safe_status,
)
```

The exact internal signatures may remain narrower, but the control
relationship is mandatory:

- provider resolution occurs once at startup;
- the raw provider is injected into the existing golden-path builder;
- all Web routes share that same application and Runtime;
- activation and read projections therefore observe the same selected
  provider and SQLite state;
- Web adapters never call discovery or the factory;
- tests may continue to inject a prepared Fake-backed application.

If resolution fails, the business application must not start with another
provider. The process may fail startup with a controlled diagnostic, or expose
only an explicit unavailable status boundary; it must not accept business
activation while pretending to be ready.

## 9. Provider management and Doctor

Provider management, Doctor and Web startup must call the same orchestrator or
the same underlying resolution service.

- `provider discover` remains read-only and never selects.
- `provider select <kind>` explicitly validates, then persists only the
  non-secret selection.
- `doctor --provider <kind>` validates an explicit process-local selection.
- `doctor --smoke` calls the resolved provider with synthetic, in-memory input
  through the existing guard and never writes Runtime state.
- Web uses the same resolved provider result for application construction.

Direct adapter construction in legacy Demo commands may remain for bounded
compatibility, but it is not the standard composition path and must not define
new configuration semantics.

## 10. Safe Runtime status API

The read-only endpoint is:

```text
GET /api/runtime
```

Its allowlisted contract is:

```json
{
  "version": "runtime-status-v1",
  "status": "ready",
  "provider": "ollama",
  "model": "qwen3.5:9b",
  "execution": "local",
  "selection_source": "saved_config",
  "health": "healthy"
}
```

Allowed status values:

- `ready`;
- `unconfigured`;
- `unavailable`;
- `invalid_configuration`;
- `degraded`.

The endpoint may return `null` for provider/model when unresolved. It must
clearly identify explicit Fake execution as synthetic/demo.

`selection_source` is one of:

- `command_line`;
- `environment`;
- `saved_config`;
- `injected`;
- `none`.

It must never return:

- an API key, token or credential value;
- an Authorization header;
- the name or value of unrelated environment variables;
- prompts, system instructions or raw model responses;
- local database, configuration or knowledge-file paths;
- traceback, request internals, Runtime objects or raw audit details.

`GET /api/runtime` is independent of the F03-D1 workspace, event, employee and
pulse projections. It does not change those contracts.

## 11. Failure behavior

| Condition | Required result |
|---|---|
| No explicit or saved selection | `unconfigured`; list candidates safely; construct no provider |
| Multiple discovered candidates | `unconfigured`; require explicit choice |
| Saved provider no longer reachable | `unavailable`; no alternate selection |
| Configured model absent | `invalid_configuration` or `unavailable`; never choose another model |
| Credential reference absent/rejected | Controlled unavailable/configuration failure; no secret echo |
| Factory construction failure | Business server does not become ready |
| Provider request failure after startup | Existing bounded Runtime/Web failure handling; same provider identity |
| Explicit Fake | Ready only as synthetic/demo, never real inference |

Diagnostics may include a safe provider kind, model identifier, health category
and selection source. They must not include response bodies, credentials,
tracebacks or sensitive local paths.

## 12. Verification invariants

Tests must prove:

- CLI options override explicit environment configuration;
- environment configuration overrides a saved selection;
- a saved selection is reloaded and revalidated;
- zero, one and multiple discovery candidates never auto-select;
- Fake is never selected without explicit intent;
- all four provider kinds are constructed through the existing factory;
- missing endpoint, model and credential references fail closed;
- saved selection affects the Web application's actual provider;
- activation reaches the selected provider and the same Runtime projections;
- `/api/runtime` reports safe status without credential leakage;
- F03-D1/F03-D2 projections and frontend integration remain unchanged.

Real AMD Linux/Ollama acceptance is a separate host exercise. Passing Windows
unit and loopback protocol tests must not be described as Linux or ROCm
validation.
