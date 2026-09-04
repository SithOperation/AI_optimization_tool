"""
Large-file streaming telemetry import handler.

Supports CSV and JSON files up to 500 MB with:
- Streaming/chunked parsing (no full file in memory)
- Column mapping and alias resolution
- Row-by-row validation
- Chunked database inserts (1000-5000 rows per transaction)
- Progress reporting via callback
- Duplicate detection (by event_id)
- Temporary file cleanup
"""

import asyncio
import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .app_config import ensure_application_directories
from .models import ImportJob, TelemetryEvent
from .schemas import EventCreate

MAX_FILE_SIZE = 500_000_000
MAX_UPLOAD_CHUNK_SIZE = 5_000_000
MAX_RECORD_CHARS = 2_000_000
STALE_IMPORT_SECONDS = 24 * 60 * 60
_upload_locks: dict[str, threading.Lock] = {}
_upload_locks_guard = threading.Lock()
csv.field_size_limit(MAX_RECORD_CHARS)


# Known aliases for common column names
KNOWN_ALIASES = {
    "input_tokens": ["prompt_tokens", "input_token_count", "tokens_in"],
    "output_tokens": ["completion_tokens", "output_token_count", "tokens_out"],
    "estimated_total_cost": ["total_cost", "cost"],
    "model": ["model_name", "model_id"],
    "provider": ["vendor", "provider_name"],
    "latency_ms": ["latency", "response_time", "duration_ms"],
    "timestamp": ["created_at", "time", "datetime", "event_time"],
    "application": ["app", "service", "application_name"],
    "success": ["is_success", "succeeded"],
    "cached_input_tokens": ["cache_input_tokens", "cached_tokens"],
    "retry_count": ["retries", "retry"],
    "cache_hit": ["is_cache_hit", "cached"],
    "total_tokens": ["tokens_total"],
    "department": [],
    "team": [],
    "workload": [],
    "request_id": [],
    "status_code": [],
    "error_type": [],
}

# Reverse map: alias -> canonical
ALIAS_REVERSE = {}
for canonical, aliases in KNOWN_ALIASES.items():
    ALIAS_REVERSE[canonical] = canonical
    for alias in aliases:
        ALIAS_REVERSE[alias] = canonical


class ImportError(Exception):
    """Base exception for import operations."""
    pass


class FileValidationError(ImportError):
    """File failed validation."""
    pass


class ParseError(ImportError):
    """Error parsing file content."""
    pass


def validate_file_metadata(filename: str, file_size: int, file_format: str) -> None:
    """Validate filename, size, and format before processing."""
    max_size = MAX_FILE_SIZE

    # Validate size
    if file_size <= 0:
        raise FileValidationError("File size must be greater than 0")
    if file_size > max_size:
        raise FileValidationError(
            f"File exceeds maximum size of {max_size / 1_000_000:.0f} MB"
        )

    # Validate extension
    ext = Path(filename).suffix.lower()
    if file_format == "csv" and ext != ".csv":
        raise FileValidationError("File format CSV requires .csv extension")
    if file_format == "json" and ext not in [".json", ".jsonl"]:
        raise FileValidationError("File format JSON requires .json or .jsonl extension")

    # Validate filename (prevent path traversal)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise FileValidationError("Invalid filename (path traversal detected)")
    if len(filename) > 255:
        raise FileValidationError("Filename too long (max 255 characters)")


def guess_csv_delimiter(sample: str) -> str:
    """Detect CSV delimiter from sample."""
    delimiters = [",", ";", "\t", "|"]
    max_fields = 0
    best_delim = ","

    for delim in delimiters:
        reader = csv.reader(io.StringIO(sample), delimiter=delim)
        try:
            first_row = next(reader, None)
            field_count = len(first_row) if first_row else 0
            if field_count > max_fields:
                max_fields = field_count
                best_delim = delim
        except Exception:
            pass

    return best_delim


def guess_encoding(data: bytes) -> str:
    """Detect file encoding."""
    # Try UTF-8 first (most common)
    try:
        data.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        pass

    # Try UTF-16
    try:
        data.decode("utf-16")
        return "UTF-16"
    except UnicodeDecodeError:
        pass

    # Try Latin-1 (fallback, always succeeds)
    try:
        data.decode("latin-1")
        return "Latin-1"
    except UnicodeDecodeError:
        pass

    return "UTF-8"  # Default fallback


