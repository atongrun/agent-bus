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
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
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
        # Idempotent migration: add last_error column if not present
        # (safe to re-run init_db() against an existing database).
        try:
            conn.execute("ALTER TABLE events ADD COLUMN last_error TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists — safe on re-init


def insert_event(
    from_agent: str, to_agent: str, event_type: str, payload_json: str
) -> dict:
    """Insert a new event and return it as a dict."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO events (from_agent, to_agent, type, payload_json)
               VALUES (?, ?, ?, ?)""",
            (from_agent, to_agent, event_type, payload_json),
        )
        event_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row)


def get_event(event_id: int) -> dict | None:
    """Get a single event by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def get_pending_events(agent: str) -> list[dict]:
    """Get all events for an agent that are not yet acked (pending or delivered)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE to_agent = ? AND status IN ('pending', 'delivered')
               ORDER BY created_at ASC""",
            (agent,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_failed_events(agent: str) -> list[dict]:
    """Get terminally failed events for an agent."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE to_agent = ? AND status = 'failed'
               ORDER BY created_at ASC""",
            (agent,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_operator_events(
    *,
    status: str | None = None,
    query: str | None = None,
    before_id: int | None = None,
    limit: int = 100,
) -> tuple[list[dict], bool]:
    """Read a newest-first page across all identities without changing state."""
    clauses: list[str] = []
    params: list[object] = []

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        searchable_columns = (
            "CAST(id AS TEXT)",
            "from_agent",
            "to_agent",
            "type",
            "payload_json",
            "COALESCE(last_error, '')",
        )
        clauses.append(
            "("
            + " OR ".join(
                f"{column} LIKE ? ESCAPE '\\'" for column in searchable_columns
            )
            + ")"
        )
        params.extend([pattern] * len(searchable_columns))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM events
                {where}
                ORDER BY id DESC
                LIMIT ?""",
            params,
        ).fetchall()

    has_more = len(rows) > limit
    return [dict(row) for row in rows[:limit]], has_more


def get_event_status_counts() -> dict[str, int]:
    """Return global event counts for every durable status."""
    counts = {"pending": 0, "delivered": 0, "acked": 0, "failed": 0}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM events GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[row["status"]] = row["count"]
    return counts


def get_max_event_id(agent: str) -> int:
    """Get the maximum event ID for a given agent (any status)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM events WHERE to_agent = ?", (agent,)
        ).fetchone()
        return row[0]


def mark_delivered(event_id: int) -> dict | None:
    """Atomically mark a pending event delivered and return its current row."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE events
               SET status = 'delivered',
                   delivered_at = COALESCE(delivered_at, datetime('now'))
               WHERE id = ? AND status = 'pending'""",
            (event_id,),
        )
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def ack_event(
    event_id: int,
    expected_retry_count: int | None = None,
) -> tuple[str, dict | None]:
    """Atomically ACK an event, returning an outcome and current row."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return "not_found", None
        if row["status"] == "acked":
            return "already_acked", dict(row)
        if row["status"] == "failed":
            return "conflict", dict(row)
        if (
            expected_retry_count is not None
            and row["retry_count"] != expected_retry_count
        ):
            return "stale", dict(row)

        conn.execute(
            """UPDATE events
               SET status = 'acked',
                   acked_at = datetime('now')
               WHERE id = ? AND status IN ('pending', 'delivered')""",
            (event_id,),
        )
        updated = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return "acked", dict(updated)


def record_failure(
    event_id: int,
    last_error: str | None,
    max_attempts: int,
    expected_retry_count: int | None,
) -> tuple[str, dict | None]:
    """Atomically record one failed attempt and apply the terminal threshold."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return "not_found", None
        if row["status"] == "failed":
            return "already_failed", dict(row)
        if row["status"] == "acked":
            return "conflict", dict(row)
        if (
            expected_retry_count is not None
            and row["retry_count"] != expected_retry_count
        ):
            return "stale", dict(row)

        next_count = row["retry_count"] + 1
        # Compatibility: pre-P0 listeners only called /fail after their local
        # threshold was exhausted. With no observed count, preserve that
        # terminal transition. New listeners always send the precondition and
        # use the durable server-side threshold.
        next_status = (
            "failed"
            if expected_retry_count is None or next_count >= max_attempts
            else "pending"
        )
        conn.execute(
            """UPDATE events
               SET status = ?,
                   retry_count = ?,
                   last_error = ?,
                   delivered_at = CASE WHEN ? = 'pending' THEN NULL ELSE delivered_at END
               WHERE id = ? AND status IN ('pending', 'delivered')""",
            (next_status, next_count, last_error, next_status, event_id),
        )
        updated = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return "failed" if next_status == "failed" else "recorded", dict(updated)


def requeue_event(event_id: int) -> tuple[str, dict | None]:
    """Atomically requeue a failed event while preserving failure evidence."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return "not_found", None
        if row["status"] == "pending":
            return "already_pending", dict(row)
        if row["status"] != "failed":
            return "conflict", dict(row)

        conn.execute(
            """UPDATE events
               SET status = 'pending', delivered_at = NULL, acked_at = NULL
               WHERE id = ? AND status = 'failed'""",
            (event_id,),
        )
        updated = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return "requeued", dict(updated)


def check_new_events(agent: str, after_id: int) -> list[dict]:
    """Get new events for an agent with id > after_id (for polling)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE to_agent = ? AND id > ?
                 AND status IN ('pending', 'delivered')
               ORDER BY created_at ASC""",
            (agent, after_id),
        ).fetchall()
        return [dict(r) for r in rows]
