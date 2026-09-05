# Artifact Link Contract

## Admission

Producing services, Agent Harness, Chatbot UI, LinkRouter, and ArtifactService must
share one result identity and activation contract. Losing it can expose local paths
or make dataset and artifact identities interchangeable.

## Identity

Artifact links use one authority:

```text
artifact://<artifact_id>
```

Dataset ids identify registered data for later service or tool input. They are not
link authorities. A derived dataset intended for user download must also have a
ready export artifact.

A Chatbot source attachment is not an Artifact link. Harness may project the
original import's bounded label and an in-process local opening target from
Dataset provenance for the desktop UI. That target is neither persisted
conversation content nor provider input, and it must not be converted into an
Artifact identity merely to reopen a Thread.

Generic Chatbot-event diagnostic serialization and logging must redact that
opening target. The desktop bubble keeps it only in its short-lived local
activation map.

Legacy `view` query hints are accepted for compatibility but ignored. Artifact kind,
MIME type, and markdown syntax determine current presentation.

## Authority Flow

```text
producing service
  -> ArtifactService registers a ready local result
  -> tool or service result exposes artifact_id
  -> assistant markdown may reference artifact://<artifact_id>
  -> Chatbot passes activation to LinkRouter
  -> ArtifactService resolves and opens the registered local artifact
```

Markdown image syntax requests an inline image preview; an ordinary markdown link
requests a normal openable artifact. Both retain the same artifact id authority.

## Invariants

- ArtifactService owns registration, readiness, URI resolution, and local file
  activation. LinkRouter owns UI link dispatch.
- UI and provider-facing content do not construct, expose, or activate raw local
  paths as artifact identities. An ephemeral Chatbot source presentation may
  carry a local opening target only inside the desktop UI boundary; it is not an
  artifact URI, Markdown target, provider value, or canonical Message field.
- Remote worker paths are never artifact links. Remote outputs become linkable only
  after local finalization and registration.
- A missing registration or registered file is a service error and activation
  fails.
- Tool results expose identities, not prebuilt artifact URI strings; conversation
  presentation owns markdown construction.

## Verification

URI parsing and activation are covered through `tests/test_services.py`,
`tests/test_markdown_renderer.py`, and artifact paths in `tests/test_main.py` and
the Agent Harness test suites.