def parse_csv_rows(
    content: str, delimiter: str, chunk_size: int = 100
) -> Iterator[dict]:
    """Parse CSV content row by row, yielding dicts."""
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        raise ParseError("CSV has no headers")

    for row in reader:
        # Filter out empty rows
        if any(v and v.strip() for v in row.values()):
            yield dict(row)


def parse_json_rows(content: str) -> Iterator[dict]:
    """Parse JSON content (array or line-delimited)."""
    content = content.strip()

    # Try line-delimited JSON first
    if not content.startswith("["):
        for line in content.split("\n"):
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ParseError(f"Invalid JSON line: {e}")
        return

    # Try JSON array
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
                else:
                    raise ParseError("JSON array contains non-object items")
        else:
            raise ParseError("JSON must be an array or line-delimited objects")
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}")


class LimitedTextLines:
    """Iterator that rejects pathological CSV/JSONL records without buffering them fully."""

    def __init__(self, handle):
        self.handle = handle

    def __iter__(self):
        return self

    def __next__(self):
        line = self.handle.readline(MAX_RECORD_CHARS + 1)
        if not line:
            raise StopIteration
        if len(line) > MAX_RECORD_CHARS or (len(line) == MAX_RECORD_CHARS + 1 and not line.endswith("\n")):
            raise ParseError("A source record exceeds the 2 MB safety limit")
        if "\x00" in line:
            raise ParseError("NULL bytes are not allowed in import files")
        return line


def stream_json_array(handle) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    eof = False
    while True:
        if not eof and len(buffer) < 64_000:
            block = handle.read(64_000)
            eof = not block
            buffer += block
        buffer = buffer.lstrip()
        if not started:
            if not buffer and eof:
                raise ParseError("JSON file is empty")
            if not buffer:
                continue
            if buffer[0] != "[":
                raise ParseError("JSON must be an array or line-delimited objects")
            buffer = buffer[1:]
            started = True
        buffer = buffer.lstrip()
        if buffer.startswith(","):
            buffer = buffer[1:].lstrip()
        if buffer.startswith("]"):
            if buffer[1:].strip() or not eof:
                remainder = buffer[1:] + (handle.read() if not eof else "")
                if remainder.strip():
                    raise ParseError("Unexpected data after JSON array")
            return
        try:
            item, end = decoder.raw_decode(buffer)
        except json.JSONDecodeError as error:
            if eof:
                raise ParseError("Invalid or incomplete JSON array") from error
            if len(buffer) > MAX_RECORD_CHARS:
                raise ParseError("A JSON object exceeds the 2 MB safety limit") from error
            block = handle.read(64_000)
            eof = not block
            buffer += block
            continue
        if not isinstance(item, dict):
            raise ParseError("JSON array contains non-object items")
        yield item
        buffer = buffer[end:]


def iter_file_rows(path: Path, file_format: str, encoding: str, delimiter: str = ",") -> Iterator[dict]:
    with path.open("r", encoding=encoding, errors="strict", newline="") as handle:
        if file_format == "csv":
            reader = csv.DictReader(LimitedTextLines(handle), delimiter=delimiter)
            if not reader.fieldnames:
                raise ParseError("CSV has no headers")
            for row in reader:
                if None in row:
                    raise ParseError("CSV row contains more fields than the header")
                if any(value and value.strip() for value in row.values()):
                    yield dict(row)
            return
        first = handle.read(1)
        while first and first.isspace():
            first = handle.read(1)
        handle.seek(0)
        if first == "[":
            yield from stream_json_array(handle)
        else:
            for line in LimitedTextLines(handle):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ParseError("Invalid JSON line") from error
                if not isinstance(item, dict):
                    raise ParseError("Each JSON line must be an object")
                yield item


def import_directory() -> Path:
    path = ensure_application_directories()["cache"] / "tokenscope_imports"
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise FileValidationError("Import storage cannot be a symbolic link")
    return path


def cleanup_stale_import_files(max_age_seconds: int = STALE_IMPORT_SECONDS) -> int:
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in import_directory().glob("*.tmp"):
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def auto_map_columns(csv_headers: list[str]) -> dict[str, str]:
    """Attempt automatic column mapping using known aliases."""
    mapping = {}

    for header in csv_headers:
        canonical = ALIAS_REVERSE.get(header.lower().replace(" ", "_"))
        if canonical:
            mapping[header] = canonical

    return mapping


