
"""Normalize and resample landmark recordings for ML training."""

from __future__ import annotations


from dataclasses import dataclass
import math
from typing import Any, Sequence



from ml.dataset import (
    DatasetError,
    RecordingSample,
    load_dataset,
)


# One recording is converted into exactly this many frames.
DEFAULT_SEQUENCE_LENGTH = 64

# 33 pose + 21 left hand + 21 right hand.
LANDMARK_COUNT = 75

# Each point contains x, y, z and visibility.
VALUES_PER_POINT = 4

# Three additional values indicate whether pose/left/right hand
# landmarks were detected in the frame.
GROUP_MASK_COUNT = 3

FEATURES_PER_FRAME = (
    LANDMARK_COUNT * VALUES_PER_POINT + GROUP_MASK_COUNT
)


class PreprocessingError(Exception):
    """Raised when landmark preprocessing fails."""


@dataclass(frozen=True)
class PreprocessedRecording:
    """One normalized and temporally resampled recording."""

    recording_id: str
    label: str
    participant_id: str
    sequence: tuple[tuple[float, ...], ...]
    original_frame_count: int
    detected_frame_count: int

    @property
    def sequence_length(self) -> int:
        return len(self.sequence)

    @property
    def feature_count(self) -> int:
        return len(self.sequence[0]) if self.sequence else 0

    @property
    def detection_ratio(self) -> float:
        if self.original_frame_count == 0:
            return 0.0

        return self.detected_frame_count / self.original_frame_count


def _is_valid_point(point: Any) -> bool:
    """Check whether a landmark contains finite coordinates."""

    if not isinstance(point, dict):
        return False

    for key in ("x", "y", "z"):
        value = point.get(key)

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return False

    return True


def _valid_group(
    landmarks: Any,
    expected_count: int,
    group_name: str,
) -> list[dict[str, Any]] | None:
    """Return a valid landmark group or None if it was not detected."""

    if landmarks is None:
        return None

    if not isinstance(landmarks, list):
        raise PreprocessingError(
            f"{group_name} must be a list or None."
        )

    if len(landmarks) != expected_count:
        raise PreprocessingError(
            f"{group_name} must contain {expected_count} points."
        )

    if not all(_is_valid_point(point) for point in landmarks):
        raise PreprocessingError(
            f"{group_name} contains invalid landmark coordinates."
        )

    return landmarks


def _distance_2d(
    first: dict[str, Any],
    second: dict[str, Any],
) -> float:
    return math.hypot(
        float(first["x"]) - float(second["x"]),
        float(first["y"]) - float(second["y"]),
    )


def _midpoint(
    first: dict[str, Any],
    second: dict[str, Any],
) -> tuple[float, float, float]:
    return (
        (float(first["x"]) + float(second["x"])) / 2.0,
        (float(first["y"]) + float(second["y"])) / 2.0,
        (float(first["z"]) + float(second["z"])) / 2.0,
    )


def _calculate_reference(
    pose: list[dict[str, Any]] | None,
    left_hand: list[dict[str, Any]] | None,
    right_hand: list[dict[str, Any]] | None,
) -> tuple[tuple[float, float, float], float]:
    """
    Calculate a common coordinate origin and scale.

    Priority:
    1. Midpoint between shoulders, scaled by shoulder width.
    2. Midpoint between hips, scaled by hip width.
    3. Midpoint between detected wrists.
    4. Center of all detected landmarks.
    """

    if pose is not None:
        # MediaPipe Pose: left shoulder 11, right shoulder 12.
        left_shoulder = pose[11]
        right_shoulder = pose[12]

        if _distance_2d(left_shoulder, right_shoulder) > 1e-6:
            return (
                _midpoint(left_shoulder, right_shoulder),
                _distance_2d(left_shoulder, right_shoulder),
            )

        # MediaPipe Pose: left hip 23, right hip 24.
        left_hip = pose[23]
        right_hip = pose[24]

        if _distance_2d(left_hip, right_hip) > 1e-6:
            return (
                _midpoint(left_hip, right_hip),
                _distance_2d(left_hip, right_hip),
            )

    wrists = []

    if left_hand is not None:
        wrists.append(left_hand[0])

    if right_hand is not None:
        wrists.append(right_hand[0])

    if len(wrists) == 2:
        anchor = _midpoint(wrists[0], wrists[1])
    elif len(wrists) == 1:
        point = wrists[0]
        anchor = (
            float(point["x"]),
            float(point["y"]),
            float(point["z"]),
        )
    else:
        all_points = []

        for group in (pose, left_hand, right_hand):
            if group is not None:
                all_points.extend(group)

        if not all_points:
            return (0.0, 0.0, 0.0), 1.0

        anchor = (
            sum(float(p["x"]) for p in all_points) / len(all_points),
            sum(float(p["y"]) for p in all_points) / len(all_points),
            sum(float(p["z"]) for p in all_points) / len(all_points),
        )

    all_points = []

    for group in (pose, left_hand, right_hand):
        if group is not None:
            all_points.extend(group)

    scale = max(
        (
            _distance_2d(
                {"x": anchor[0], "y": anchor[1]},
                point,
            )
            for point in all_points
        ),
        default=1.0,
    )

    return anchor, max(scale, 1e-6)




