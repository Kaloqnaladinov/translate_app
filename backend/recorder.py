"""Safe streaming storage for uploaded video recordings."""

from __future__ import annotations

from uuid import uuid4

from fastapi import UploadFile

from backend.dataset_manager import RAW_DIR

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_VIDEO_TYPES = {
    "video/webm": ".webm",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


async def save_video_upload(upload: UploadFile) -> tuple[str, int, str]:
    """Stream an uploaded video to dataset/raw using a generated filename."""
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    extension = ALLOWED_VIDEO_TYPES.get(content_type)

    if extension is None:
        raise ValueError("Unsupported video format. Use WebM, MP4 or MOV.")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{extension}"
    destination = RAW_DIR / stored_filename
    total_size = 0

    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_BYTES:
                    raise ValueError("Video is too large. Maximum size is 100 MB.")
                output.write(chunk)

        if total_size == 0:
            raise ValueError("The uploaded video is empty.")

        return stored_filename, total_size, content_type
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
