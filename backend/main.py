"""FastAPI application for the Translate App dataset foundation."""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.dataset_manager import (
    RAW_DIR,
    delete_recording,
    initialize_database,
    list_recordings,
    save_recording_metadata,
)
from backend.recorder import save_video_upload

PARTICIPANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,40}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Translate App API",
    description="Backend foundation for consent-based video dataset collection.",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000",
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


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "translate-app-api"}


@app.post("/api/recordings", status_code=201)
async def upload_recording(
    file: UploadFile = File(...),
    participant_id: str = Form(...),
    consent_given: bool = Form(...),
    label: str | None = Form(default=None),
) -> dict:
    participant_id = participant_id.strip()
    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
        raise HTTPException(
            status_code=422,
            detail="participant_id must be 3-40 characters: letters, numbers, _ or -.",
        )

    if not consent_given:
        raise HTTPException(
            status_code=403,
            detail="Recording cannot be stored without the participant's consent.",
        )

    cleaned_label = label.strip() if label and label.strip() else None
    if cleaned_label and len(cleaned_label) > 80:
        raise HTTPException(status_code=422, detail="label must be 80 characters or fewer.")

    try:
        stored_filename, file_size, content_type = await save_video_upload(file)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    recording = {
        "id": uuid4().hex,
        "participant_id": participant_id,
        "label": cleaned_label,
        "consent_given": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_filename": Path(file.filename or "recording").name[:255],
        "stored_filename": stored_filename,
        "content_type": content_type,
        "file_size": file_size,
    }

    try:
        save_recording_metadata(recording)
    except Exception as error:
        (RAW_DIR / stored_filename).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save recording metadata.") from error

    return {
        "message": "Recording saved.",
        "recording": {
            key: value for key, value in recording.items()
            if key != "stored_filename"
        },
    }


@app.get("/api/recordings")
async def get_recordings() -> dict:
    return {"recordings": list_recordings()}


@app.delete("/api/recordings/{recording_id}")
async def remove_recording(recording_id: str) -> dict[str, str]:
    deleted = delete_recording(recording_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recording not found.")
    return {"message": "Recording deleted."}
