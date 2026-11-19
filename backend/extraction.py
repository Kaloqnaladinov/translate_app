
"""Extract hand and body landmarks from raw sign-language videos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.dataset_manager import DATASET_DIR, RAW_DIR

PROCESSED_DIR = DATASET_DIR / "processed"
SUPPORTED_EXTENSIONS = {".webm", ".mp4", ".mov"}
EXTRACTION_VERSION = "1.0"


class ExtractionError(Exception):
    """Raised when video landmark extraction fails."""


def _validate_video_path(video_path: str | Path) -> Path:
    """Accept only existing video files stored directly in dataset/raw."""
    raw_root = RAW_DIR.resolve()
    source = Path(video_path).resolve()

    if source.parent != raw_root:
        raise ExtractionError("Video must be stored directly inside dataset/raw.")

    if not source.is_file():
        raise ExtractionError("Video file does not exist.")

    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ExtractionError("Unsupported video format.")

    return source


def _landmarks_to_list(landmarks: Any) -> list[dict[str, float]] | None:
    """Convert MediaPipe landmarks into JSON-compatible coordinates."""
    if landmarks is None:
        return None

    points = []

    for point in landmarks.landmark:
        item = {
            "x": float(point.x),
            "y": float(point.y),
            "z": float(point.z),
        }

        # Pose landmarks may also contain visibility information.
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
) -> dict[str, Any]:
    """
    Extract pose and both-hand landmarks from a video.

    The original video is never modified.
    Results are written to dataset/processed as JSON Lines.
    """
    if isinstance(frame_step, bool) or not isinstance(frame_step, int) or frame_step < 1:
        raise ExtractionError("frame_step must be a positive integer.")

    if model_complexity not in (0, 1, 2):
        raise ExtractionError("model_complexity must be 0, 1 or 2.")

    for name, value in (
        ("min_detection_confidence", min_detection_confidence),
        ("min_tracking_confidence", min_tracking_confidence),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0.0 <= value <= 1.0
        ):
            raise ExtractionError(f"{name} must be between 0.0 and 1.0.")

    source = _validate_video_path(video_path)

    # Imports are delayed so the rest of the backend can start
    # even when the extraction dependencies are not installed.
    try:
        import cv2
        import mediapipe as mp
    except ImportError as error:
        raise ExtractionError(
            "Landmark extraction requires OpenCV and MediaPipe. "
            "Install them with: pip install opencv-python mediapipe"
        ) from error

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    output_path = PROCESSED_DIR / f"{source.stem}.landmarks.jsonl"

    if output_path.exists():
        raise ExtractionError(
            "An extraction result already exists for this video. "
            "Move or rename the existing result before retrying."
        )

    capture = cv2.VideoCapture(str(source))

    if not capture.isOpened():
        capture.release()
        raise ExtractionError("Could not open the video file.")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ExtractionError("Video has invalid FPS or dimensions.")

    frame_index = 0
    processed_frames = 0
    output_created = False

    try:
        with mp.solutions.holistic.Holistic(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=True,
            enable_segmentation=False,
            refine_face_landmarks=False,
            min_detection_confidence=float(min_detection_confidence),
            min_tracking_confidence=float(min_tracking_confidence),
        ) as holistic:

            with output_path.open("x", encoding="utf-8") as output:
                output_created = True

                metadata = {
                    "record_type": "metadata",
                    "schema_version": EXTRACTION_VERSION,
                    "source_filename": source.name,
                    "fps": fps,
                    "width": width,
                    "height": height,
                    "reported_frame_count": reported_frame_count,
                    "frame_step": frame_step,
                    "model": "MediaPipe Holistic",
                    "model_complexity": model_complexity,
                    "landmarks": ["pose", "left_hand", "right_hand"],
                }

                output.write(json.dumps(metadata, allow_nan=False) + "\n")

                while True:
                    success, frame = capture.read()

                    if not success:
                        break

                    current_index = frame_index
                    frame_index += 1

                    if current_index % frame_step != 0:
                        continue

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    rgb_frame.flags.writeable = False
                    results = holistic.process(rgb_frame)

                    frame_data = {
                        "record_type": "frame",
                        "frame_index": current_index,
                        "timestamp_ms": round(
                            (current_index / fps) * 1000, 3
                        ),
                        "pose": _landmarks_to_list(results.pose_landmarks),
                        "left_hand": _landmarks_to_list(
                            results.left_hand_landmarks
                        ),
                        "right_hand": _landmarks_to_list(
                            results.right_hand_landmarks
                        ),
                    }

                    output.write(
                        json.dumps(frame_data, allow_nan=False) + "\n"
                    )
                    processed_frames += 1

                output.flush()

        if processed_frames == 0:
            raise ExtractionError("No video frames could be processed.")

        return {
            "source": source.name,
            "output": str(output_path),
            "total_frames_read": frame_index,
            "processed_frames": processed_frames,
            "fps": fps,
            "width": width,
            "height": height,
        }

    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(
            f"Landmark extraction failed: {error}"
        ) from error
    finally:
        capture.release()

        # Do not leave an incomplete result that could be mistaken
        # for a successful extraction.
        if output_created and (
            "processed_frames" not in locals() or processed_frames == 0
        ):
            output_path.unlink(missing_ok=True)
