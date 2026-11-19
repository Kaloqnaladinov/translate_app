"""
FastAPI backend for the Translate App — HTTP layer only.

Responsibilities:
- accept video uploads (upload reading delegated to ``backend/recorder.py``),
- persist metadata (delegated to ``backend/dataset_manager.py``),
- map ``DatasetError`` subclasses to HTTP status codes,
- never expose internal file paths or raw database error text.

Milestone 1 — no sign recognition, no landmark extraction.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Package-relative imports when launched as `uvicorn backend.main:app`
# from the project root; flat imports when launched from `backend/`.
try:
    from . import dataset_manager
    from .dataset_manager import (
        ConflictError,
        DatabaseError,
        DatasetError,
        NotFoundError,
        PROJECT_ROOT,
        RAW_DIR,
        ValidationError,
    )
    from .recorder import (
        UploadTooLargeError,
        infer_content_type,
        read_upload,
    )
except ImportError:  # pragma: no cover
    import dataset_manager  # type: ignore
    from dataset_manager import (  # type: ignore
        ConflictError,
        DatabaseError,
        DatasetError,
        NotFoundError,
        PROJECT_ROOT,
        RAW_DIR,
        ValidationError,
    )
    from recorder import (  # type: ignore
        UploadTooLargeError,
        infer_content_type,
        read_upload,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# API-level label cap. The database accepts up to 128; the HTTP API is
# stricter on purpose so we never hit the DB limit from the browser.
MAX_LABEL_LENGTH = 80

# Extension -> MIME, used to set FileResponse media_type and to recover
# the content type when browsers send application/octet-stream.
EXT_TO_MIME = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}
MIME_TO_EXT = {mime: ext for ext, mime in EXT_TO_MIME.items()}

# Fields that stay internal — never returned by any endpoint.
_INTERNAL_FIELDS = {"file_path", "filename"}


# ---------------------------------------------------------------------------
# Lifespan + app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema and raw storage directory exist at startup."""
    dataset_manager.init_db()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Translate App API",
    version="0.1.0",
    description="Foundation backend for Bulgarian Sign Language translate app.",
    lifespan=lifespan,
)

# Local development only. Tighten allow_origins before any deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_http_error(exc: DatasetError) -> HTTPException:
    """Map a ``DatasetError`` to an ``HTTPException``.

    - ValidationError -> 422
    - NotFoundError   -> 404
    - ConflictError   -> 409
    - DatabaseError   -> 500 with a generic message (no internals leaked)
    - anything else   -> 500 with a generic message
    """
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, DatabaseError):
        return HTTPException(status_code=500, detail="Internal database error.")
    return HTTPException(status_code=500, detail="Internal server error.")


def _sanitize(record: dict) -> dict:
    """Strip internal fields from a record before returning it as JSON."""
    return {k: v for k, v in record.items() if k not in _INTERNAL_FIELDS}


def _safe_extension(
    original_filename: Optional[str], content_type: Optional[str]
) -> str:
    """Return a safe file extension for the stored video file."""
    if original_filename:
        candidate = Path(original_filename).suffix.lower()
        if candidate in EXT_TO_MIME:
            return candidate
    if content_type in MIME_TO_EXT:
        return MIME_TO_EXT[content_type]
    return ".webm"  # safe default for MediaRecorder output


def _validate_label_length(label: Optional[str]) -> Optional[str]:
    """Trim ``label`` and enforce the API-level 80-character cap."""
    if label is None:
        return None
    if not isinstance(label, str):
        raise HTTPException(status_code=422, detail="label must be a string.")
    trimmed = label.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_LABEL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"label must be at most {MAX_LABEL_LENGTH} characters.",
        )
    return trimmed


def _resolve_video_path(record: dict) -> Path:
    """Return the absolute path to a record's video, guaranteed inside RAW_DIR.

    Defence in depth against a tampered ``file_path`` value in the database.
    """
    relative = record.get("file_path")
    if not relative:
        raise HTTPException(
            status_code=500, detail="Recording has no associated file."
        )

    abs_path = (PROJECT_ROOT / relative).resolve()
    try:
        abs_path.relative_to(RAW_DIR.resolve())
    except ValueError:
        raise HTTPException(
            status_code=500, detail="Invalid file path in record."
        )

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Video file is missing.")
    return abs_path


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class LabelUpdate(BaseModel):
    """Body for PATCH /api/recordings/{id}."""
    label: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "translate-app-backend"}


