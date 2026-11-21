
"""Train and save a sign-language gesture classification model."""

from __future__ import annotations

import argparse
import json
import pickle
import sys

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.dataset import (
    DatasetError,
    DEFAULT_DATASET_DIR,
    load_dataset,
    split_by_participant,
)
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
    """Flatten a complete temporal sequence into one feature vector."""

    if recording.sequence_length != DEFAULT_SEQUENCE_LENGTH:
        raise TrainingError(
            f"Recording {recording.recording_id} has an invalid "
            f"sequence length: {recording.sequence_length}."
        )

    if recording.feature_count != FEATURES_PER_FRAME:
        raise TrainingError(
            f"Recording {recording.recording_id} has an invalid "
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
    """Convert preprocessed recordings into model input and labels."""

    features = []
    labels = []

    for recording in recordings:
        features.append(_flatten_recording(recording))
        labels.append(recording.label)

    if not features:
        raise TrainingError("No training recordings are available.")

    expected_size = DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME

    if any(len(row) != expected_size for row in features):
        raise TrainingError(
            f"Every input must contain exactly {expected_size} values."
        )

    return features, labels


def _validate_split(split: Any, all_labels: set[str]) -> None:
    """Ensure every gesture class is represented in every split."""

    if not split.train:
        raise TrainingError("The training split is empty.")

    if not split.validation:
        raise TrainingError("The validation split is empty.")

    if not split.test:
        raise TrainingError("The test split is empty.")

    for split_name, samples in (
        ("training", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        available_labels = {sample.label for sample in samples}
        missing_labels = sorted(all_labels - available_labels)

        if missing_labels:
            raise TrainingError(
                f"The {split_name} split is missing gesture classes: "
                f"{', '.join(missing_labels)}. "
                "Collect recordings of every gesture from more participants."
            )

    training_counts = Counter(
        sample.label for sample in split.train
    )

    insufficient = {
        label: count
        for label, count in training_counts.items()
        if count < 2
    }

    if insufficient:
        details = ", ".join(
            f"{label}: {count}"
            for label, count in sorted(insufficient.items())
        )

        raise TrainingError(
            "At least 2 training recordings per gesture are required. "
            f"Insufficient classes: {details}."
        )


def _save_model(
    model: Any,
    metadata: dict[str, Any],
) -> tuple[Path, Path]:
    """Save the trained model and metadata using temporary files."""

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODELS_DIR / MODEL_FILENAME
    metadata_path = MODELS_DIR / METADATA_FILENAME

    temporary_model = model_path.with_suffix(".pkl.tmp")
    temporary_metadata = metadata_path.with_suffix(".json.tmp")

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
            f"Could not save the trained model: {error}"
        ) from error

    return model_path, metadata_path


def train_model(
    estimators: int = DEFAULT_ESTIMATORS,
    seed: int = RANDOM_STATE,
) -> dict[str, Any]:
    """Load, split, train, validate and save the classifier."""

    if estimators < 10:
        raise TrainingError(
            "The number of estimators must be at least 10."
        )

    print("\n=== TRANSLATE APP MODEL TRAINING ===")

    print("\n1. Loading dataset...")

    recordings = load_dataset()

    print(f"   Loaded recordings: {len(recordings)}")
    print(
        "   Participants: "
        f"{len({item.participant_id for item in recordings})}"
    )

    all_labels = {item.label for item in recordings}

    if len(all_labels) < 2:
        raise TrainingError(
            "At least 2 different gesture classes are required "
            "to train a classifier."
        )

    print(f"   Gesture classes: {len(all_labels)}")

    print("\n2. Splitting by participant...")

    split = split_by_participant(
        recordings,
        seed=seed,
    )

    _validate_split(split, all_labels)

    print(f"   Training recordings:   {len(split.train)}")
    print(f"   Validation recordings: {len(split.validation)}")
    print(f"   Test recordings:       {len(split.test)}")

    print("\n3. Preprocessing recordings...")

    train_data = preprocess_dataset(split.train)
    validation_data = preprocess_dataset(split.validation)

    X_train, y_train = _prepare_data(train_data)
    X_validation, y_validation = _prepare_data(validation_data)

    print(f"   Features per recording: {len(X_train[0])}")
    print(f"   Training samples:       {len(X_train)}")
    print(f"   Validation samples:     {len(X_validation)}")

    print("\n4. Initializing classifier...")

    try:
        import sklearn
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, f1_score
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

    print("\n5. Training model...")

    model.fit(X_train, y_train)

    print("\n6. Evaluating on validation data...")

    predictions = model.predict(X_validation)

    validation_accuracy = float(
        accuracy_score(y_validation, predictions)
    )

    validation_f1 = float(
        f1_score(
            y_validation,
            predictions,
            average="macro",
            zero_division=0,
        )
    )

    print(f"   Validation accuracy: {validation_accuracy:.4f}")
    print(f"   Validation macro F1: {validation_f1:.4f}")

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
        "classes": sorted(str(label) for label in model.classes_),
        "training_recordings": len(split.train),
        "validation_recordings": len(split.validation),
        "reserved_test_recordings": len(split.test),
        "validation_accuracy": validation_accuracy,
        "validation_macro_f1": validation_f1,
        "participant_split": {
            "train": sorted({
                item.participant_id for item in split.train
            }),
            "validation": sorted({
                item.participant_id for item in split.validation
            }),
            "test": sorted({
                item.participant_id for item in split.test
            }),
        },
    }

    print("\n7. Saving model...")

    model_path, metadata_path = _save_model(model, metadata)

    print(f"   Model:    {model_path}")
    print(f"   Metadata: {metadata_path}")

    print("\n=== TRAINING COMPLETED ===")
    print("Model training: PASSED")

    return metadata


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description="Train the Translate App gesture classifier."
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

    except (DatasetError, PreprocessingError, TrainingError) as error:
        print(f"\nTraining could not be completed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
