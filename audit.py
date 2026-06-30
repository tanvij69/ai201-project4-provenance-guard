import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "audit_log.db")


def init_db():
    """Creates the audit log table if it doesn't already exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL,
            creator_id TEXT,
            timestamp TEXT NOT NULL,
            text_snippet TEXT,
            attribution TEXT,
            confidence REAL,
            llm_score REAL,
            stylometric_score REAL,
            status TEXT,
            appeal_reason TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_entry(entry: dict):
    """
    Writes a structured entry to the audit log.
    Expects a dict with keys matching the table columns (missing keys default to None).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_log
        (content_id, creator_id, timestamp, text_snippet, attribution,
         confidence, llm_score, stylometric_score, status, appeal_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry.get("content_id"),
        entry.get("creator_id"),
        entry.get("timestamp"),
        entry.get("text_snippet"),
        entry.get("attribution"),
        entry.get("confidence"),
        entry.get("llm_score"),
        entry.get("stylometric_score"),
        entry.get("status"),
        entry.get("appeal_reason"),
    ))
    conn.commit()
    conn.close()


def get_log(limit: int = 20):
    """Returns the most recent audit log entries as a list of dicts."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_submission(content_id: str):
    """Looks up the most recent log entry for a given content_id."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM audit_log WHERE content_id = ? ORDER BY id DESC LIMIT 1",
        (content_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_status(content_id: str, new_status: str, appeal_reason: str = None):
    """Updates the status (and optionally appeal reason) for a submission."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_log
        SET status = ?, appeal_reason = ?
        WHERE content_id = ?
    """, (new_status, appeal_reason, content_id))
    conn.commit()
    conn.close()