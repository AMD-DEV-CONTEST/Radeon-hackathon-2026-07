"""
LaunchKart AI 2.0 — Memory Service

Manages persistent agent memory with ChromaDB vector search and Hybrid Ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.memory import MemoryEntryResponse, MemoryListResponse, MemorySearchResponse
from app.exceptions import NotFoundError
from app.infrastructure.database.models.memory_entry_model import MemoryEntryModel
from app.infrastructure.vector_store_client import vector_store

logger = structlog.get_logger(__name__)


class MemoryService:
    """Manages persistent memory entries with hybrid vector search capability."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_memories(
        self,
        user_id: UUID,
        memory_type: str | None = None,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> MemoryListResponse:
        query = select(MemoryEntryModel).where(MemoryEntryModel.user_id == user_id)
        if memory_type:
            query = query.where(MemoryEntryModel.memory_type == memory_type)
        if namespace:
            query = query.where(MemoryEntryModel.namespace == namespace)
        query = query.order_by(MemoryEntryModel.created_at.desc()).limit(limit).offset(offset)

        result = await self._db.execute(query)
        entries = result.scalars().all()

        if not entries and offset == 0:
            total_res = await self._db.execute(select(MemoryEntryModel).where(MemoryEntryModel.user_id == user_id).limit(1))
            if not total_res.scalar_one_or_none():
                await self._seed_demo_memories(user_id)
                result = await self._db.execute(query)
                entries = result.scalars().all()

        return MemoryListResponse(
            entries=[MemoryEntryResponse.model_validate(e) for e in entries],
            total=len(entries),
        )

    async def add_memory(self, user_id: UUID, content: str, memory_type: str, namespace: str, metadata: dict) -> UUID:
        """Add a new memory to PostgreSQL and Vector DB."""
        new_id = uuid.uuid4()
        
        # 1. Save to Relational DB for direct access
        db_entry = MemoryEntryModel(
            id=new_id,
            user_id=user_id,
            memory_type=memory_type,
            namespace=namespace,
            content=content,
            metadata=metadata
        )
        self._db.add(db_entry)
        await self._db.commit()

        # 2. Extract standard metadata for vector search
        collection_name = f"memory_{namespace}"
        vector_metadata = {
            "memory_type": memory_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": metadata.get("confidence", 80),
            "importance": metadata.get("importance", 50),
            "source_agent": metadata.get("source_agent", "unknown"),
            "launch_id": metadata.get("launch_id", "none")
        }

        # 3. Store in Vector DB
        try:
            vector_store.add_memory(
                collection_name=collection_name,
                document=content,
                metadata=vector_metadata,
                doc_id=str(new_id)
            )
        except Exception as e:
            logger.error("Failed to add memory to Vector DB", error=str(e), collection=collection_name)
            
        return new_id

    async def search_memories(
        self, user_id: UUID, query: str, limit: int = 10
    ) -> MemorySearchResponse:
        """
        Phase 5 Hybrid Semantic Search using ChromaDB vectors.
        Applies scoring: (Similarity * 0.5) + (Recency * 0.2) + (Confidence * 0.15) + (Importance * 0.15)
        """
        logger.info("Executing hybrid vector search", query=query)
        
        # Ensure demo memories are seeded if DB is empty
        total_res = await self._db.execute(select(MemoryEntryModel).where(MemoryEntryModel.user_id == user_id).limit(1))
        if not total_res.scalar_one_or_none():
            await self._seed_demo_memories(user_id)
        
        # 1. Search all vector collections
        raw_results = vector_store.search_all(query, n_results_per_collection=3)
        
        # 2. Score and rank results
        scored_results = []
        now = datetime.now(timezone.utc)
        
        for item in raw_results:
            # Distance is lower for closer vectors. Convert distance to similarity (0-1)
            # Chroma L2 distance usually ranges up to 2.0.
            distance = item['distance']
            similarity = max(0, 1.0 - (distance / 2.0))
            
            meta = item['metadata']
            
            # Recency (0-1): Decay over 30 days
            try:
                dt = datetime.fromisoformat(meta['timestamp'])
                days_old = (now - dt).days
                recency = max(0, 1.0 - (days_old / 30.0))
            except:
                recency = 0.5
                
            # Confidence & Importance (0-1)
            confidence = float(meta.get('confidence', 50)) / 100.0
            importance = float(meta.get('importance', 50)) / 100.0
            
            # Hybrid Score
            final_score = (similarity * 0.50) + (recency * 0.20) + (confidence * 0.15) + (importance * 0.15)
            
            scored_results.append((final_score, item))
            
        # 3. Sort by final score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        top_results = [item[1] for item in scored_results[:limit]]
        
        # 4. Fetch full DB entries for top results
        if not top_results:
            db_query = (
                select(MemoryEntryModel)
                .where(
                    MemoryEntryModel.user_id == user_id,
                    (MemoryEntryModel.content.ilike(f"%{query}%")) | (MemoryEntryModel.namespace.ilike(f"%{query}%")) | (MemoryEntryModel.memory_type.ilike(f"%{query}%"))
                )
                .limit(limit)
            )
            result = await self._db.execute(db_query)
            fallback_entries = result.scalars().all()
            if not fallback_entries:
                result = await self._db.execute(select(MemoryEntryModel).where(MemoryEntryModel.user_id == user_id).order_by(MemoryEntryModel.created_at.desc()).limit(limit))
                fallback_entries = result.scalars().all()
            return MemorySearchResponse(
                results=[MemoryEntryResponse.model_validate(e) for e in fallback_entries],
                query=query,
                total=len(fallback_entries),
            )
            
        ids = [UUID(item['id']) for item in top_results]
        db_query = select(MemoryEntryModel).where(MemoryEntryModel.id.in_(ids))
        result = await self._db.execute(db_query)
        entries_dict = {e.id: e for e in result.scalars().all()}
        
        # Re-order based on our score
        ordered_entries = []
        for r in top_results:
            eid = UUID(r['id'])
            if eid in entries_dict:
                ordered_entries.append(entries_dict[eid])

        return MemorySearchResponse(
            results=[MemoryEntryResponse.model_validate(e) for e in ordered_entries],
            query=query,
            total=len(ordered_entries),
        )

    async def delete_memory(self, memory_id: UUID, user_id: UUID) -> None:
        result = await self._db.execute(
            select(MemoryEntryModel).where(
                MemoryEntryModel.id == memory_id,
                MemoryEntryModel.user_id == user_id,
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise NotFoundError("Memory entry", str(memory_id))
        await self._db.delete(entry)

    async def _seed_demo_memories(self, user_id: UUID) -> None:
        """Seed initial realistic AMD demo memories if none exist."""
        logger.info("Seeding demo memory vectors for AMD launch team", user_id=str(user_id))
        demo_memories = [
            ("pricing", "insight", "Historical GPU pricing analysis shows $999 MSRP for AMD Radeon RX 7900 XTX yields optimal ROI and outcompetes rival cards in price-to-performance by 18%.", {"confidence": 94, "importance": 90, "source_agent": "Pricing Strategy Agent", "launch_id": "demo-launch-1"}),
            ("seo", "strategy", "Keywords '24GB VRAM', '4K gaming GPU', and 'ROCm AI inference' drive 3x higher organic search traffic on Amazon and Newegg.", {"confidence": 91, "importance": 85, "source_agent": "SEO Optimization Agent", "launch_id": "demo-launch-1"}),
            ("branding", "guideline", "AMD Radeon branding should emphasize 'Extreme Gaming' and 'Open AI Ecosystem' with vibrant red/dark aesthetics and futuristic typography.", {"confidence": 89, "importance": 80, "source_agent": "Branding & Visuals Agent", "launch_id": "demo-launch-1"}),
            ("competitor", "analysis", "NVIDIA RTX 4080 Super has 16GB VRAM; highlighting our 24GB VRAM advantage is critical for LLM fine-tuning creators and 4K gamers.", {"confidence": 96, "importance": 95, "source_agent": "Competitor Intelligence Agent", "launch_id": "demo-launch-1"}),
            ("marketplace", "rule", "Amazon A+ content formatting requires 5 feature bullets with exact VRAM specifications and PCIe 4.0 compatibility details.", {"confidence": 88, "importance": 75, "source_agent": "Marketplace Specialist", "launch_id": "demo-launch-1"}),
            ("marketing", "campaign", "Reddit r/localLLaMA and r/hardware target campaigns yield highest conversion rate for ROCm accelerated graphics cards.", {"confidence": 85, "importance": 80, "source_agent": "Marketing Campaign Agent", "launch_id": "demo-launch-1"}),
            ("seller", "partner", "Preferred distributor SYNNEX offers 2-day SLA shipping on wholesale AMD GPU bundles with co-op marketing funds.", {"confidence": 90, "importance": 70, "source_agent": "Seller Operations Agent", "launch_id": "demo-launch-1"}),
            ("pricing", "historical", "Promotional discount of 5% during Prime Day increased unit sales volume by 320% without cannibalizing Q4 margins.", {"confidence": 92, "importance": 85, "source_agent": "Pricing Strategy Agent", "launch_id": "demo-launch-1"}),
        ]
        for ns, mtype, content, meta in demo_memories:
            await self.add_memory(user_id=user_id, content=content, memory_type=mtype, namespace=ns, metadata=meta)
