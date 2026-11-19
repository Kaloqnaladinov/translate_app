
"""SQLite metadata management for the Translate App recording dataset.

This module stores recording metadata and exposes the functions currently used
by backend/main.py. Video uploads are written by backend/recorder.py.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"
RAW_DIR = DATASET_DIR / "raw"
DATABASE_PATH = DATASET_DIR / "metadata.sqlite3"

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

ALLOWED_VIDEO_TYPES = {
    "video/webm": ".webm",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}

_PARTICIPANT_RE = re.compile(r"^[A-Za-z0-9_-]{3,40}$")
_RECORDING_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_STORED_FILENAME_RE = re.compile(
    r"^[a-f0-9]{32}\.(?:webm|mp4|mov)$"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DatasetError(Exception):
    """Base class for dataset metadata errors."""


class ValidationError(DatasetError):
    """Input metadata is invalid."""


class NotFoundError(DatasetError):
    """The requested recording does not exist."""


class ConflictError(DatasetError):
    """A unique metadata value already exists."""


class DatabaseError(DatasetError):
    """SQLite operation failed."""


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""

    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(
            str(DATABASE_PATH),
            timeout=5
        )
    except sqlite3.Error as exc:
        raise DatabaseError(
            "Could not open the recordings database."
        ) from exc

    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

        yield connection

        connection.commit()

    except sqlite3.IntegrityError as exc:
        connection.rollback()

        message = str(exc).lower()

        if "unique" in message or "primary key" in message:
            raise ConflictError(
                "A recording with this identifier already exists."
            ) from exc

        raise DatabaseError(
            "A database integrity constraint was violated."
        ) from exc

    except sqlite3.Error as exc:
        connection.rollback()

        raise DatabaseError(
            "A database operation failed."
        ) from exc

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------

def _validate_recording_metadata(
    recording: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize metadata received from the API layer."""

    if not isinstance(recording, dict):
        raise ValidationError("recording must be a dictionary.")

    required = (
        "id",
        "participant_id",
        "consent_given",
        "created_at",
        "original_filename",
        "stored_filename",
        "content_type",
        "file_size",
    )

    missing = [
        key for key in required
        if key not in recording
    ]

    if missing:
        raise ValidationError(
            f"Missing recording fields: {', '.join(missing)}."
        )

    # Recording ID
    recording_id = recording["id"]

    if (
        not isinstance(recording_id, str)
        or not _RECORDING_ID_RE.fullmatch(recording_id)
    ):
        raise ValidationError(
            "id must be a 32-character lowercase hexadecimal UUID."
        )

    # Participant ID
    participant_id = recording["participant_id"]

    if not isinstance(participant_id, str):
        raise ValidationError(
            "participant_id must be a string."
        )

    participant_id = participant_id.strip()

    if not _PARTICIPANT_RE.fullmatch(participant_id):
        raise ValidationError(
            "participant_id must be 3-40 letters, numbers, '_' or '-'."
        )

    # Consent
    if recording["consent_given"] is not True:
        raise ValidationError(
            "Consent is required to store a recording."
        )

    # Timestamp
    created_at = recording["created_at"]

    if (
        not isinstance(created_at, str)
        or not created_at.strip()
        or len(created_at) > 64
    ):
        raise ValidationError(
            "created_at must be a non-empty timestamp string."
        )

    # Original filename
    original_filename = recording["original_filename"]

    if (
        not isinstance(original_filename, str)
        or not original_filename.strip()
    ):
        raise ValidationError(
            "original_filename must be a non-empty string."
        )

    # Normalize Windows and POSIX path separators.
    original_filename = (
        original_filename
        .replace("\\", "/")
        .split("/")[-1]
    )

    original_filename = (
        original_filename
        .replace("\x00", "")
        .strip()
    )

    if not original_filename or len(original_filename) > 255:
        raise ValidationError(
            "original_filename must contain 1-255 characters."
        )

    # Stored filename must be generated by the application.
    stored_filename = recording["stored_filename"]

    if (
        not isinstance(stored_filename, str)
        or not _STORED_FILENAME_RE.fullmatch(stored_filename)
    ):
        raise ValidationError(
            "stored_filename is not a valid generated video filename."
        )

    # Content type
    content_type = recording["content_type"]

    if not isinstance(content_type, str):
        raise ValidationError(
            "content_type must be a string."
        )

    expected_extension = ALLOWED_VIDEO_TYPES.get(content_type)

    if (
        expected_extension is None
        or not stored_filename.endswith(expected_extension)
    ):
        raise ValidationError(
            "content_type does not match the stored video extension."
        )

    # File size
    file_size = recording["file_size"]

    if isinstance(file_size, bool) or not isinstance(file_size, int):
        raise ValidationError(
            "file_size must be an integer."
        )

    if not 1 <= file_size <= MAX_UPLOAD_BYTES:
        raise ValidationError(
            "file_size must be between 1 byte and 100 MB."
        )

    # Label
    label = recording.get("label")

    if label is not None:
        if not isinstance(label, str):
            raise ValidationError(
                "label must be a string or null."
            )

        label = label.strip() or None

        if label is not None and len(label) > 80:
            raise ValidationError(
                "label must be 80 characters or fewer."
            )

    return {
        "id": recording_id,
        "participant_id": participant_id,
        "label": label,
        "consent_given": 1,
        "created_at": created_at.strip(),
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "content_type": content_type,
        "file_size": file_size,
    }


