"""
Episodic memory — structured retrieval of past *incidents* (as opposed to
unstructured runbook text), keyed on service name, severity, and recency.
This complements vector search: vector search finds semantically similar
text, episodic lookup finds "what actually happened last time on this
exact service", which the Synthesizer agent weighs more heavily.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import Incident, IncidentStatus


class EpisodicMemory:
    async def past_incidents_for_signal(
        self,
        db: AsyncSession,
        *,
        source: str,
        limit: int = 5,
    ) -> list[Incident]:
        stmt = (
            select(Incident)
            .where(Incident.source == source, Incident.status == IncidentStatus.RESOLVED)
            .order_by(Incident.resolved_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