def _normalize_group(
    landmarks: list[dict[str, Any]] | None,
    anchor: tuple[float, float, float],
    scale: float,
    expected_count: int,
) -> list[float]:
    """Normalize one landmark group into a flat numeric list."""

    if landmarks is None:
        return [0.0] * (expected_count * VALUES_PER_POINT)

    values = []

    for point in landmarks:
        x = (float(point["x"]) - anchor[0]) / scale
        y = (float(point["y"]) - anchor[1]) / scale
        z = (float(point["z"]) - anchor[2]) / scale

        visibility = float(point.get("visibility", 1.0))

        values.extend((x, y, z, visibility))

    return values



def preprocess_frame(frame: dict[str, Any]) -> tuple[float, ...]:
    """Convert one extracted frame into a fixed-size feature vector."""

    pose = _valid_group(frame.get("pose"), 33, "pose")
    left_hand = _valid_group(
        frame.get("left_hand"),
        21,
        "left_hand",
    )
    right_hand = _valid_group(
        frame.get("right_hand"),
        21,
        "right_hand",
    )

    anchor, scale = _calculate_reference(
        pose,
        left_hand,
        right_hand,
    )

    features = []

    # Pose: 33 points.
    features.extend(_normalize_group(pose, anchor, scale, 33))
    features.extend(_normalize_group(left_hand, anchor, scale, 21))
    features.extend(_normalize_group(right_hand, anchor, scale, 21))

    # Detection masks: pose, left hand, right hand.
    features.extend(
        (
            1.0 if pose is not None else 0.0,
            1.0 if left_hand is not None else 0.0,
            1.0 if right_hand is not None else 0.0,
        )
    )

    if len(features) != FEATURES_PER_FRAME:
        raise PreprocessingError(
            "Unexpected feature vector size: "
            f"{len(features)} instead of {FEATURES_PER_FRAME}."
        )

    if not all(math.isfinite(value) for value in features):
        raise PreprocessingError(
            "Preprocessing produced a non-finite feature."
        )

    return tuple(features)


def _interpolate(
    first: Sequence[float],
    second: Sequence[float],
    ratio: float,
) -> tuple[float, ...]:
    """Linearly interpolate two feature vectors."""

    return tuple(
        a + (b - a) * ratio
        for a, b in zip(first, second)
    )


def resample_sequence(
    features: Sequence[Sequence[float]],
    timestamps: Sequence[float],
    sequence_length: int = DEFAULT_SEQUENCE_LENGTH,
) -> tuple[tuple[float, ...], ...]:
    """Resample a recording to a fixed number of temporal frames."""

    if sequence_length < 2:
        raise PreprocessingError(
            "sequence_length must be at least 2."
        )

    if not features:
        raise PreprocessingError(
            "Cannot resample an empty recording."
        )

    if len(features) != len(timestamps):
        raise PreprocessingError(
            "Features and timestamps must have the same length."
        )

    if any(len(row) != FEATURES_PER_FRAME for row in features):
        raise PreprocessingError(
            "Input contains a feature vector with an invalid size."
        )

    if len(features) == 1:
        return tuple(
            tuple(features[0])
            for _ in range(sequence_length)
        )

    if any(
        not math.isfinite(float(timestamp))
        for timestamp in timestamps
    ):
        raise PreprocessingError(
            "Timestamps must contain finite numbers."
        )

    if any(
        timestamps[index] <= timestamps[index - 1]
        for index in range(1, len(timestamps))
    ):
        raise PreprocessingError(
            "Timestamps must be strictly increasing."
        )

    start = float(timestamps[0])
    end = float(timestamps[-1])

    if end <= start:
        raise PreprocessingError(
            "Recording duration must be positive."
        )

    result = []
    right_index = 1

    for output_index in range(sequence_length):
        target_time = start + (
            (end - start) * output_index / (sequence_length - 1)
        )

        while (
            right_index < len(timestamps) - 1
            and timestamps[right_index] < target_time
        ):
            right_index += 1

        left_index = right_index - 1

        left_time = float(timestamps[left_index])
        right_time = float(timestamps[right_index])

        duration = right_time - left_time

        ratio = (
            0.0
            if duration <= 0
            else (target_time - left_time) / duration
        )

        ratio = min(1.0, max(0.0, ratio))

        result.append(
            _interpolate(
                features[left_index],
                features[right_index],
                ratio,
            )
        )

    return tuple(result)


