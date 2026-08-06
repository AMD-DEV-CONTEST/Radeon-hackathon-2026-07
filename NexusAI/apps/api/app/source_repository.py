from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.models import SourceChunkRecord, SourceRecord
from nexus.world import Source

class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_with_chunks(self, source: Source, checksum: str, chunks: list[str]) -> Source:
        record = SourceRecord(
            id=str(source.id),
            world_id=str(source.world_id),
            name=source.name,
            source_type=source.source_type,
            uri=source.uri,
            checksum=checksum,
            metadata_json=source.metadata,
        )
        self.db.add(record)
        for index, text in enumerate(chunks):
            self.db.add(SourceChunkRecord(
                source_id=str(source.id),
                world_id=str(source.world_id),
                chunk_index=index,
                text=text,
                metadata_json={},
            ))
        self.db.commit()
        return source

    def list_sources(self, world_id: UUID):
        return self.db.scalars(
            select(SourceRecord).where(SourceRecord.world_id == str(world_id))
        ).all()

    def list_chunks(self, source_id: UUID):
        return self.db.scalars(
            select(SourceChunkRecord)
            .where(SourceChunkRecord.source_id == str(source_id))
            .order_by(SourceChunkRecord.chunk_index)
        ).all()
