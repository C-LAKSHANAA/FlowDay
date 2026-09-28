"""
persistence.py

Simple file-based persistence for FlowDay.

Storage format
--------------
backend/data/completion_log.json

A JSON file containing a single top-level array.  Each element is one
TaskCompletionLog entry serialised as a JSON object.  New entries are
appended by reading the existing array, appending, and writing back.

This is intentionally simple — no database, no migrations, no ORM.
A real production deployment would swap this module out for a proper
store (SQLite, Postgres, etc.) without touching any other code.

Thread safety
-------------
The read-modify-write is protected by a threading.Lock so concurrent
FastAPI requests don't corrupt the file.  This is sufficient for a
single-process dev server.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models import TaskCompletionLog

# ---------------------------------------------------------------------------
# File location
# ---------------------------------------------------------------------------

DATA_DIR  = Path(__file__).parent.parent / "data"
LOG_FILE  = DATA_DIR / "completion_log.json"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_file() -> None:
    """Create the data directory and an empty log file if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("[]", encoding="utf-8")


def _read_all() -> list[dict]:
    _ensure_file()
    raw = LOG_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _write_all(entries: list[dict]) -> None:
    LOG_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_completion(entry: TaskCompletionLog) -> TaskCompletionLog:
    """
    Append a TaskCompletionLog entry to the log file.

    Sets ``completed_at`` to the current UTC time before writing if it
    is not already set.  Returns the entry as written (with timestamp).
    """
    if not entry.completed_at:
        entry = entry.model_copy(update={
            "completed_at": datetime.now(timezone.utc).isoformat()
        })

    with _lock:
        entries = _read_all()
        entries.append(entry.model_dump())
        _write_all(entries)

    return entry


def read_all_completions() -> list[TaskCompletionLog]:
    """Return all log entries as a list of TaskCompletionLog objects."""
    with _lock:
        raw = _read_all()
    return [TaskCompletionLog(**row) for row in raw]


def read_completions_for_task(task_id: str) -> list[TaskCompletionLog]:
    """Return all log entries for a specific task id."""
    return [e for e in read_all_completions() if e.task_id == task_id]
