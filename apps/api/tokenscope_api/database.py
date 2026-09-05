import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .app_config import application_data_dir, ensure_application_directories

DEFAULT_DB = ensure_application_directories(application_data_dir())["database"] / "ai-optimization-tool.db"
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("TOKENSCOPE_DATABASE_URL", f"sqlite:///{DEFAULT_DB.as_posix()}")

if DATABASE_URL.startswith("sqlite:///"):
    Path(DATABASE_URL.removeprefix("sqlite:///")) .parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