# ---------------------------------------------------------------------------
# Filesystem path security
# ---------------------------------------------------------------------------

def _get_safe_video_path(stored_filename: str) -> Path:
    """Resolve a generated filename and ensure it stays inside dataset/raw."""

    if (
        not isinstance(stored_filename, str)
        or not _STORED_FILENAME_RE.fullmatch(stored_filename)
    ):
        raise ValidationError(
            "Invalid stored video filename."
        )

    raw_root = RAW_DIR.resolve()
    candidate = (RAW_DIR / stored_filename).resolve()

    try:
        candidate.relative_to(raw_root)

    except ValueError as exc:
        raise ValidationError(
            "Video path escapes the raw dataset directory."
        ) from exc

    if candidate.parent != raw_root:
        raise ValidationError(
            "Video must be stored directly inside dataset/raw."
        )

    return candidate


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def initialize_database() -> None:
    """Create dataset folders and the recordings table if missing."""

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    (DATASET_DIR / "processed").mkdir(
        parents=True,
        exist_ok=True
    )

    (DATASET_DIR / "models").mkdir(
        parents=True,
        exist_ok=True
    )

    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,

                participant_id TEXT NOT NULL,

                label TEXT,

                consent_given INTEGER NOT NULL
                    CHECK (consent_given IN (0, 1)),

                created_at TEXT NOT NULL,

                original_filename TEXT NOT NULL,

                stored_filename TEXT NOT NULL UNIQUE,

                content_type TEXT NOT NULL
                    CHECK (
                        content_type IN (
                            'video/webm',
                            'video/mp4',
                            'video/quicktime'
                        )
                    ),

                file_size INTEGER NOT NULL
                    CHECK (
                        file_size > 0
                        AND file_size <= 104857600
                    )
            )
            """
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_recording_metadata(
    recording: dict[str, Any]
) -> None:
    """Save metadata for a video already written by backend/recorder.py."""

    data = _validate_recording_metadata(recording)

    initialize_database()

    video_path = _get_safe_video_path(
        data["stored_filename"]
    )

    # The file must exist inside dataset/raw.
    if not video_path.is_file():
        raise ValidationError(
            "The uploaded video file does not exist in dataset/raw."
        )

    # Verify the actual file size against the metadata.
    if video_path.stat().st_size != data["file_size"]:
        raise ValidationError(
            "The actual video size does not match file_size metadata."
        )

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO recordings (
                id,
                participant_id,
                label,
                consent_given,
                created_at,
                original_filename,
                stored_filename,
                content_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["participant_id"],
                data["label"],
                data["consent_given"],
                data["created_at"],
                data["original_filename"],
                data["stored_filename"],
                data["content_type"],
                data["file_size"],
            ),
        )


def list_recordings() -> list[dict[str, Any]]:
    """Return metadata without exposing internal storage filenames."""

    initialize_database()

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                participant_id,
                label,
                consent_given,
                created_at,
                original_filename,
                content_type,
                file_size
            FROM recordings
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def delete_recording(recording_id: str) -> bool:
    """Delete a recording row and its safely-resolved video file."""

    if (
        not isinstance(recording_id, str)
        or not _RECORDING_ID_RE.fullmatch(recording_id)
    ):
        raise ValidationError(
            "recording_id must be a 32-character lowercase hexadecimal UUID."
        )

    initialize_database()

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT stored_filename
            FROM recordings
            WHERE id = ?
            """,
            (recording_id,),
        ).fetchone()

        if row is None:
            return False

        video_path = _get_safe_video_path(
            row["stored_filename"]
        )

        connection.execute(
            "DELETE FROM recordings WHERE id = ?",
            (recording_id,),
        )

    # Delete the file only after the database transaction commits.
    #
    # SQLite and filesystem operations are not atomic. If file deletion
    # fails here, the database row is already gone and an orphan file
    # may need manual cleanup.

    video_path.unlink(missing_ok=True)

    return True
