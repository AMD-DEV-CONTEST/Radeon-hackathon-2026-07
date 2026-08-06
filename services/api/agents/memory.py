from datetime import datetime
from typing import Any

from sqlalchemy import Column, String, Text, DateTime, JSON

from models import Base, SessionLocal


class UserMemory(Base):
    __tablename__ = "user_memory"

    key = Column(String(128), primary_key=True)
    value = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectAsset(Base):
    __tablename__ = "project_assets"

    id = Column(String(36), primary_key=True)
    asset_type = Column(String(64), nullable=False)  # style, character, mesh, texture, depth_map
    name = Column(String(256), nullable=False)
    file_path = Column(String(512), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentMemory:
    """Lightweight memory layer for the 3D Director Agent.

    For now it stores user preferences (e.g., default style, print size) and
    reusable project assets in the same SQL database as the jobs.
    """

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    def get(self, key: str) -> Any | None:
        db = SessionLocal()
        try:
            row = db.query(UserMemory).filter(UserMemory.key == f"{self.namespace}:{key}").first()
            return row.value if row else None
        finally:
            db.close()

    def set(self, key: str, value: Any) -> None:
        db = SessionLocal()
        try:
            row = db.query(UserMemory).filter(UserMemory.key == f"{self.namespace}:{key}").first()
            if row:
                row.value = value
            else:
                row = UserMemory(key=f"{self.namespace}:{key}", value=value)
                db.add(row)
            db.commit()
        finally:
            db.close()

    def add_asset(self, asset_type: str, name: str, file_path: str | None = None, metadata: dict | None = None) -> str:
        import uuid
        db = SessionLocal()
        try:
            asset_id = str(uuid.uuid4())
            asset = ProjectAsset(
                id=asset_id,
                asset_type=asset_type,
                name=name,
                file_path=file_path,
                metadata_=metadata or {},
            )
            db.add(asset)
            db.commit()
            return asset_id
        finally:
            db.close()

    def list_assets(self, asset_type: str | None = None) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            q = db.query(ProjectAsset)
            if asset_type:
                q = q.filter(ProjectAsset.asset_type == asset_type)
            rows = q.order_by(ProjectAsset.created_at.desc()).limit(50).all()
            return [
                {
                    "id": r.id,
                    "type": r.asset_type,
                    "name": r.name,
                    "file_path": r.file_path,
                    "metadata": r.metadata_,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            db.close()


agent_memory = AgentMemory()
