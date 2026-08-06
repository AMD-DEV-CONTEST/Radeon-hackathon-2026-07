# Xenix Product Truth

## Purpose and Pressure

Xenix is a local desktop workbench for non-technical business users, primarily
business and marketing staff. It turns tabular data into decision-ready analysis
through conversation, without requiring users to operate a data stack, choose
algorithms, or translate technical outputs on their own.

The product pressure is to preserve business meaning while reducing analytical
friction. Xenix should help users understand what the data says, what action it
supports, and what uncertainty remains.

## Claims and Evaluation

| Product claim | Rationale | Observable success | Expected evidence |
| --- | --- | --- | --- |
| Conversation is the primary work surface. | Business users should express goals in their own language. | A user can attach tabular data, ask a business question, and continue the work in one conversation. | Integrated conversation, attachment, and history coverage. |
| Data preparation preserves the source and produces explicit derived data. | Cleaning or reshaping must not silently destroy the original business record. | Prepared results are registered separately and remain available to later analysis. | Data-service and lineage contract coverage. |
| Results are explained in business terms and remain reviewable. | Metrics and model names alone do not support decisions. | The conversation explains meaning, actions, risks, and limitations; material outputs open as local artifacts. | Agent acceptance and artifact-activation coverage. |
| Reusable analyzers can be trained and applied without exposing algorithm plumbing. | Repeated business analysis should not require a notebook or ML interface. | A user can prepare roles, train or tune an analyzer, and apply the retained analyzer to compatible data. | Model-lifecycle integration coverage. |
| Product state and canonical outputs remain locally authoritative. | Optional remote capacity must not turn Xenix into a hosted backend. | Local services retain conversation, task, dataset, model, and artifact authority when remote ML execution is used. | Storage, worker, and artifact boundary coverage. |
| User knowledge can guide data analysis with source-linked evidence. | Business rules and operating experience often live outside datasets. | A user can import a supported document once and the Agent can retrieve a bounded, citable passage while analyzing data. | Knowledge import, lookup-tool, citation, and Agent benchmark coverage. |
| The interface supports English and Simplified Chinese. | Business users should work in the configured interface language. | The selected language persists and also guides the conversation language for new work. | Locale persistence and UI-switch coverage. |

## Capabilities and Workflows

1. Start or reopen a conversation and attach a supported local CSV or Excel file.
2. Ask Xenix to inspect, combine, clean, prepare, summarize, or visualize the
   registered data.
3. When useful, define data roles and train, tune, or apply a reusable analyzer.
4. Review explanations in the conversation and open generated datasets, charts,
   models, reports, and apply results as local artifacts.
5. Configure supported LLM providers and choose the LLM model used by the next
   assistant response without changing sampling already in progress.
6. Open the Knowledge Workspace, select or drop TXT, DOC/DOCX, PPT/PPTX, PDF, JPEG,
   or PNG material, and let the Agent apply relevant saved knowledge through
   source-linked lookup.
7. Open About to review the installed Xenix version and manually check for
   software updates. A confirmed download reports percentage progress in a
   modeless window before the user explicitly chooses whether to restart and
   apply it.

## Rules and Scope

- Xenix serves one local operator. Accounts, roles, tenancy, and concurrent-user
  coordination are out of scope.
- Xenix does not mutate or delete user-selected source files. Cleaning,
  preparation, and transformation create derived registered data.
- Dataset identities are inputs to later work. User-openable outputs are
  service-registered artifacts.
- Local services, SQLite state, and local canonical artifacts remain authoritative.
  SSH workers provide execution and cache capacity only.
- External LLM-provider APIs are adapters, not a Xenix-owned remote backend.
- MVP exposes one global Knowledge Library. Its internal identity permits future
  multiple-library instances, but no library-management UI is promised.
- Knowledge import preserves the selected source and canonical content locally.
  Local OCR is installed explicitly through the Knowledge Workspace and supports
  standalone JPEG/PNG sources and scanned PDF pages. PPTX uses the canonical Docling
  path; legacy PPT uses an explicit LibreOffice-to-PPTX normalization. VLM and
  Markdown are outside MVP.
- Browser-first operation, an always-on Xenix server, and hosted product authority
  are out of scope.
- Trial builds may enforce a build-time expiry and direct the user to a purchase or
  licensed-download path. They do not provide online license activation.

## Business Language

- **Dataset**: registered tabular data available to Xenix analysis and model work.
- **Artifact**: a service-registered result that the user can open or preview.
- **LLM model**: the provider model selected for a conversation's next assistant
  response.
- **Trained analyzer**: a reusable analysis or ML result that can be applied to
  compatible data; UI copy may call it a trained model.
- **ML worker**: local or SSH-backed execution capacity selected by Xenix services;
  it does not own product state or canonical outputs.
- **Knowledge Library**: the global collection of imported business knowledge that
  the Agent may search; it is distinct from conversation attachments and Datasets.
- **Knowledge Unit**: a bounded, source-located passage derived from the current
  canonical document and used as the atomic retrieval result.
