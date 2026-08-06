# NexusAI Semantic Retrieval

**Version:** 1.0

## Purpose

Search World source chunks by relevance instead of database ordering or exact string lookup.

## v0.7.0 Local Baseline

This milestone uses a local HashingVectorizer with word and bigram features and cosine-equivalent similarity.

Advantages:

- zero API cost
- no model download
- deterministic tests
- Vercel/API friendly
- establishes a stable retrieval contract

This is a retrieval baseline, not the final GPU embedding architecture.

## Endpoint

GET `/api/worlds/{world_id}/search?q=...&top_k=5`

## Future Radeon Path

The retrieval interface is intentionally isolated so the local vectorizer can later be replaced by a real embedding model running on AMD Radeon Cloud. That phase will produce dense semantic embeddings and benchmark GPU inference against this CPU baseline.
