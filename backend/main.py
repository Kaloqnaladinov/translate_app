
"""Train an experimental sign-language classifier using all recordings."""

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


def flatten_recording(recording: Any) -> list[float]:
    """Convert a preprocessed sequence into one feature vector."""

    if recording.sequence_length != DEFAULT_SEQUENCE_LENGTH:
        raise TrainingError(
            f"Invalid sequence length: {recording.recording_id}"
        )

    if recording.feature_count != FEATURES_PER_FRAME:
        raise TrainingError(
            f"Invalid feature count: {recording.recording_id}"
        )

    return [
        value
        for frame in recording.sequence
        for value in frame
    ]


def prepare_data(
    recordings: list[Any],
) -> tuple[list[list[float]], list[str]]:
    """Prepare all recordings for classifier training."""

    features = []
    labels = []

    for recording in recordings:
        features.append(flatten_recording(recording))
        labels.append(recording.label)

    if not features:
        raise TrainingError("No training recordings available.")

    expected_size = DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME

    if any(len(row) != expected_size for row in features):
        raise TrainingError(
            f"Expected {expected_size} features per recording."
        )

    return features, labels


def save_model(
    model: Any,
    metadata: dict[str, Any],
) -> tuple[Path, Path]:
    """Save model and metadata."""

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODELS_DIR / MODEL_FILENAME
    metadata_path = MODELS_DIR / METADATA_FILENAME

    temporary_model = MODELS_DIR / "sign_classifier.tmp.pkl"
    temporary_metadata = MODELS_DIR / "sign_classifier.tmp.json"

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

    except OSError as error:
        temporary_model.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)

        raise TrainingError(
            f"Could not save model: {error}"
        ) from error

    return model_path, metadata_path


def train_model(
    estimators: int = DEFAULT_ESTIMATORS,
    seed: int = RANDOM_STATE,
) -> dict[str, Any]:
    """Train using every valid recording in the dataset."""

    if estimators < 10:
        raise TrainingError(
            "At least 10 estimators are required."
        )

    print("\n=== TRANSLATE APP EXPERIMENTAL MODEL TRAINING ===")

    # 1. Load complete dataset.
    print("\n1. Loading complete dataset...")

    recordings = load_dataset()

    if len(recordings) < 2:
        raise TrainingError(
            "At least two recordings are required."
        )

    participants = sorted({
        item.participant_id for item in recordings
    })

    labels = sorted({
        item.label for item in recordings
    })

    if len(labels) < 2:
        raise TrainingError(
            "At least two gesture classes are required."
        )

    print(f"   Recordings:      {len(recordings)}")
    print(f"   Participants:    {len(participants)}")
    print(f"   Gesture classes: {len(labels)}")

    # 2. Inspect class distribution.
    label_counts = Counter(
        item.label for item in recordings
    )

    singleton_labels = sorted(
        label
        for label, count in label_counts.items()
        if count == 1
    )

    print("\n2. Checking gesture distribution...")
    print(f"   Classes with one recording: {len(singleton_labels)}")
    print(
        "   Classes with multiple recordings: "
        f"{len(labels) - len(singleton_labels)}"
    )

    if singleton_labels:
        print(
            "   WARNING: Some classes have only one example."
        )

    # 3. Preprocess every recording.
    print("\n3. Preprocessing ALL recordings...")

    processed = preprocess_dataset(recordings)

    X_train, y_train = prepare_data(processed)

    print(f"   Processed recordings: {len(X_train)}")
    print(f"   Features per recording: {len(X_train[0])}")

    # 4. Initialize classifier.
    print("\n4. Initializing Random Forest...")

    try:
        import sklearn
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as error:
        raise TrainingError(
            "scikit-learn is missing. Install it with "
            "python -m pip install scikit-learn"
        ) from error

    model = RandomForestClassifier(
        n_estimators=estimators,
        random_state=seed,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=-1,
    )

    # 5. Train on all recordings.
    print("\n5. Training on the COMPLETE dataset...")
    print("   Please wait...")

    model.fit(X_train, y_train)

    print("\n   Training completed.")
    print(f"   Learned classes: {len(model.classes_)}")

    # 6. Save metadata.
    metadata = {
        "model_name": "Translate App First Experimental Model",
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
        "training_recordings": len(recordings),
        "participants": participants,
        "participant_count": len(participants),
        "classes": sorted(str(label) for label in model.classes_),
        "class_count": len(model.classes_),
        "recordings_per_class": dict(sorted(label_counts.items())),
        "single_recording_classes": singleton_labels,
        "evaluation_status": "NOT_INDEPENDENTLY_EVALUATED",
        "evaluation_note": (
            "All available recordings were used for training. "
            "Training performance is not a measure of generalization. "
            "Independent evaluation with new recordings and signers "
            "is required."
        ),
        "participant_independent_test": False,
        "validation_performed": False,
        "test_performed": False,
    }

    # 7. Save model.
    print("\n6. Saving model...")

    model_path, metadata_path = save_model(model, metadata)

    print(f"   Model: {model_path}")
    print(f"   Metadata: {metadata_path}")

    print("\n=== TRAINING COMPLETED ===")
    print(f"Training recordings: {len(recordings)}")
    print(f"Learned classes: {len(model.classes_)}")
    print("Model training: PASSED")
    print("Independent evaluation: NOT YET PERFORMED")

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the Translate App experimental model."
    )

    parser.add_argument(
        "--estimators",
        type=int,
        default=DEFAULT_ESTIMATORS,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=RANDOM_STATE,
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
        print(f"\nTraining failed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
