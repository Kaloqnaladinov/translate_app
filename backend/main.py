
"""Main FastAPI application for the Translate App backend."""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from backend.dataset_manager import (
    RAW_DIR,
    ConflictError,
    DatabaseError,
    DatasetError,
    NotFoundError,
    ValidationError,
    delete_recording,
    initialize_database,
    list_recordings,
    save_recording_metadata,
)
from backend.recorder import save_video_upload


logger = logging.getLogger(__name__)

PARTICIPANT_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{3,40}$"
)

RECORDING_FILENAME_PATTERN = re.compile(
    r"^[a-f0-9]{32}\.(?:webm|mp4|mov)$"
)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize the database when the application starts."""
    initialize_database()
    yield


app = FastAPI(
    title="Translate App API",
    description=(
        "Backend API for consent-based video dataset collection."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        (
            "http://localhost:5500,"
            "http://127.0.0.1:5500,"
            "http://localhost:8000,"
            "http://127.0.0.1:8000"
        ),
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.exception_handler(ValidationError)
async def handle_validation_error(
    _: Request,
    exc: ValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


@app.exception_handler(NotFoundError)
async def handle_not_found_error(
    _: Request,
    exc: NotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)},
    )


@app.exception_handler(ConflictError)
async def handle_conflict_error(
    _: Request,
    exc: ConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
    )


@app.exception_handler(DatabaseError)
async def handle_database_error(
    _: Request,
    exc: DatabaseError,
) -> JSONResponse:
    logger.error("Database operation failed: %s", exc)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "A database operation failed."
        },
    )


@app.exception_handler(DatasetError)
async def handle_dataset_error(
    _: Request,
    exc: DatasetError,
) -> JSONResponse:
    logger.error("Dataset operation failed: %s", exc)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "A dataset operation failed."
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _public_recording(recording: dict) -> dict:
    """Return only metadata intended for API consumers."""

    allowed_fields = {
        "id",
        "participant_id",
        "label",
        "consent_given",
        "created_at",
        "content_type",
        "file_size",
    }

    return {
        key: value
        for key, value in recording.items()
        if key in allowed_fields
    }


def _cleanup_uploaded_file(stored_filename: str) -> None:
    """Remove an uploaded file after metadata persistence fails."""

    if not RECORDING_FILENAME_PATTERN.fullmatch(stored_filename):
        logger.error(
            "Refusing to clean up an unexpected filename."
        )
        return

    try:
        (RAW_DIR / stored_filename).unlink(missing_ok=True)

    except OSError:
        logger.exception(
            "Could not remove an uncommitted uploaded video."
        )


def _normalize_original_filename(filename: str | None) -> str:
    """Remove path components from a client-provided filename."""

    if not filename:
        return "recording"

    normalized = filename.replace("\\", "/").split("/")[-1]
    normalized = normalized.replace("\x00", "").strip()

    return normalized[:255] or "recording"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "translate-app-api",
    }


# ---------------------------------------------------------------------------
# Upload recording
# ---------------------------------------------------------------------------

@app.post("/api/recordings", status_code=201)
async def upload_recording(
    file: UploadFile = File(...),
    participant_id: str = Form(...),
    consent_given: bool = Form(...),
    label: str | None = Form(default=None),
) -> dict:

    # Validate participant identifier before accepting the video.
    participant_id = participant_id.strip()

    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "participant_id must contain 3-40 characters: "
                "letters, numbers, underscores or hyphens."
            ),
        )

    # Consent is mandatory.
    if not consent_given:
        raise HTTPException(
            status_code=403,
            detail="Recording cannot be stored without consent.",
        )

    # Normalize optional label.
    cleaned_label = label.strip() if label else None
    cleaned_label = cleaned_label or None

    if cleaned_label and len(cleaned_label) > 80:
        raise HTTPException(
            status_code=422,
            detail="label must be 80 characters or fewer.",
        )

    # Store the uploaded video.
    try:
        (
            stored_filename,
            file_size,
            content_type,
        ) = await save_video_upload(file)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # Build metadata for the database.
    recording = {
        "id": uuid4().hex,
        "participant_id": participant_id,
        "label": cleaned_label,
        "consent_given": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_filename": _normalize_original_filename(
            file.filename
        ),
        "stored_filename": stored_filename,
        "content_type": content_type,
        "file_size": file_size,
    }

    # Save metadata only after the video has been stored successfully.
    try:
        save_recording_metadata(recording)

    except DatasetError:
        _cleanup_uploaded_file(stored_filename)
        raise

    except Exception as exc:
        _cleanup_uploaded_file(stored_filename)

        logger.exception(
            "Unexpected error while saving recording metadata."
        )

        raise HTTPException(
            status_code=500,
            detail="Could not save recording metadata.",
        ) from exc

    return {
        "message": "Recording saved successfully.",
        "recording": _public_recording(recording),
    }


# ---------------------------------------------------------------------------
# List recordings
# ---------------------------------------------------------------------------

@app.get("/api/recordings")
async def get_recordings() -> dict:

    recordings = list_recordings()

    return {
        "recordings": [
            _public_recording(recording)
            for recording in recordings
        ]
    }


# ---------------------------------------------------------------------------
# Delete recording
# ---------------------------------------------------------------------------

@app.delete("/api/recordings/{recording_id}")
async def remove_recording(
    recording_id: str,
) -> dict[str, str]:

    deleted = delete_recording(recording_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Recording not found.",
        )

    return {
        "message": "Recording deleted successfully."
    }
