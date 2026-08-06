# Track 2 Submission: ClaimCourt

## Team

Zi Fei Yu

## Application

ClaimCourt: A Private Local AI Evidence Court

## Summary

ClaimCourt is a private evidence-grounded local AI agent that compiles fuzzy human recollections into structured search plans, retrieves cited evidence from private workspaces, and turns disputed commitments into verdicts, contradiction timelines, and approval-gated decision briefs.

The verified stack runs on an AMD Radeon PRO W7900-class GPU with ROCm. Qwen3-14B BF16 is served through vLLM for the ClaimCourt intent LoRA and the controlled prosecution, defense, and judge stages. Local BGE embeddings, a local cross-encoder reranker, SQLite FTS5, BM25, metadata, and file-family authority rules support private retrieval without a closed remote model API.

## Track 2 Capabilities

- Local knowledge retrieval and RAG
- Tool routing and sensitive-record scanning
- Multi-step controlled agent workflow
- Persistent local query and evidence memory
- Permission-gated export and privacy controls

## Verified Radeon Evidence

- 320/320 frozen fuzzy-intent queries passed on the live Router, BGE embedding, and reranker stack.
- Unsafe wrong auto-selections: 0.
- Qwen3-14B court mode: local vLLM.
- First-token latency: 0.27 seconds.
- Generation throughput: 14.3 tokens/second.
- Full three-role court latency: 126.44 seconds.

## Materials

- Project description: `submission/ClaimCourt_Project_Description.pdf`
- Presentation: `submission/ClaimCourt_Presentation.pptx`
- Demo script: `submission/DEMO_SCRIPT.md`
- Demo video: [YouTube](https://youtu.be/Do_LJsUSFnQ)
- Source and setup: `README.md`

## Privacy Statement

The public demo corpus and benchmark are synthetic. No private participant documents, credentials, or private evaluation queries are included in this pull request. Core inference does not depend on a closed remote model API.
