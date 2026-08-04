# About Nova

Nova is a private, locally deployed AI agent built for the AMD AI DevMaster
Hackathon (Track 2: Development & Local Deployment of Private AI Agents).

## Design goals

- **Local-first**: the core language model runs on an AMD Radeon GPU via the
  ROCm software stack. No document or query is sent to a third-party API for
  core functionality.
- **Grounded answers**: Nova retrieves relevant chunks from a local knowledge
  base (Retrieval-Augmented Generation) instead of relying purely on the
  model's training data.
- **Tool use**: Nova can list and read files from an explicitly allowed
  directory, and perform simple calculations, demonstrating tool invocation
  and workflow orchestration.
- **Memory**: Nova keeps a bounded window of recent conversation turns so it
  can handle natural, multi-turn follow-up questions.
- **Privacy by design**: file-access tools are restricted to an allow-list of
  directories (`config.ALLOWED_TOOL_DIRS`). Any path outside that list is
  refused automatically, regardless of what is asked.

## Replace this file

Delete or replace the contents of `data/sample_docs/` with your own
documents, then re-run `python ingest.py` to rebuild the local knowledge
base around your real use case.
