
"""Load, validate and split extracted sign-language landmark recordings."""

from __future__ import annotations

import json
import math
import random

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "dataset" / "processed"

SUPPORTED_SCHEMA_VERSIONS = {"1.1"}

LANDMARK_COUNTS = {
    "pose": 33,
    "left_hand": 21,
    "right_hand": 21,
}


class DatasetError(Exception):
    """Raised when a dataset cannot be loaded or validated."""


@dataclass(frozen=True)
class RecordingSample:
    """One complete recording and its extracted landmark frames."""

    recording_id: str
    label: str
    participant_id: str
    source_filename: str
    schema_version: str
    fps: float
    frames: tuple[dict[str, Any], ...]

    @property
    def frame_count(self) -> int:
        return len(self.frames)


@dataclass(frozen=True)
class DatasetSplit:
    """Dataset divided by participant, without participant leakage."""

    train: tuple[RecordingSample, ...]
    validation: tuple[RecordingSample, ...]
    test: tuple[RecordingSample, ...]

    def summary(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }


def _is_finite_number(value: Any) -> bool:
    """Return True only for finite numeric values (not booleans)."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _require_text(
    value: Any,
    field_name: str,
    file_path: Path,
    line_number: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            f"'{field_name}' must be a non-empty string."
        )

    return value.strip()


def _validate_landmarks(
    landmarks: Any,
    landmark_name: str,
    file_path: Path,
    line_number: int,
) -> None:
    """Validate one pose or hand landmark collection."""

    # MediaPipe returns None when a body part is not detected.
    if landmarks is None:
        return

    expected_count = LANDMARK_COUNTS[landmark_name]

    if not isinstance(landmarks, list):
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            f"'{landmark_name}' must be a list or null."
        )

    if len(landmarks) != expected_count:
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            f"'{landmark_name}' must contain "
            f"{expected_count} points; got {len(landmarks)}."
        )

    for point_index, point in enumerate(landmarks):
        if not isinstance(point, dict):
            raise DatasetError(
                f"{file_path.name}:{line_number}: "
                f"{landmark_name}[{point_index}] must be an object."
            )

        for coordinate in ("x", "y", "z"):
            value = point.get(coordinate)

            if not _is_finite_number(value):
                raise DatasetError(
                    f"{file_path.name}:{line_number}: "
                    f"{landmark_name}[{point_index}].{coordinate} "
                    f"must be a finite number."
                )

        if "visibility" in point:
            visibility = point["visibility"]

            if not _is_finite_number(visibility):
                raise DatasetError(
                    f"{file_path.name}:{line_number}: "
                    f"{landmark_name}[{point_index}].visibility "
                    f"must be a finite number."
                )


def _validate_frame(
    frame: Any,
    file_path: Path,
    line_number: int,
) -> dict[str, Any]:
    if not isinstance(frame, dict):
        raise DatasetError(
            f"{file_path.name}:{line_number}: frame must be an object."
        )

    if frame.get("record_type") != "frame":
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            "expected record_type='frame'."
        )

    frame_index = frame.get("frame_index")
    timestamp_ms = frame.get("timestamp_ms")

    if (
        isinstance(frame_index, bool)
        or not isinstance(frame_index, int)
        or frame_index < 0
    ):
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            "frame_index must be a non-negative integer."
        )

    if not _is_finite_number(timestamp_ms) or timestamp_ms < 0:
        raise DatasetError(
            f"{file_path.name}:{line_number}: "
            "timestamp_ms must be a finite non-negative number."
        )

    for landmark_name in LANDMARK_COUNTS:
        _validate_landmarks(
            frame.get(landmark_name),
            landmark_name,
            file_path,
            line_number,
        )

    return frame


def load_recording(file_path: str | Path) -> RecordingSample:
    """Load and validate one extracted JSONL recording."""

    path = Path(file_path)

    if not path.is_file():
        raise DatasetError(f"Dataset file does not exist: {path}")

    metadata = None
    frames = []
    previous_frame_index = -1

    try:
        with path.open("r", encoding="utf-8") as file:
            for line_number, raw_line in enumerate(file, start=1):
                if not raw_line.strip():
                    continue

                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise DatasetError(
                        f"{path.name}:{line_number}: invalid JSON: {error.msg}"
                    ) from error

                if not isinstance(record, dict):
                    raise DatasetError(
                        f"{path.name}:{line_number}: "
                        "each JSONL record must be an object."
                    )

                record_type = record.get("record_type")

                if record_type == "metadata":
                    if metadata is not None or frames:
                        raise DatasetError(
                            f"{path.name}:{line_number}: "
                            "metadata must appear exactly once, before frames."
                        )

                    metadata = record
                    continue

                if record_type == "frame":
                    if metadata is None:
                        raise DatasetError(
                            f"{path.name}:{line_number}: "
                            "metadata must appear before frame records."
                        )

                    frame = _validate_frame(
                        record,
                        path,
                        line_number,
                    )

                    if frame["frame_index"] <= previous_frame_index:
                        raise DatasetError(
                            f"{path.name}:{line_number}: "
                            "frame_index values must be strictly increasing."
                        )

                    previous_frame_index = frame["frame_index"]
                    frames.append(frame)
                    continue

                raise DatasetError(
                    f"{path.name}:{line_number}: "
                    f"unknown record_type: {record_type!r}."
                )

    except OSError as error:
        raise DatasetError(
            f"Could not read {path}: {error}"
        ) from error

    if metadata is None:
        raise DatasetError(f"{path.name}: metadata record is missing.")

    schema_version = metadata.get("schema_version")

    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise DatasetError(
            f"{path.name}: unsupported schema_version "
            f"{schema_version!r}. Supported: "
            f"{', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}."
        )

    recording_id = _require_text(
        metadata.get("recording_id"),
        "recording_id",
        path,
        1,
    )
    label = _require_text(
        metadata.get("label"),
        "label",
        path,
        1,
    )
    participant_id = _require_text(
        metadata.get("participant_id"),
        "participant_id",
        path,
        1,
    )
    source_filename = _require_text(
        metadata.get("source_filename"),
        "source_filename",
        path,
        1,
    )

    fps = metadata.get("fps")

    if not _is_finite_number(fps) or fps <= 0:
        raise DatasetError(
            f"{path.name}: metadata fps must be a positive finite number."
        )

    if not frames:
        raise DatasetError(f"{path.name}: recording contains no frames.")

    return RecordingSample(
        recording_id=recording_id,
        label=label,
        participant_id=participant_id,
        source_filename=source_filename,
        schema_version=schema_version,
        fps=float(fps),
        frames=tuple(frames),
    )


def load_dataset(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> list[RecordingSample]:
    """Load all extracted JSONL recordings from a directory."""

    directory = Path(dataset_dir)

    if not directory.is_dir():
        raise DatasetError(
            f"Processed dataset directory does not exist: {directory}"
        )

    files = sorted(directory.glob("*.landmarks.jsonl"))

    if not files:
        raise DatasetError(
            f"No '*.landmarks.jsonl' files found in {directory}."
        )

    recordings = []
    seen_recording_ids = set()

    for file_path in files:
        recording = load_recording(file_path)

        if recording.recording_id in seen_recording_ids:
            raise DatasetError(
                "Duplicate recording_id found: "
                f"{recording.recording_id}"
            )

        seen_recording_ids.add(recording.recording_id)
        recordings.append(recording)

    return recordings


def split_by_participant(
    recordings: list[RecordingSample],
    train_ratio: float = 0.70,
    validation_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> DatasetSplit:
    """
    Split recordings by participant, never by individual frame.

    This prevents recordings from the same participant from leaking
    into both training and evaluation sets.
    """

    ratios = (train_ratio, validation_ratio, test_ratio)

    if any(
        not _is_finite_number(ratio) or ratio <= 0
        for ratio in ratios
    ):
        raise DatasetError("All split ratios must be positive numbers.")

    if not math.isclose(sum(ratios), 1.0, rel_tol=0, abs_tol=1e-9):
        raise DatasetError("Split ratios must add up to 1.0.")

    if not recordings:
        raise DatasetError("Cannot split an empty dataset.")

    participants: dict[str, list[RecordingSample]] = {}

    for recording in recordings:
        participants.setdefault(
            recording.participant_id,
            [],
        ).append(recording)

    participant_ids = sorted(participants)

    if len(participant_ids) < 3:
        raise DatasetError(
            "At least 3 different participants are required for "
            "train/validation/test splitting. "
            f"Currently available: {len(participant_ids)}. "
            "Collect recordings from more participants."
        )

    rng = random.Random(seed)
    rng.shuffle(participant_ids)

    participant_count = len(participant_ids)

    train_count = max(1, round(participant_count * train_ratio))
    validation_count = max(1, round(participant_count * validation_ratio))

    # Always leave at least one participant for the test set.
    if train_count + validation_count >= participant_count:
        train_count = max(1, participant_count - 2)
        validation_count = 1

    train_ids = set(participant_ids[:train_count])
    validation_ids = set(
        participant_ids[train_count:train_count + validation_count]
    )
    test_ids = set(
        participant_ids[train_count + validation_count:]
    )

    def collect(ids: set[str]) -> tuple[RecordingSample, ...]:
        return tuple(
            recording
            for participant_id in sorted(ids)
            for recording in participants[participant_id]
        )

    return DatasetSplit(
        train=collect(train_ids),
        validation=collect(validation_ids),
        test=collect(test_ids),
    )


def print_dataset_summary(
    recordings: list[RecordingSample],
) -> None:
    """Print a human-readable dataset summary."""

    participants = {item.participant_id for item in recordings}
    labels = sorted({item.label for item in recordings})
    total_frames = sum(item.frame_count for item in recordings)

    print("\n=== TRANSLATE APP DATASET ===")
    print(f"Recordings:   {len(recordings)}")
    print(f"Participants: {len(participants)}")
    print(f"Labels:       {len(labels)}")
    print(f"Total frames: {total_frames}")

    print("\nRecordings per label:")

    for label in labels:
        count = sum(item.label == label for item in recordings)
        print(f"  {label}: {count}")

    print("\nParticipants:")

    for participant_id in sorted(participants):
        count = sum(
            item.participant_id == participant_id
            for item in recordings
        )
        print(f"  {participant_id}: {count} recordings")


def main() -> None:
    """Run dataset validation from the command line."""

    try:
        recordings = load_dataset()
        print_dataset_summary(recordings)

        print("\nDataset validation: PASSED")

        try:
            split = split_by_participant(recordings)

            print("\nParticipant split:")
            for name, count in split.summary().items():
                print(f"  {name}: {count} recordings")

        except DatasetError as error:
            print("\nParticipant split is not ready:")
            print(f"  {error}")

    except DatasetError as error:
        raise SystemExit(f"\nDataset validation failed:\n{error}") from error


if __name__ == "__main__":
    main()
