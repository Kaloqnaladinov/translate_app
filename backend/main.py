
"""
FastAPI backend for Translate App.

Responsibilities:
- receive video uploads;
- delegate video storage to recorder.py;
- delegate metadata operations to dataset_manager.py;
- extract MediaPipe landmarks;
- predict gestures using the trained ML model;
- preserve original recordings when metadata is deleted.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import dataset_manager

from .dataset_manager import (
    ConflictError,
    DatabaseError,
    DatasetError,
    NotFoundError,
    ValidationError,
    RAW_DIR,
    DATASET_DIR,
)

from .extraction import (
    ExtractionError,
    extract_video_landmarks,
)

from ml.predict import (
    PredictionError,
    predict_recording,
)

from .recorder import (
    EmptyUploadError,
    RecorderError,
    UploadTooLargeError,
    UnsupportedVideoTypeError,
    save_video_upload,
)


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

MAX_LABEL_LENGTH = 80

SERVICE_NAME = "translate-app-backend"

API_VERSION = "0.1.0"

# Local development configuration.
# Restrict this list before production deployment.
ALLOWED_ORIGINS = ["*"]

# Temporary prediction files are kept outside the training dataset.
PREDICTIONS_TMP_DIR = DATASET_DIR / "predictions_tmp"


# ---------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize required storage before the server starts."""

    dataset_manager.init_db()

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PREDICTIONS_TMP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    yield


app = FastAPI(
    title="Translate App API",
    version=API_VERSION,
    description=(
        "Backend foundation for the Bulgarian Sign Language "
        "Translate App."
    ),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------

def _to_http_error(exc: DatasetError) -> HTTPException:
    """Convert internal dataset exceptions into HTTP responses."""

    if isinstance(exc, ValidationError):
        return HTTPException(
            status_code=422,
            detail=str(exc),
        )

    if isinstance(exc, NotFoundError):
        return HTTPException(
            status_code=404,
            detail=str(exc),
        )

    if isinstance(exc, ConflictError):
        return HTTPException(
            status_code=409,
            detail=str(exc),
        )

    if isinstance(exc, DatabaseError):
        return HTTPException(
            status_code=500,
            detail="Internal database error.",
        )

    return HTTPException(
        status_code=500,
        detail="Internal server error.",
    )


# ---------------------------------------------------------------------
# Response serialization
# ---------------------------------------------------------------------

_INTERNAL_FIELDS = {
    "stored_filename",
    "filename",
    "file_path",
}


def _serialize_record(record: dict) -> dict:
    """
    Prepare a recording for the frontend.

    Internal filesystem names and paths are never exposed.
    """

    result = {
        key: value
        for key, value in record.items()
        if key not in _INTERNAL_FIELDS
    }

    result["file_url"] = (
        f"/api/recordings/{record['id']}/file"
    )

    return result


# ---------------------------------------------------------------------
# Label validation
# ---------------------------------------------------------------------

def _validate_label(label: Optional[str]) -> Optional[str]:
    """Validate the label received from the frontend."""

    if label is None:
        return None

    if not isinstance(label, str):
        raise HTTPException(
            status_code=422,
            detail="label must be a string.",
        )

    label = label.strip()

    if not label:
        return None

    if len(label) > MAX_LABEL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=(
                f"label must contain at most "
                f"{MAX_LABEL_LENGTH} characters."
            ),
        )

    return label


# ---------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------