@app.get("/api/recordings")
def list_recordings() -> dict:
    try:
        items = dataset_manager.get_all_recordings()
    except DatasetError as exc:
        raise _to_http_error(exc)

    sanitized = [_sanitize(r) for r in items]
    return {"items": sanitized, "count": len(sanitized)}


@app.get("/api/recordings/{recording_id}")
def get_recording(recording_id: str) -> dict:
    try:
        record = dataset_manager.get_recording_by_id(recording_id)
    except DatasetError as exc:
        raise _to_http_error(exc)
    return _sanitize(record)


@app.get("/api/recordings/{recording_id}/file")
def get_recording_file(recording_id: str):
    try:
        record = dataset_manager.get_recording_by_id(recording_id)
    except DatasetError as exc:
        raise _to_http_error(exc)

    path = _resolve_video_path(record)
    media_type = EXT_TO_MIME.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@app.post("/api/recordings", status_code=201)
async def create_recording(
    file: UploadFile = File(...),
    participant_id: str = Form(...),
    consent: bool = Form(...),
    label: Optional[str] = Form(None),
) -> dict:
    # ``file.close()`` must run on every exit path — success, validation
    # error, HTTPException, or unexpected crash. The outer try/finally
    # guarantees that. Close failures are swallowed so they never mask the
    # real error the client should see; the temp file will be cleaned up
    # by garbage collection regardless.
    try:
        # --- 1) Cheap validation BEFORE touching disk -------------------
        if not consent:
            raise HTTPException(
                status_code=422,
                detail="Consent is required to store a recording.",
            )

        validated_label = _validate_label_length(label)

        # Reuse dataset_manager's participant_id validator so the regex
        # lives in exactly one place.
        try:
            pid = dataset_manager._validate_participant_id(participant_id)
        except ValidationError as exc:
            raise _to_http_error(exc)

        # --- 2) Read the upload (chunked, size-capped) ------------------
        try:
            payload = read_upload(file.file)
        except UploadTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        except Exception:
            raise HTTPException(
                status_code=500, detail="Failed to read uploaded file."
            )

        if not payload:
            raise HTTPException(
                status_code=422, detail="Uploaded file is empty."
            )

        content_type = infer_content_type(file.filename, file.content_type)
        # Browsers sometimes send application/octet-stream for MediaRecorder
        # blobs. Fall back to extension-based inference in that case.
        if not content_type or content_type == "application/octet-stream":
            if file.filename:
                content_type = EXT_TO_MIME.get(
                    Path(file.filename).suffix.lower()
                )
        if not content_type or not content_type.startswith("video/"):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported content type '{content_type}'. "
                    "Only video/* accepted."
                ),
            )

        # --- 3) Persist the video file ---------------------------------
        # Fresh UUID filename; the client-supplied name never touches disk.
        rid = uuid.uuid4().hex
        extension = _safe_extension(file.filename, content_type)
        filename = f"{rid}{extension}"
        abs_video_path = RAW_DIR / filename
        relative_path = f"dataset/raw/{filename}"

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        try:
            abs_video_path.write_bytes(payload)
        except OSError:
            raise HTTPException(
                status_code=500, detail="Cannot write video file."
            )

        # --- 4) Persist metadata; roll back the file on any failure ----
        try:
            record = dataset_manager.add_recording(
                recording_id=rid,
                participant_id=pid,
                consent_given=True,
                filename=filename,
                file_path=relative_path,
                label=validated_label,
            )
        except DatasetError as exc:
            try:
                abs_video_path.unlink()
            except OSError:
                pass
            raise _to_http_error(exc)
        except Exception:
            try:
                abs_video_path.unlink()
            except OSError:
                pass
            raise HTTPException(
                status_code=500, detail="Internal server error."
            )

        return _sanitize(record)
    finally:
        # Guaranteed on every exit. Swallow close errors so we don't
        # mask the original exception (or a successful 201 response).
        try:
            await file.close()
        except Exception:
            pass


@app.patch("/api/recordings/{recording_id}")
def update_recording_label(recording_id: str, body: LabelUpdate) -> dict:
    validated_label = _validate_label_length(body.label)
    try:
        record = dataset_manager.update_label(recording_id, validated_label)
    except DatasetError as exc:
        raise _to_http_error(exc)
    return _sanitize(record)


@app.delete("/api/recordings/{recording_id}")
def delete_recording(recording_id: str) -> dict:
    """Delete the metadata row. The original video file is NOT deleted."""
    try:
        dataset_manager.delete_recording_by_id(recording_id)
    except DatasetError as exc:
        raise _to_http_error(exc)
    return {"deleted": recording_id}