def preprocess_recording(
    recording: RecordingSample,
    sequence_length: int = DEFAULT_SEQUENCE_LENGTH,
) -> PreprocessedRecording:
    """Preprocess one complete RecordingSample."""

    if not isinstance(recording, RecordingSample):
        raise PreprocessingError(
            "recording must be a RecordingSample."
        )

    if sequence_length < 2:
        raise PreprocessingError(
            "sequence_length must be at least 2."
        )

    features = []
    timestamps = []
    detected_frame_count = 0

    for frame in recording.frames:
        features.append(preprocess_frame(frame))
        timestamps.append(float(frame["timestamp_ms"]))

        if any(
            frame.get(group) is not None
            for group in ("pose", "left_hand", "right_hand")
        ):
            detected_frame_count += 1

    if detected_frame_count == 0:
        raise PreprocessingError(
            f"Recording {recording.recording_id} has no detected "
            "body or hand landmarks."
        )

    sequence = resample_sequence(
        features,
        timestamps,
        sequence_length,
    )

    return PreprocessedRecording(
        recording_id=recording.recording_id,
        label=recording.label,
        participant_id=recording.participant_id,
        sequence=sequence,
        original_frame_count=len(recording.frames),
        detected_frame_count=detected_frame_count,
    )


def preprocess_dataset(
    recordings: Sequence[RecordingSample],
    sequence_length: int = DEFAULT_SEQUENCE_LENGTH,
) -> list[PreprocessedRecording]:
    """Preprocess every recording in a dataset."""

    if not recordings:
        raise PreprocessingError(
            "Cannot preprocess an empty dataset."
        )

    processed = []

    for recording in recordings:
        try:
            processed.append(
                preprocess_recording(
                    recording,
                    sequence_length,
                )
            )
        except PreprocessingError as error:
            raise PreprocessingError(
                f"Recording {recording.recording_id}: {error}"
            ) from error

    return processed


def print_preprocessing_summary(
    recordings: Sequence[PreprocessedRecording],
) -> None:
    """Print preprocessing results."""

    if not recordings:
        raise PreprocessingError(
            "No preprocessed recordings to summarize."
        )

    labels = sorted({item.label for item in recordings})

    print("\n=== PREPROCESSING SUMMARY ===")
    print(f"Recordings:       {len(recordings)}")
    print(f"Labels:           {len(labels)}")
    print(f"Sequence length:  {recordings[0].sequence_length}")
    print(f"Features / frame: {recordings[0].feature_count}")
    print(
        f"Total ML values:  "
        f"{sum(item.sequence_length * item.feature_count for item in recordings)}"
    )

    print("\nDetection quality:")

    for item in recordings:
        percentage = item.detection_ratio * 100

        print(
            f"  {item.recording_id}: "
            f"{item.detected_frame_count}/"
            f"{item.original_frame_count} frames "
            f"({percentage:.1f}%)"
        )

    print("\nRecordings per label:")

    for label in labels:
        count = sum(item.label == label for item in recordings)
        print(f"  {label}: {count}")


def main() -> None:
    """Load and preprocess the local dataset."""

    try:
        recordings = load_dataset()
        processed = preprocess_dataset(recordings)

        print_preprocessing_summary(processed)

        print("\nPreprocessing validation: PASSED")

    except (DatasetError, PreprocessingError) as error:
        raise SystemExit(
            f"\nPreprocessing failed:\n{error}"
        ) from error


if __name__ == "__main__":
    main()


