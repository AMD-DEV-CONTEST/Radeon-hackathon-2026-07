# NexusAI Extraction Pipeline

**Version:** 1.0

## Goal

Transform normalized source chunks into candidate structured knowledge and materialize supported Entities and Relationships in the World graph.

## v0.6.0 Strategy

This milestone deliberately starts with deterministic rule-based extraction.

Why:

- Free to run.
- Fully testable.
- Produces explainable results.
- Establishes the extraction contract before GPU/LLM integration.
- Gives future AI extractors a stable interface.

## Flow

Source Chunks -> Rule Extraction -> Candidate Entities -> Candidate Relationships -> Deduplication -> Persistent Knowledge Graph

## Endpoint

POST `/api/worlds/{world_id}/sources/{source_id}/extract`

## Current Relationship Rules

- LIVES_IN
- WORKS_WITH
- VISITED
- MAINTAINS
- ADVISES
- LOCATED_IN
- CONNECTED_TO

## Provenance

Created Entities and Relationships carry the originating Source ID.

## Next

v0.7.0 introduces semantic embeddings and retrieval. Later GPU-backed extraction can supplement deterministic rules without replacing the core graph contract.