class LabelUpdate(BaseModel):
    """Request body for PATCH /api/recordings/{recording_id}."""

    label: Optional[str] = None


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Return backend health status."""

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": API_VERSION,
    }


# ---------------------------------------------------------------------
# List recordings
# ---------------------------------------------------------------------

@app.get("/api/recordings")
def list_recordings() -> dict:
    """Return all recordings."""

    try:
        records = dataset_manager.get_all_recordings()

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    items = [
        _serialize_record(record)
        for record in records
    ]

    return {
        "items": items,
        "count": len(items),
    }


# ---------------------------------------------------------------------
# Get one recording
# ---------------------------------------------------------------------

@app.get("/api/recordings/{recording_id}")
def get_recording(recording_id: str) -> dict:
    """Return one recording by ID."""

    try:
        record = dataset_manager.get_recording_by_id(
            recording_id
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    return _serialize_record(record)


# ---------------------------------------------------------------------
# Download / stream original video
# ---------------------------------------------------------------------

@app.get("/api/recordings/{recording_id}/file")
def get_recording_file(recording_id: str):
    """Return the original video file."""

    try:
        record = dataset_manager.get_recording_by_id(
            recording_id
        )

        video_path = dataset_manager.get_video_path(
            record
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    return FileResponse(
        path=video_path,
        media_type=record["content_type"],
        filename=record["original_filename"],
    )


# ---------------------------------------------------------------------
# Extract landmarks from a recording
# ---------------------------------------------------------------------

@app.post("/api/recordings/{recording_id}/extract")
def extract_recording_landmarks(recording_id: str) -> dict:
    """Extract MediaPipe landmarks from an existing recording."""

    try:
        record = dataset_manager.get_recording_by_id(
            recording_id
        )

        video_path = dataset_manager.get_video_path(
            record
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    label = record.get("label")

    if (
        not label
        or label.strip().lower() == "камерен запис"
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Set a valid sign label before "
                "extracting landmarks."
            ),
        )

    try:
        result = extract_video_landmarks(
            video_path=video_path,
            recording_id=record["id"],
            label=label,
            participant_id=record["participant_id"],
        )

    except ExtractionError as exc:
        message = str(exc)

        if "already exists" in message:
            raise HTTPException(
                status_code=409,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=422,
            detail=message,
        ) from exc

    return {
        "status": "completed",
        "message": "Landmarks extracted successfully.",
        "result": result,
    }


# ---------------------------------------------------------------------
# Predict gesture from an uploaded recording
# ---------------------------------------------------------------------

@app.post("/api/recordings/{recording_id}/predict")
def predict_recording_endpoint(recording_id: str) -> dict:
    """
    Extract temporary landmarks and predict one recorded gesture.

    Temporary landmarks are stored outside dataset/processed.
    They are deleted after prediction.
    The training dataset is not modified.
    """

    try:
        record = dataset_manager.get_recording_by_id(
            recording_id
        )

        video_path = dataset_manager.get_video_path(
            record
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    temporary_landmarks = (
        PREDICTIONS_TMP_DIR
        / f"prediction__{uuid4().hex}.landmarks.jsonl"
    )

    try:
        # 1. Extract landmarks from the uploaded video.
        extraction_result = extract_video_landmarks(
            video_path=video_path,
            recording_id=record["id"],
            label="prediction",
            participant_id=record["participant_id"],
            output_path=temporary_landmarks,
        )

        # 2. Run the trained AI model.
        prediction = predict_recording(
            landmarks_path=temporary_landmarks,
            top_k=5,
        )

        return {
            "status": "success",
            "recording_id": recording_id,
            "extraction": {
                "frames": extraction_result["processed_frames"],
                "output": "temporary",
            },
            "prediction": prediction,
        }

    except ExtractionError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract landmarks from the video."
            ),
        ) from exc

    except PredictionError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI prediction is currently unavailable."
            ),
        ) from exc

    finally:
        # Never leave temporary prediction data in the dataset.
        temporary_landmarks.unlink(missing_ok=True)


# ---------------------------------------------------------------------
# Create recording
# ---------------------------------------------------------------------

@app.post(
    "/api/recordings",
    status_code=201,
)
async def create_recording(
    file: UploadFile = File(...),
    participant_id: str = Form(...),
    consent: bool = Form(...),
    label: Optional[str] = Form(None),
) -> dict:
    """
    Receive a video and save its metadata.

    Expected multipart/form-data fields:
        file
        participant_id
        consent
        label (optional)
    """

    # 1. Validate consent before accepting the upload.
    if not consent:
        raise HTTPException(
            status_code=422,
            detail="Consent is required to store a recording.",
        )

    # 2. Validate participant ID.
    try:
        participant_id = (
            dataset_manager._validate_participant_id(
                participant_id
            )
        )

    except ValidationError as exc:
        raise _to_http_error(exc) from exc

    # 3. Validate label.
    label = _validate_label(label)

    # 4. Save the actual video.
    try:
        (
            stored_filename,
            file_size,
            content_type,
        ) = await save_video_upload(file)

    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc

    except EmptyUploadError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except UnsupportedVideoTypeError as exc:
        raise HTTPException(
            status_code=415,
            detail=str(exc),
        ) from exc

    except RecorderError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not store the uploaded video.",
        ) from exc

    # 5. Generate application metadata.
    recording_id = uuid4().hex

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    # 6. Save metadata in SQLite.
    try:
        record = dataset_manager.add_recording(
            recording_id=recording_id,
            participant_id=participant_id,
            consent_given=True,
            stored_filename=stored_filename,
            content_type=content_type,
            file_size=file_size,
            original_filename=(
                file.filename or stored_filename
            ),
            created_at=created_at,
            label=label,
        )

    except DatasetError as exc:
        # The database rejected the metadata.
        # Remove only this failed upload.
        video_path = RAW_DIR / stored_filename
        video_path.unlink(missing_ok=True)

        raise _to_http_error(exc) from exc

    except Exception as exc:
        video_path = RAW_DIR / stored_filename
        video_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail="Could not save recording metadata.",
        ) from exc

    return _serialize_record(record)


# ---------------------------------------------------------------------
# Update recording label
# ---------------------------------------------------------------------

@app.patch("/api/recordings/{recording_id}")
def update_recording_label(
    recording_id: str,
    body: LabelUpdate,
) -> dict:
    """Update a recording's label."""

    label = _validate_label(body.label)

    try:
        record = dataset_manager.update_label(
            recording_id,
            label,
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    return _serialize_record(record)


# ---------------------------------------------------------------------
# Delete recording metadata
# ---------------------------------------------------------------------

@app.delete("/api/recordings/{recording_id}")
def delete_recording(recording_id: str) -> dict:
    """
    Delete recording metadata.

    The original video remains in dataset/raw/.
    """

    try:
        dataset_manager.delete_recording_by_id(
            recording_id
        )

    except DatasetError as exc:
        raise _to_http_error(exc) from exc

    return {
        "deleted": recording_id,
        "video_preserved": True,
    }
