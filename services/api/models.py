import enum
import uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

Base = declarative_base()


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    GENERATING_MULTIVIEW = "generating_multiview"
    GENERATING_3D = "generating_3d"
    POSTPROCESSING = "postprocessing"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String(32), default=JobStatus.PENDING.value, nullable=False)
    input_image_path = Column(String(512), nullable=False)
    style = Column(String(128), default="realistic")
    prompt = Column(Text, default="")
    output_mode = Column(String(32), default="fullcolor_3d")

    # intermediate / final artifacts
    multiview_image_paths = Column(JSON, default=list)
    result_model_path = Column(String(512), nullable=True)
    result_preview_path = Column(String(512), nullable=True)
    print_report = Column(JSON, nullable=True)

    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
