"""SQLite database layer for Agent Bus."""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("AGENT_BUS_DB_PATH", "data/agent-bus.db")


def _ensure_dir():
    """Ensure the database directory exists."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection with WAL mode and row factory."""
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'delivered', 'acked', 'failed')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                delivered_at TEXT,
                acked_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Index for efficient query of un-acked events by agent
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_to_agent_status
            ON events(to_agent, status)
        """)
        # Index for ordering by creation time
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_created_at
            ON events(created_at)
        """)


def insert_event(from_agent: str, to_agent: str, event_type: str,
                 payload_json: str) -> dict:
    """Insert a new event and return it as a dict."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO events (from_agent, to_agent, type, payload_json)
               VALUES (?, ?, ?, ?)""",
            (from_agent, to_agent, event_type, payload_json)
        )
        event_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return dict(row)


def get_event(event_id: int) -> dict | None:
    """Get a single event by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pending_events(agent: str) -> list[dict]:
    """Get all events for an agent that are not yet acked (pending or delivered)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE to_agent = ? AND status IN ('pending', 'delivered')
               ORDER BY created_at ASC""",
            (agent,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_max_event_id(agent: str) -> int:
    """Get the maximum event ID for a given agent (any status)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM events WHERE to_agent = ?",
            (agent,)
        ).fetchone()
        return row[0]


def mark_delivered(event_id: int) -> bool:
    """Mark an event as delivered. Returns True if updated."""
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE events
               SET status = 'delivered',
                   delivered_at = COALESCE(delivered_at, datetime('now'))
               WHERE id = ? AND status = 'pending'""",
            (event_id,)
        )
        return cursor.rowcount > 0


def ack_event(event_id: int) -> bool:
    """Mark an event as acknowledged. Returns True if updated."""
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE events
               SET status = 'acked',
                   acked_at = datetime('now')
               WHERE id = ? AND status IN ('pending', 'delivered')""",
            (event_id,)
        )
        return cursor.rowcount > 0


def check_new_events(agent: str, after_id: int) -> list[dict]:
    """Get new events for an agent with id > after_id (for polling)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE to_agent = ? AND id > ?
               ORDER BY created_at ASC""",
            (agent, after_id)
        ).fetchall()
        return [dict(r) for r in rows]
