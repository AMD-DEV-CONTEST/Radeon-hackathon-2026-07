# NexusAI Universal World Model

**Version:** 1.0

Every NexusAI experience maps domain knowledge into six canonical concepts:

1. **World** — an isolated knowledge space.
2. **Source** — original input material and provenance.
3. **Entity** — something that exists or is referenced.
4. **Relationship** — a typed directed connection between entities.
5. **Event** — something that happened, optionally at a known time.
6. **Observation** — a derived statement with explicit provenance.

Observation provenance may be `source`, `deterministic`, `ai`, or `user`. AI observations can carry confidence values. This prevents model interpretation from silently becoming verified fact.

World-specific modules may extend domain semantics, but must preserve provenance, identity, typed relationships, events, and observation provenance.