def coerce_value(value: str, field_name: str) -> any:
    """Coerce string value to appropriate type."""
    if value is None:
        return None
    
    # Convert to string if numeric
    if isinstance(value, (int, float)):
        if field_name in [
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "total_tokens",
            "context_window",
            "retry_count",
        ]:
            return int(value)
        elif field_name in [
            "latency_ms",
            "estimated_total_cost",
            "input_price_per_million",
            "output_price_per_million",
        ]:
            return float(value)
        else:
            return value
    
    # Handle string values
    if isinstance(value, str):
        if not value or value.strip() == "":
            return None
        value = value.strip()
    else:
        return value

    # Token fields
    if field_name in [
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "total_tokens",
        "context_window",
        "retry_count",
    ]:
        try:
            return int(value)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot parse '{value}' as integer for {field_name}")

    # Float fields
    if field_name in [
        "latency_ms",
        "time_to_first_token_ms",
        "tokens_per_second",
        "estimated_input_cost",
        "estimated_output_cost",
        "estimated_total_cost",
        "context_utilization",
    ]:
        try:
            return float(value)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot parse '{value}' as float for {field_name}")

    # Boolean fields
    if field_name in ["success", "cache_hit"]:
        if value.lower() in ["true", "1", "yes", "y"]:
            return True
        if value.lower() in ["false", "0", "no", "n"]:
            return False
        raise ValueError(f"Cannot parse '{value}' as boolean for {field_name}")

    # Integer fields (status_code, retry_count)
    if field_name in ["status_code", "retry_count"]:
        if field_name == "status_code" and value:
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        try:
            return int(value)
        except (ValueError, TypeError):
            if field_name == "retry_count":
                return 0
            return None

    # String fields: return as-is
    return value


