"""Versioned local SQLite snapshots; validated transactional restore, no path input."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from uuid import UUID, uuid4
import zipfile

from sqlalchemy import select, func

from .app_config import VERSION, ensure_application_directories
from .database import Base
from .models import ImportJob

FORMAT_VERSION = 1
MAX_DATABASE_BYTES = 20 * 1024**3


def backup_path(backup_id: str) -> Path:
    try:
        safe_id = str(UUID(backup_id))
    except ValueError as error:
        raise ValueError("Invalid backup identifier") from error
    return ensure_application_directories()["backups"] / f"{safe_id}.aiopt-backup"


def digest(path):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def require_idle(db):
    if db.bind.dialect.name != "sqlite":
        raise ValueError("Use database-native backup tools for enterprise databases")
    active = db.scalar(select(func.count()).select_from(ImportJob).where(
        ImportJob.status.in_(["UPLOADED", "ANALYZING", "READY", "IMPORTING"])))
    if active:
        raise ValueError("Finish or cancel pending imports before backup or restore")


def create_backup(db):
    require_idle(db)
    backup_id = str(uuid4())
    destination = backup_path(backup_id)
    with tempfile.TemporaryDirectory(prefix="aiopt-backup-") as folder:
        snapshot = Path(folder) / "database.sqlite"
        with closing(sqlite3.connect(snapshot)) as target:
            db.connection().connection.driver_connection.backup(target)
        manifest = {"format_version": FORMAT_VERSION, "app_version": VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "database_sha256": digest(snapshot), "secrets_included": False}
        temporary = destination.with_suffix(".pending")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.write(snapshot, "database.sqlite")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return {"backup_id": backup_id, **manifest, "bytes": destination.stat().st_size}


@contextmanager
def validated_backup(backup_id):
    path = backup_path(backup_id)
    with tempfile.TemporaryDirectory(prefix="aiopt-restore-") as folder:
        snapshot = Path(folder) / "database.sqlite"
        with zipfile.ZipFile(path) as archive:
            if sorted(archive.namelist()) != ["database.sqlite", "manifest.json"]:
                raise ValueError("Unexpected backup contents")
            if archive.getinfo("manifest.json").file_size > 8192 or archive.getinfo("database.sqlite").file_size > MAX_DATABASE_BYTES:
                raise ValueError("Backup exceeds supported size")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format_version") != FORMAT_VERSION or manifest.get("app_version") != VERSION or manifest.get("secrets_included") is not False:
                raise ValueError("Unsupported backup version")
            with archive.open("database.sqlite") as source, snapshot.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        if digest(snapshot) != manifest.get("database_sha256"):
            raise ValueError("Backup integrity check failed")
        source = sqlite3.connect(f"{snapshot.as_uri()}?mode=ro", uri=True)
        try:
            source.execute("PRAGMA trusted_schema=OFF")
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
            objects = source.execute("SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if any(kind in {"trigger", "view"} for _, kind in objects):
                raise ValueError("Executable schema objects are not permitted")
            if {name for name, kind in objects if kind == "table"} != set(Base.metadata.tables):
                raise ValueError("Backup schema does not match this application")
            for table in Base.metadata.sorted_tables:
                columns = source.execute(f'PRAGMA table_info("{table.name}")').fetchall()
                if [row[1] for row in columns] != [column.name for column in table.columns]:
                    raise ValueError("Backup columns do not match this application")
            yield source, manifest
        finally:
            source.close()


def restore_backup(db, backup_id, audit_callback):
    require_idle(db)
    # Fully validate before any mutation or recovery snapshot.
    with validated_backup(backup_id) as (source, manifest):
        recovery = create_backup(db)
        try:
            connection = db.connection()
            # Real write transaction protects against concurrent SQLite writers.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            require_idle(db)
            for table in Base.metadata.sorted_tables:
                if table.name == "audit_events":
                    continue  # History cannot be erased or forged through restore.
                connection.exec_driver_sql(f'DELETE FROM "{table.name}"')
                columns = ",".join(f'"{col.name}"' for col in table.columns)
                cursor = source.execute(f'SELECT {columns} FROM "{table.name}"')
                placeholders = ",".join("?" for _ in table.columns)
                while batch := cursor.fetchmany(1000):
                    connection.exec_driver_sql(f'INSERT INTO "{table.name}" ({columns}) VALUES ({placeholders})', batch)
            audit_callback(db, "backup.restored", "backup", backup_id, recovery_backup_id=recovery["backup_id"])
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"restored": True, "recovery_backup_id": recovery["backup_id"], "version": manifest["app_version"]}
