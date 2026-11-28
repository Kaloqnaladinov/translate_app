
"""Train and save the experimental Translate App gesture classifier.

All available recordings are used for training.
This version does not calculate validation or test accuracy.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.dataset import DatasetError, load_dataset
from ml.preprocess import (
    DEFAULT_SEQUENCE_LENGTH,
    FEATURES_PER_FRAME,
    PreprocessingError,
    preprocess_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "dataset" / "models"

MODEL_FILENAME = "sign_classifier.pkl"
METADATA_FILENAME = "sign_classifier.metadata.json"

RANDOM_STATE = 42
DEFAULT_ESTIMATORS = 300


class TrainingError(Exception):
    """Raised when model training cannot be completed."""


def _flatten_recording(recording: Any) -> list[float]:
    """Flatten one preprocessed recording into a feature vector."""

    if recording.sequence_length != DEFAULT_SEQUENCE_LENGTH:
        raise TrainingError(
            f"Recording {recording.recording_id} has invalid "
            f"sequence length: {recording.sequence_length}."
        )

    if recording.feature_count != FEATURES_PER_FRAME:
        raise TrainingError(
            f"Recording {recording.recording_id} has invalid "
            f"feature count: {recording.feature_count}."
        )

    return [
        value
        for frame in recording.sequence
        for value in frame
    ]


def _prepare_data(
    recordings: list[Any],
) -> tuple[list[list[float]], list[str]]:
    """Prepare model features and labels."""

    features = []
    labels = []

    for recording in recordings:
        features.append(_flatten_recording(recording))
        labels.append(recording.label)

    if not features:
        raise TrainingError("No training recordings are available.")

    expected_size = DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME

    for index, row in enumerate(features):
        if len(row) != expected_size:
            raise TrainingError(
                f"Recording at index {index} has {len(row)} features; "
                f"expected {expected_size}."
            )

    return features, labels


def _save_model(
    model: Any,
    metadata: dict[str, Any],
) -> tuple[Path, Path]:
    """Save model and metadata."""

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODELS_DIR / MODEL_FILENAME
    metadata_path = MODELS_DIR / METADATA_FILENAME

    temporary_model = MODELS_DIR / (MODEL_FILENAME + ".tmp")
    temporary_metadata = MODELS_DIR / (METADATA_FILENAME + ".tmp")

    try:
        with temporary_model.open("wb") as file:
            pickle.dump(
                model,
                file,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

        with temporary_metadata.open("w", encoding="utf-8") as file:
            json.dump(
                metadata,
                file,
                ensure_ascii=False,
                indent=4,
            )

        temporary_model.replace(model_path)
        temporary_metadata.replace(metadata_path)

    except (OSError, pickle.PickleError) as error:
        temporary_model.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)

        raise TrainingError(
            f"Could not save model files: {error}"
        ) from error

    return model_path, metadata_path


def train_model(
    estimators: int = DEFAULT_ESTIMATORS,
    seed: int = RANDOM_STATE,
) -> dict[str, Any]:
    """Train the classifier using every available recording."""

    if estimators < 10:
        raise TrainingError(
            "The number of estimators must be at least 10."
        )

    print("\n=== TRANSLATE APP MODEL TRAINING ===")

    # 1. Load the complete dataset.
    print("\n1. Loading complete dataset...")

    recordings = load_dataset()

    if len(recordings) < 2:
        raise TrainingError(
            "At least 2 recordings are required."
        )

    participant_ids = sorted({
        item.participant_id for item in recordings
    })

    all_labels = sorted({
        item.label for item in recordings
    })

    if len(all_labels) < 2:
        raise TrainingError(
            "At least 2 different gesture classes are required."
        )

    label_counts = Counter(item.label for item in recordings)
    participant_counts = Counter(
        item.participant_id for item in recordings
    )

    print(f"   Recordings:   {len(recordings)}")
    print(f"   Participants: {len(participant_ids)}")
    print(f"   Gesture classes: {len(all_labels)}")

    print("\n   Recordings per participant:")

    for participant_id, count in sorted(participant_counts.items()):
        print(f"      {participant_id}: {count}")

    print("\n   Recordings per gesture:")

    for label, count in sorted(label_counts.items()):
        print(f"      {label}: {count}")

    # 2. Preprocess every recording.
    print("\n2. Preprocessing all recordings...")

    processed = preprocess_dataset(recordings)

    if len(processed) != len(recordings):
        raise TrainingError(
            "The number of preprocessed recordings "
            "does not match the original dataset."
        )

    X_train, y_train = _prepare_data(processed)

    print(f"   Training samples: {len(X_train)}")
    print(f"   Features per sample: {len(X_train[0])}")

    # 3. Initialize the classifier.
    print("\n3. Initializing Random Forest...")

    try:
        import sklearn
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as error:
        raise TrainingError(
            "scikit-learn is not installed. "
            "Install it with: python -m pip install scikit-learn"
        ) from error

    model = RandomForestClassifier(
        n_estimators=estimators,
        random_state=seed,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=-1,
    )

    # 4. Train on all available recordings.
    print("\n4. Training model on ALL recordings...")
    print("   No validation or test split is being used.")

    model.fit(X_train, y_train)

    trained_classes = sorted(str(label) for label in model.classes_)

    if set(trained_classes) != set(all_labels):
        raise TrainingError(
            "The trained model classes do not match "
            "the dataset labels."
        )

    print("\n   Model training completed.")
    print(f"   Learned classes: {len(trained_classes)}")

    # 5. Prepare metadata.
    metadata = {
        "model_name": "Translate App Sign Classifier",
        "model_type": "RandomForestClassifier",
        "model_format": "pickle",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
        "random_state": seed,
        "estimators": estimators,
        "sequence_length": DEFAULT_SEQUENCE_LENGTH,
        "features_per_frame": FEATURES_PER_FRAME,
        "input_features": (
            DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME
        ),
        "training_scope": "all_available_recordings",
        "training_recordings": len(recordings),
        "participants": participant_ids,
        "participant_counts": dict(sorted(participant_counts.items())),
        "classes": trained_classes,
        "class_counts": dict(sorted(label_counts.items())),
        "evaluation_status": (
            "not_evaluated_no_independent_test_set"
        ),
        "validation_accuracy": None,
        "validation_macro_f1": None,
        "test_accuracy": None,
        "test_macro_f1": None,
        "warning": (
            "This is an experimental model. "
            "All available recordings were used for training. "
            "Independent evaluation on new recordings is required."
        ),
    }

    # 6. Save model and metadata.
    print("\n5. Saving model...")

    model_path, metadata_path = _save_model(model, metadata)

    print(f"   Model:    {model_path}")
    print(f"   Metadata: {metadata_path}")

    print("\n=== TRAINING COMPLETED ===")
    print("Training: PASSED")
    print("Independent evaluation: NOT PERFORMED")

    return metadata


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Train the Translate App gesture classifier "
            "using all available recordings."
        )
    )

    parser.add_argument(
        "--estimators",
        type=int,
        default=DEFAULT_ESTIMATORS,
        help="Number of Random Forest trees (default: 300).",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=RANDOM_STATE,
        help="Random seed (default: 42).",
    )

    args = parser.parse_args()

    try:
        train_model(
            estimators=args.estimators,
            seed=args.seed,
        )

    except (
        DatasetError,
        PreprocessingError,
        TrainingError,
    ) as error:
        print(f"\nTraining could not be completed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
