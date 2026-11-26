
"""Extract body and hand landmarks from original source videos."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from backend.dataset_manager import DATASET_DIR, RAW_DIR

PROCESSED_DIR = DATASET_DIR / "processed"
SOURCE_DIR = RAW_DIR / "source"

SOURCE_FOLDERS = {
    "letters": SOURCE_DIR / "letters",
    "words": SOURCE_DIR / "words",
}

SUPPORTED_EXTENSIONS = {".webm", ".mp4", ".mov"}

# Keep compatibility with ml/dataset.py.
EXTRACTION_VERSION = "1.1"

PARTICIPANTS = {
    "ani": "participant_002",
    "bozhi": "participant_003",
    "sofi": "participant_001",
}


class ExtractionError(Exception):
    """Raised when video landmark extraction fails."""


def discover_source_videos() -> list[Path]:
    """Find videos in source/letters and source/words."""

    videos = []

    for folder in SOURCE_FOLDERS.values():
        if not folder.is_dir():
            continue

        for path in folder.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ):
                videos.append(path)

    return sorted(videos, key=lambda path: str(path).lower())


def _validate_video_path(video_path: str | Path) -> Path:
    """Only accept videos stored inside dataset/raw."""

    source = Path(video_path).resolve()
    raw_root = RAW_DIR.resolve()

    if not source.is_file():
        raise ExtractionError("Video file does not exist.")

    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ExtractionError("Unsupported video format.")

    try:
        source.relative_to(raw_root)
    except ValueError as error:
        raise ExtractionError(
            "Video must be stored inside dataset/raw."
        ) from error

    return source


def _normalize_label(label: str) -> str:
    """Normalize filename-derived labels without merging meanings."""

    label = label.strip()
    label = re.sub(r"[_\s]+", " ", label)
    label = re.sub(r"\s+", " ", label)

    return label.casefold().strip()


def _get_video_metadata(source: Path) -> dict[str, str | None]:
    """Infer category, participant and gesture label."""

    try:
        relative = source.relative_to(SOURCE_DIR.resolve())
    except ValueError:
        return {
            "category": None,
            "participant_id": None,
            "label": None,
        }

    category = relative.parts[0] if relative.parts else None

    if category not in SOURCE_FOLDERS:
        raise ExtractionError(
            f"Unknown source category: {category}"
        )

    stem = source.stem
    participant_id = None
    label = None

    for prefix, identifier in PARTICIPANTS.items():
        marker = prefix + "_"

        if stem.casefold().startswith(marker):
            participant_id = identifier
            label = stem[len(marker):]
            break

    if label:
        # Remove repetition suffixes: _1, _2, _1-1, etc.
        label = re.sub(r"(?:_|-)\d+(?:-\d+)?$", "", label)
        label = _normalize_label(label)

    if not participant_id:
        raise ExtractionError(
            f"Could not identify participant from filename: {source.name}"
        )

    if not label:
        raise ExtractionError(
            f"Could not identify gesture label: {source.name}"
        )

    return {
        "category": category,
        "participant_id": participant_id,
        "label": label,
    }


def _recording_id(source: Path) -> str:
    """Generate a stable 32-character ID from the relative source path."""

    relative = source.relative_to(RAW_DIR.resolve()).as_posix().casefold()
    return hashlib.md5(
        relative.encode("utf-8")
    ).hexdigest()


def _output_filename(source: Path) -> str:
    """Create a unique processed filename."""

    relative = source.relative_to(SOURCE_DIR.resolve())
    parts = list(relative.parts[:-1]) + [source.stem]

    safe_name = "__".join(parts)
    safe_name = re.sub(r"[^\w.-]+", "_", safe_name)

    return f"{safe_name}.landmarks.jsonl"


def _landmarks_to_list(
    landmarks: Any,
) -> list[dict[str, float]] | None:
    """Convert MediaPipe landmarks to JSON-compatible values."""

    if landmarks is None:
        return None

    points = []

    for point in landmarks.landmark:
        item = {
            "x": float(point.x),
            "y": float(point.y),
            "z": float(point.z),
        }

        if hasattr(point, "visibility"):
            item["visibility"] = float(point.visibility)

        points.append(item)

    return points


def extract_video_landmarks(
    video_path: str | Path,
    frame_step: int = 1,
    model_complexity: int = 1,
    min_detection_confidence: float = 0.5,
    min_tracking_confidence: float = 0.5,
    recording_id: str | None = None,
    label: str | None = None,
    participant_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Extract pose and both-hand landmarks from one video."""

    if (
        isinstance(frame_step, bool)
        or not isinstance(frame_step, int)
        or frame_step < 1
    ):
        raise ExtractionError(
            "frame_step must be a positive integer."
        )

    if model_complexity not in (0, 1, 2):
        raise ExtractionError(
            "model_complexity must be 0, 1 or 2."
        )

    for name, value in (
        ("min_detection_confidence", min_detection_confidence),
        ("min_tracking_confidence", min_tracking_confidence),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0.0 <= value <= 1.0
        ):
            raise ExtractionError(
                f"{name} must be between 0.0 and 1.0."
            )

    source = _validate_video_path(video_path)
    inferred = _get_video_metadata(source)

    label = _normalize_label(label) if label else inferred["label"]
    participant_id = participant_id or inferred["participant_id"]
    recording_id = recording_id or _recording_id(source)

    if not label or not participant_id or not recording_id:
        raise ExtractionError(
            "Missing recording ID, label or participant ID."
        )

    try:
        import cv2
        import mediapipe as mp
    except ImportError as error:
        raise ExtractionError(
            "Install OpenCV and MediaPipe before extraction."
        ) from error

    if not hasattr(mp, "solutions"):
        raise ExtractionError(
            "This MediaPipe installation does not expose mp.solutions."
        )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    output_path = PROCESSED_DIR / _output_filename(source)

    if output_path.exists() and not overwrite:
        raise ExtractionError(
            f"Extraction already exists: {output_path.name}"
        )

    capture = cv2.VideoCapture(str(source))

    if not capture.isOpened():
        capture.release()
        raise ExtractionError("Could not open the video file.")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_frame_count = int(
        capture.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    if fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ExtractionError(
            "Video has invalid FPS or dimensions."
        )

    frame_index = 0
    processed_frames = 0
    success_completed = False

    try:
        with mp.solutions.holistic.Holistic(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=True,
            enable_segmentation=False,
            refine_face_landmarks=False,
            min_detection_confidence=float(
                min_detection_confidence
            ),
            min_tracking_confidence=float(
                min_tracking_confidence
            ),
        ) as holistic:

            with output_path.open(
                "w" if overwrite else "x",
                encoding="utf-8",
            ) as output:

                metadata = {
                    "record_type": "metadata",
                    "schema_version": EXTRACTION_VERSION,
                    "recording_id": recording_id,
                    "label": label,
                    "participant_id": participant_id,
                    "category": inferred["category"],
                    "source_filename": source.name,
                    "source_relative_path": str(
                        source.relative_to(RAW_DIR.resolve())
                    ),
                    "fps": fps,
                    "width": width,
                    "height": height,
                    "reported_frame_count": reported_frame_count,
                    "frame_step": frame_step,
                    "model": "MediaPipe Holistic",
                    "model_complexity": model_complexity,
                    "landmarks": [
                        "pose",
                        "left_hand",
                        "right_hand",
                    ],
                }

                output.write(
                    json.dumps(
                        metadata,
                        ensure_ascii=False,
                        allow_nan=False,
                    ) + "\n"
                )

                while True:
                    frame_ok, frame = capture.read()

                    if not frame_ok:
                        break

                    current_index = frame_index
                    frame_index += 1

                    if current_index % frame_step != 0:
                        continue

                    rgb_frame = cv2.cvtColor(
                        frame,
                        cv2.COLOR_BGR2RGB,
                    )
                    rgb_frame.flags.writeable = False

                    results = holistic.process(rgb_frame)

                    frame_data = {
                        "record_type": "frame",
                        "frame_index": current_index,
                        "timestamp_ms": round(
                            (current_index / fps) * 1000,
                            3,
                        ),
                        "pose": _landmarks_to_list(
                            results.pose_landmarks
                        ),
                        "left_hand": _landmarks_to_list(
                            results.left_hand_landmarks
                        ),
                        "right_hand": _landmarks_to_list(
                            results.right_hand_landmarks
                        ),
                    }

                    output.write(
                        json.dumps(
                            frame_data,
                            allow_nan=False,
                        ) + "\n"
                    )

                    processed_frames += 1

                output.flush()

        if processed_frames == 0:
            raise ExtractionError(
                "No video frames could be processed."
            )

        success_completed = True

        return {
            "recording_id": recording_id,
            "label": label,
            "participant_id": participant_id,
            "category": inferred["category"],
            "source": source.name,
            "output_filename": output_path.name,
            "total_frames_read": frame_index,
            "processed_frames": processed_frames,
            "fps": fps,
            "width": width,
            "height": height,
            "schema_version": EXTRACTION_VERSION,
        }

    except ExtractionError:
        raise

    except Exception as error:
        raise ExtractionError(
            f"Landmark extraction failed: {error}"
        ) from error

    finally:
        capture.release()

        if not success_completed:
            output_path.unlink(missing_ok=True)


def extract_source_dataset(
    frame_step: int = 1,
    model_complexity: int = 1,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Extract all videos in source/letters and source/words."""

    videos = discover_source_videos()

    results = []
    errors = []
    skipped = []

    for video in videos:
        output_name = _output_filename(video)
        output_path = PROCESSED_DIR / output_name

        if output_path.exists() and not overwrite:
            skipped.append(video.name)
            continue

        try:
            result = extract_video_landmarks(
                video_path=video,
                frame_step=frame_step,
                model_complexity=model_complexity,
                overwrite=overwrite,
            )

            results.append(result)

            print(
                f"[OK] {video.name}: "
                f"{result['processed_frames']} frames"
            )

        except Exception as error:
            errors.append({
                "filename": video.name,
                "error": str(error),
            })

            print(f"[ERROR] {video.name}: {error}")

    return {
        "discovered": len(videos),
        "processed": len(results),
        "skipped": len(skipped),
        "failed": len(errors),
        "results": results,
        "skipped_files": skipped,
        "errors": errors,
    }