def validate_event(row_dict: dict, mapping: dict[str, str]) -> tuple[dict, list[str]]:
    """
    Map and validate a row against EventCreate schema.
    Returns (validated_dict, errors).
    """
    errors = []
    event_data = {}

    # Apply mapping
    for csv_col, event_field in mapping.items():
        if csv_col in row_dict:
            raw_value = row_dict[csv_col]
            try:
                coerced = coerce_value(raw_value, event_field)
                if coerced is not None:
                    event_data[event_field] = coerced
            except ValueError as e:
                errors.append(f"{event_field}: {str(e)}")

    # If there are already errors, don't validate against schema
    if errors:
        return None, errors

    # Validate against EventCreate schema
    try:
        event = EventCreate(**event_data, source="import")
        return event.model_dump(), []
    except Exception as e:
        return None, [str(e)]


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class StreamingImporter:
    """Manage large-file import workflow."""

    def __init__(self, import_id: str, temp_dir: str | None = None):
        self.import_id = import_id
        self.temp_dir = Path(temp_dir) if temp_dir else ensure_application_directories()["cache"]
        self.temp_file_path = None
        self.job: ImportJob | None = None

    def get_temp_path(self) -> Path:
        """Get the path for this import's temp file."""
        if not self.temp_file_path:
            import_dir = Path(self.temp_dir) / "tokenscope_imports"
            import_dir.mkdir(parents=True, exist_ok=True)
            if import_dir.is_symlink():
                raise FileValidationError("Import storage cannot be a symbolic link")
            self.temp_file_path = import_dir / f"{self.import_id}.tmp"
        return self.temp_file_path

    async def receive_file_chunk(self, chunk: bytes) -> None:
        """Append chunk to temp file."""
        if len(chunk) > MAX_UPLOAD_CHUNK_SIZE:
            raise FileValidationError("Upload chunk exceeds the 5 MB limit")
        path = self.get_temp_path()
        with path.open("ab") as f:
            f.write(chunk)

    async def receive_upload(self, upload, declared_file_size: int) -> int:
        """Stream one multipart chunk to disk while enforcing cumulative limits."""
        with _upload_locks_guard:
            lock = _upload_locks.setdefault(self.import_id, threading.Lock())
        received = 0
        parts = []
        while True:
            part = await upload.read(1_000_000)
            if not part:
                break
            received += len(part)
            if received > MAX_UPLOAD_CHUNK_SIZE:
                raise FileValidationError("Upload chunk exceeds the 5 MB limit")
            parts.append(part)
        path = self.get_temp_path()
        with lock:
            existing = path.stat().st_size if path.exists() else 0
            if existing + received > declared_file_size or existing + received > MAX_FILE_SIZE:
                raise FileValidationError("Uploaded data exceeds the declared file size")
            with path.open("ab") as handle:
                for part in parts:
                    handle.write(part)
        return received

    def verify_complete(self, declared_file_size: int) -> None:
        path = self.get_temp_path()
        if not path.is_file() or path.is_symlink() or path.stat().st_size != declared_file_size:
            raise FileValidationError("Upload is incomplete or does not match the declared file size")

    async def analyze_file(
        self, filename: str, file_format: str, progress: Callable | None = None
    ) -> dict:
        """
        Analyze uploaded file: detect format, encoding, delimiter, row count, sample.
        Updates ImportJob in DB.
        """
        path = self.get_temp_path()
        if not path.exists():
            raise FileValidationError("File not found in temp storage")

        # Inspect only a bounded prefix for encoding and delimiter detection.
        with open(path, "rb") as f:
            raw_data = f.read(64_000)

        encoding = guess_encoding(raw_data)

        sample_rows = []
        total_rows = 0
        rejected_samples = []
        rejected_count = 0
        detected_delimiter = None
        validation_summary = {"valid_rows": 0, "rejected_rows": 0, "warnings": 0}

        try:
            if file_format == "csv":
                detected_delimiter = guess_csv_delimiter(raw_data.decode(encoding, errors="strict")[:10000])
            rows_iter = iter_file_rows(path, file_format, encoding, detected_delimiter or ",")

            # Scan entire file for row count and collect samples
            for row_num, row in enumerate(rows_iter, 1):
                total_rows = row_num
                if row_num <= 50:
                    sample_rows.append(row)

                if progress and row_num % 1000 == 0:
                    progress({"status": "analyzing", "rows_analyzed": row_num})

            validation_summary["valid_rows"] = max(0, total_rows - rejected_count)
            validation_summary["rejected_rows"] = rejected_count

        except ParseError as e:
            raise FileValidationError(f"Parse error: {str(e)}")

        # Update DB
        db = SessionLocal()
        try:
            stmt = select(ImportJob).where(ImportJob.import_id == self.import_id)
            job = db.execute(stmt).scalar_one_or_none()
            if job:
                job.total_rows = total_rows
                job.status = "READY"
                job.detected_encoding = encoding
                job.detected_delimiter = detected_delimiter or ","
                job.sample_rows = sample_rows
                db.commit()
                self.job = job
        finally:
            db.close()

        return {
            "total_rows": total_rows,
            "detected_encoding": encoding,
            "detected_delimiter": detected_delimiter or ",",
            "sample_rows": sample_rows,
            "validation_summary": validation_summary,
        }

    async def execute_import(
        self,
        mapping: dict[str, str],
        duplicate_handling: str = "skip",
        progress: Callable | None = None,
        chunk_size: int = 1000,
    ) -> dict:
        """
        Execute the import: parse file, validate rows, insert into DB in chunks.
        Returns import results summary.
        """
        path = self.get_temp_path()
        if not path.exists():
            raise FileValidationError("File not found in temp storage")

        if not mapping:
            raise ImportError("Column mapping is required before committing an import")

        db = SessionLocal()
        try:
            stmt = select(ImportJob).where(ImportJob.import_id == self.import_id)
            self.job = db.execute(stmt).scalar_one_or_none()
            if not self.job:
                raise FileValidationError("Import not found")

            encoding = self.job.detected_encoding or "UTF-8"
            file_format = self.job.format

            pending_rows = []
            rejected_rows = []
            duplicate_skipped = 0
            processed = 0
            accepted_total = 0
            inserted_total = 0
            before_count = db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0

            if file_format == "csv":
                delimiter = self.job.detected_delimiter or ","
            else:
                delimiter = ","
            rows_iter = iter_file_rows(path, file_format, encoding, delimiter)

            for row_num, row in enumerate(rows_iter, 1):
                processed = row_num

                validated, errors = validate_event(row, mapping)

                if errors:
                    rejected_rows.append(
                        {
                            "row_number": row_num,
                            "error": "; ".join(errors),
                            "fields": list(row.keys()),
                        }
                    )
                    if progress:
                        progress(
                            {
                                "status": "importing",
                                "processed": processed,
                                "rejected": len(rejected_rows),
                                "rate": processed / (processed + 1),
                            }
                        )
                    continue

                if validated.get("event_id"):
                    stmt = select(TelemetryEvent).where(
                        TelemetryEvent.event_id == validated["event_id"]
                    )
                    existing = db.execute(stmt).scalar_one_or_none()

                    if existing:
                        if duplicate_handling == "skip":
                            duplicate_skipped += 1
                            continue
                        elif duplicate_handling == "replace":
                            db.delete(existing)
                        elif duplicate_handling == "fail":
                            rejected_rows.append(
                                {
                                    "row_number": row_num,
                                    "error": f"Duplicate event_id: {validated['event_id']}",
                                }
                            )
                            continue

                pending_rows.append(validated)

                if len(pending_rows) >= chunk_size:
                    inserted_total += self._stage_chunk(db, pending_rows)
                    accepted_total += len(pending_rows)
                    pending_rows.clear()

                    if progress:
                        progress(
                            {
                                "status": "importing",
                                "processed": processed,
                                "inserted": inserted_total,
                                "rejected": len(rejected_rows),
                                "rate": processed / (processed + 1),
                            }
                        )

            if pending_rows:
                inserted_total += self._stage_chunk(db, pending_rows)
                accepted_total += len(pending_rows)
                pending_rows.clear()

            after_count = db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0
            persisted_delta = after_count - before_count
            if processed > 0 and accepted_total == 0:
                raise ImportError(f"Import produced zero valid telemetry rows from {processed} source rows. Check column mapping.")
            if accepted_total > 0 and inserted_total == 0:
                raise ImportError("Import produced accepted rows but no telemetry rows were staged")
            if inserted_total != accepted_total:
                raise ImportError(f"Inserted row count mismatch: accepted {accepted_total}, staged {inserted_total}")
            if persisted_delta < inserted_total:
                raise ImportError(f"Telemetry persistence verification failed: expected at least {inserted_total} new rows, found {persisted_delta}")

            self.job.processed_rows = processed
            self.job.valid_rows = accepted_total
            self.job.rejected_rows = len(rejected_rows)
            self.job.duplicate_skipped = duplicate_skipped
            self.job.inserted_rows = inserted_total
            self.job.status = "COMPLETED"
            self.job.completed_at = datetime.now(timezone.utc)
            self.job.rejected_row_examples = rejected_rows[:100]
            db.commit()
            result = {
                "processed_rows": processed,
                "valid_rows": accepted_total,
                "rejected_rows": len(rejected_rows),
                "duplicate_skipped": duplicate_skipped,
                "inserted_rows": inserted_total,
            }
        except ParseError as e:
            db.rollback()
            raise ImportError(f"Parse error during import: {str(e)}")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        self.cleanup()
        return result

    def _stage_chunk(self, db: Session, chunk: list[dict]) -> int:
        """Stage a chunk of validated events in the active transaction."""
        events = [TelemetryEvent(**row) for row in chunk]
        db.add_all(events)
        db.flush()
        return len(events)

    async def _insert_chunk(self, db: Session, chunk: list[dict]) -> int:
        """Insert a chunk of validated events."""
        try:
            events = [
                TelemetryEvent(**row) for row in chunk
            ]
            db.add_all(events)
            db.commit()
            return len(events)
        except IntegrityError as e:
            db.rollback()
            # Log but continue (some events may already exist)
            return 0
        except Exception as e:
            db.rollback()
            raise ImportError(f"Database insert error: {str(e)}")

    def cancel(self) -> None:
        """Cancel import and clean up."""
        db = SessionLocal()
        try:
            stmt = select(ImportJob).where(ImportJob.import_id == self.import_id)
            job = db.execute(stmt).scalar_one_or_none()
            if job:
                job.status = "CANCELLED"
                job.cancelled = True
                db.commit()
        finally:
            db.close()

        self.cleanup()

    def cleanup(self) -> None:
        """Remove temporary file."""
        path = self.get_temp_path()
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass  # Best effort


def export_rejected_rows_csv(import_id: str, include_values: bool = False) -> str:
    """Export rejected rows as CSV for download."""
    db = SessionLocal()
    try:
        stmt = select(ImportJob).where(ImportJob.import_id == import_id)
        job = db.execute(stmt).scalar_one_or_none()
        if not job or not job.rejected_row_examples:
            return ""

        # Build CSV
        output = io.StringIO()
        if include_values:
            fieldnames = ["row_number", "error", "fields"]
        else:
            fieldnames = ["row_number", "error"]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for reject in job.rejected_row_examples:
            if include_values:
                writer.writerow(
                    {
                        "row_number": reject.get("row_number"),
                        "error": reject.get("error"),
                        "fields": "|".join(reject.get("fields", [])),
                    }
                )
            else:
                writer.writerow(
                    {
                        "row_number": reject.get("row_number"),
                        "error": reject.get("error"),
                    }
                )

        return output.getvalue()
    finally:
        db.close()
