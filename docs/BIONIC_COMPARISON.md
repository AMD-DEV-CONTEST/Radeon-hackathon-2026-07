# Bionic-Graph Comparison & Recurrence Gap

## Comparison Summary

| Aspect | Bionic-Graph | GraphVoice | Gap |
|--------|-------------|------------|-----|
| **Lang** | Rust (single binary) | Python + Flask + Neo4j Docker | Deployment complexity |
| **Storage** | Custom block engine (16KB blocks, WAL) | Neo4j 5 Community | Neo4j heavier but battle-tested |
| **Query** | Gremlin (22 pipeline steps) | Cypher + safe templates (10) | Gremlin richer, Cypher simpler |
| **Search** | jieba-rs token-indexed (sub-ms) | `CONTAINS` full scan + GraphRAG | Token index would speed up keyword search |
| **Traversal** | Bionic Neuronal Spread (attention-based BFS with decay) | BFS via Cypher `MATCH` hops | Attention weighting adds relevance ranking |
| **Temporal** | Time travel (point-in-time MVCC) | Event time_period (string) only | Time travel enables "what did I know last year?" |
| **Agent lifecycle** | load → plan → act (3 phases) | interview → graph → regenerate | Plan→act phase would add proactive suggestions |
| **Recurrence** | Not supported | Not supported | **CRITICAL GAP — see below** |
| **Ranking** | Self-updating atime/rank system | Manual order field on Event | Auto-ranking would improve retrieval quality |
| **Audio / Voice** | None | Full pipeline (STT, VAD, TTS, AudioWorklet) | GraphVoice unique advantage |
| **Multi-graph** | Named, isolated graphs | Single Neo4j database | Multi-graph would separate user sessions cleanly |

## Adoptable Patterns from Bionic-Graph

1. **self_soul.md template** — structured Markdown as ground-truth scaffold for the interviewer
2. **LLM output logging** — every extraction saved as timestamped JSON for debugging
3. **Priority + rank on Event nodes** — self-updating relevance scoring
4. **Dedup by name as explicit pattern** — vertex name = unique key, always

## Recurrence Gap (ROADMAP)

### Problem

Neither framework handles **repetitive life patterns** — things that happen repeatedly over decades:
- "I've had migraines every winter for 20 years" (chronic illness)
- "I go to the same café every Sunday morning" (habit/routine)
- "I return to that beach every summer" (annual ritual)
- "I've moved 8 times in 10 years" (recurring instability)
- "Every spring, I get depressed" (seasonal pattern)

### Why Events/Edges Can't Model Recurrence

- 20 years of daily café visits = 7,300 Event nodes — graph bloat
- 20 years of annual migraines compressed to 1 Event — information loss
- No way to query: "how often?", "is it getting worse?", "when did it start vs stop?"

### Proposed Solution: Pattern Node Type

```
Entity types (current 7):  person | object | place | concept | skill | body_part | feeling | trait
                      NEW: pattern

Pattern {name, type: "pattern", description}
Properties: interval, frequency, first_date, last_date, estimated_count

Frequency enum: daily | weekly | monthly | seasonally | annually | periodically

Relationships:
  (:Entity)-[:HAS_PATTERN]->(:Pattern)           -- who/what this pattern belongs to
  (:Pattern)-[:EXAMPLE]->(:Event)                  -- 2-5 concrete examples linked to the pattern
  (:Pattern)-[:LOCATED_AT]->(:Entity {type: "place"}) -- where the pattern occurs
  (:Pattern)-[:TRIGGERED_BY]->(:Entity)            -- what causes/triggers it
```

### Example

```
(Entity "我" {type: "person"})
  -[:HAS_PATTERN]-> (Pattern "冬季偏头痛" {
      interval: "every winter",
      frequency: "seasonally",
      first_date: "2015-01",
      last_date: "2023-12",
      estimated_count: 8
    })
    -[:EXAMPLE]-> (Event "2015第一次发作" {order: 15})
    -[:EXAMPLE]-> (Event "2022最严重那次" {order: 47})
    -[:TRIGGERED_BY]-> (Entity "气压变化" {type: "concept"})
```

This keeps 1 Pattern node instead of 8 duplicated Event nodes, preserves the "how often" query, and links to concrete examples for the "is it getting worse?" question.

### Implementation Plan

| Step | When | Effort |
|------|------|--------|
| Add `pattern` to Entity type enum | Now | Small |
| Add `Pattern` properties to story_graph.py | Now | Small |
| Update structurization prompt to detect recurrence | Next | Medium |
| Update interviewer FSM with "routines" phase | Next | Small |
| Test with real recurrent life patterns | Next | Medium |

### Open Question

Even with Pattern nodes, the current schema has a flat temporal model. Should we consider:
- A time-series overlay (timeline of Entity states over time)?
- NamedGraphs (Bionic-Graph approach) for different time periods?
- Versioned properties on single entities (how a relationship evolves)?
