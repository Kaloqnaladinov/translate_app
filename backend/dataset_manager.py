"""SQLite-backed metadata management for recorded videos."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"
RAW_DIR = DATASET_DIR / "raw"
DATABASE_PATH = DATASET_DIR / "metadata.sqlite3"


def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection."""
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    """Create dataset folders and the recordings table if they do not exist."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (DATASET_DIR / "processed").mkdir(parents=True, exist_ok=True)
    (DATASET_DIR / "models").mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL,
                label TEXT,
                consent_given INTEGER NOT NULL CHECK (consent_given IN (0, 1)),
                created_at TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                content_type TEXT NOT NULL,
                file_size INTEGER NOT NULL CHECK (file_size > 0)
            )
            """
        )


def save_recording_metadata(recording: dict[str, Any]) -> None:
    """Save metadata for a video that has already been written to disk."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO recordings (
                id, participant_id, label, consent_given, created_at,
                original_filename, stored_filename, content_type, file_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recording["id"],
                recording["participant_id"],
                recording.get("label"),
                int(recording["consent_given"]),
                recording["created_at"],
                recording["original_filename"],
                recording["stored_filename"],
                recording["content_type"],
                recording["file_size"],
            ),
        )


def list_recordings() -> list[dict[str, Any]]:
    """Return metadata without exposing server filesystem paths."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, participant_id, label, consent_given, created_at,
                   original_filename, content_type, file_size
            FROM recordings
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def delete_recording(recording_id: str) -> bool:
    """Delete a recording and its metadata. Return False if it does not exist."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT stored_filename FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()

        if row is None:
            return False

        file_path = (RAW_DIR / row["stored_filename"]).resolve()
        if file_path.parent != RAW_DIR.resolve():
            raise ValueError("Unsafe recording path in database.")

        connection.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))

    file_path.unlink(missing_ok=True)
    return True
