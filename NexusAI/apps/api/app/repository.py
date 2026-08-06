from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.models import WorldRecord
from nexus.world import World, WorldType

class WorldRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _to_domain(record: WorldRecord) -> World:
        return World(
            id=UUID(record.id),
            name=record.name,
            world_type=WorldType(record.world_type),
            description=record.description,
            metadata=record.metadata_json or {},
            created_at=record.created_at,
        )

    def list(self) -> list[World]:
        records = self.db.scalars(select(WorldRecord).order_by(WorldRecord.created_at.desc())).all()
        return [self._to_domain(record) for record in records]

    def get(self, world_id: UUID) -> World | None:
        record = self.db.get(WorldRecord, str(world_id))
        return self._to_domain(record) if record else None

    def create(self, world: World) -> World:
        record = WorldRecord(
            id=str(world.id),
            name=world.name,
            world_type=world.world_type.value,
            description=world.description,
            metadata_json=world.metadata,
            created_at=world.created_at,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_domain(record)
