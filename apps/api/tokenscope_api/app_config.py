"""Application identity, filesystem, and structured logging standards."""
from __future__ import annotations
import json, logging, os, platform, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "AI Optimization Tool"
APP_SLUG = "AIOptimizationTool"
REPOSITORY = "AI_optimization_tool"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DATA_SUBDIRECTORIES = ("database", "logs", "backups", "exports", "cache", "config")

def application_data_dir() -> Path:
    override = os.getenv("AIOPT_DATA_DIR")
    if override: return Path(override).expanduser().resolve()
    if os.getenv("AIOPT_RUNTIME") == "desktop" or getattr(sys, "frozen", False):
        return Path(os.getenv("LOCALAPPDATA", Path.home() / ".local" / "share")) / APP_SLUG
    return ROOT / "database" / "sqlite" / "development-data"

def ensure_application_directories(root: Path | None = None) -> dict[str, Path]:
    base = root or application_data_dir(); base.mkdir(parents=True, exist_ok=True)
    paths = {name: base / name for name in DATA_SUBDIRECTORIES}
    for path in paths.values(): path.mkdir(parents=True, exist_ok=True)
    return paths

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"timestamp":self.formatTime(record,"%Y-%m-%dT%H:%M:%S%z"),"level":record.levelname,"logger":record.name,"message":record.getMessage()}, ensure_ascii=False)

def configure_logging() -> None:
    log_dir=ensure_application_directories()["logs"]; formatter=JsonFormatter()
    for name,filename,level in (("aiopt.application","application.log",logging.INFO),("aiopt.api","api.log",logging.INFO),("aiopt.errors","errors.log",logging.ERROR)):
        logger=logging.getLogger(name)
        if not logger.handlers:
            handler=RotatingFileHandler(log_dir/filename,maxBytes=5_000_000,backupCount=5,encoding="utf-8");handler.setFormatter(formatter);logger.addHandler(handler)
        logger.setLevel(level);logger.propagate=False

def build_information() -> dict[str, str]:
    return {"name":APP_NAME,"version":VERSION,"build_type":os.getenv("AIOPT_BUILD_TYPE","Development"),"architecture":platform.machine() or "unknown","repository":REPOSITORY,"license":"Apache-2.0"}
