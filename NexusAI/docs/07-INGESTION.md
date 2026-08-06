# NexusAI Universal Ingestion Engine

**Version:** 1.0

## Supported MVP Formats

- TXT
- JSON
- PDF
- DOCX

## Pipeline

Upload -> Validate -> Parse -> Normalize -> SHA-256 checksum -> Chunk -> Persist Source -> Persist Chunks

The ingestion layer does not perform AI extraction in v0.5.0. Its responsibility is deterministic conversion of source material into normalized text chunks with provenance.

## Limits

The MVP upload API rejects files larger than 10 MB.

## Endpoints

- POST `/api/worlds/{world_id}/sources/upload`
- GET `/api/worlds/{world_id}/sources`
- GET `/api/worlds/{world_id}/sources/{source_id}/chunks`

## Next Phase

v0.6.0 consumes these chunks to extract candidate Entities, Relationships, Events, and Observations.
