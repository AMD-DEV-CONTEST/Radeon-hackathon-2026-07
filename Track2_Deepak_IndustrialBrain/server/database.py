from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.hash import pbkdf2_sha256 as hasher
from .config import settings

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from .models import User
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        admin = User(
            username="admin",
            password_hash=hasher.hash("Admin@123"),
            display_name="Administrator",
            role="ADMIN"
        )
        db.add(admin)
        
    if not db.query(User).filter(User.username == "engineer").first():
        eng = User(
            username="engineer",
            password_hash=hasher.hash("Engineer@123"),
            display_name="Plant Engineer",
            role="ENGINEER"
        )
        db.add(eng)
    db.commit()
    db.close()
