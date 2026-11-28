
"""Evaluate the trained gesture classifier on independent recordings.

Evaluation data must be stored separately from the training dataset.
The raw/source/nonedited directory is explicitly forbidden.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys

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

DEFAULT_EVALUATION_DIR = PROJECT_ROOT / "dataset" / "evaluation"

MODEL_FILENAME = "sign_classifier.pkl"
METADATA_FILENAME = "sign_classifier.metadata.json"
REPORT_FILENAME = "evaluation_report.json"


class EvaluationError(Exception):
    """Raised when independent model evaluation cannot be completed."""


def _check_evaluation_directory(directory: Path) -> None:
    """Prevent evaluation from using forbidden or training data."""

    resolved = directory.resolve()

    forbidden = (
        PROJECT_ROOT / "dataset" / "raw" / "source" / "nonedited"
    ).resolve()

    processed = (
        PROJECT_ROOT / "dataset" / "processed"
    ).resolve()

    try:
        resolved.relative_to(forbidden)
        raise EvaluationError(
            "Evaluation from dataset/raw/source/nonedited is forbidden."
        )
    except ValueError:
        pass

    if resolved == processed:
        raise EvaluationError(
            "The processed training dataset cannot be used "
            "for independent evaluation."
        )

    if not resolved.is_dir():
        raise EvaluationError(
            f"Evaluation directory does not exist: {resolved}"
        )


def _load_metadata(path: Path) -> dict[str, Any]:
    """Load model metadata."""

    if not path.is_file():
        raise EvaluationError(
            f"Model metadata not found: {path}. "
            "Train the model first."
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(
            f"Could not read model metadata: {error}"
        ) from error

    if not isinstance(metadata, dict):
        raise EvaluationError(
            "Model metadata must be a JSON object."
        )

    expected_features = (
        DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME
    )

    if metadata.get("sequence_length") != DEFAULT_SEQUENCE_LENGTH:
        raise EvaluationError(
            "Model sequence length does not match preprocessing."
        )

    if metadata.get("features_per_frame") != FEATURES_PER_FRAME:
        raise EvaluationError(
            "Model feature count does not match preprocessing."
        )

    if metadata.get("input_features") != expected_features:
        raise EvaluationError(
            "Model input feature count is incorrect."
        )

    if metadata.get("training_scope") != "all_available_recordings":
        raise EvaluationError(
            "Unexpected training scope in model metadata."
        )

    return metadata


def _load_model(path: Path) -> Any:
    """Load the trusted project model."""

    if not path.is_file():
        raise EvaluationError(
            f"Trained model not found: {path}. "
            "Run python -m ml.train first."
        )

    try:
        with path.open("rb") as file:
            model = pickle.load(file)
    except (OSError, pickle.UnpicklingError, EOFError) as error:
        raise EvaluationError(
            f"Could not load model: {error}"
        ) from error

    if not hasattr(model, "predict"):
        raise EvaluationError(
            "Loaded model does not provide predict()."
        )

    return model


def _prepare_features(
    recordings: list[Any],
) -> list[list[float]]:
    """Convert preprocessed recordings into model input vectors."""

    features = []

    expected_size = (
        DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME
    )

    for recording in recordings:
        if recording.sequence_length != DEFAULT_SEQUENCE_LENGTH:
            raise EvaluationError(
                f"Invalid sequence length in {recording.recording_id}."
            )

        if recording.feature_count != FEATURES_PER_FRAME:
            raise EvaluationError(
                f"Invalid feature count in {recording.recording_id}."
            )

        row = [
            value
            for frame in recording.sequence
            for value in frame
        ]

        if len(row) != expected_size:
            raise EvaluationError(
                f"Invalid input vector size in {recording.recording_id}."
            )

        features.append(row)

    return features


def evaluate_model(
    evaluation_dir: str | Path = DEFAULT_EVALUATION_DIR,
    model_path: str | Path = MODELS_DIR / MODEL_FILENAME,
    metadata_path: str | Path = MODELS_DIR / METADATA_FILENAME,
) -> dict[str, Any]:
    """Evaluate the model on independent recordings."""

    evaluation_dir = Path(evaluation_dir)
    model_path = Path(model_path)
    metadata_path = Path(metadata_path)

    print("\n=== TRANSLATE APP MODEL EVALUATION ===")

    # 1. Check evaluation data location.
    print("\n1. Checking evaluation directory...")

    _check_evaluation_directory(evaluation_dir)

    print(f"   Directory: {evaluation_dir.resolve()}")

    # 2. Load metadata and model.
    print("\n2. Loading model metadata...")

    metadata = _load_metadata(metadata_path)

    print("\n3. Loading trained model...")

    model = _load_model(model_path)

    if not hasattr(model, "classes_"):
        raise EvaluationError(
            "Model does not contain trained classes."
        )

    model_classes = {
        str(label) for label in model.classes_
    }

    metadata_classes = set(metadata.get("classes", []))

    if model_classes != metadata_classes:
        raise EvaluationError(
            "Model classes do not match metadata."
        )

    expected_features = metadata["input_features"]

    if getattr(model, "n_features_in_", None) != expected_features:
        raise EvaluationError(
            "Model input dimensions do not match metadata."
        )

    # 4. Load independent recordings.
    print("\n4. Loading independent evaluation recordings...")

    recordings = load_dataset(evaluation_dir)

    if not recordings:
        raise EvaluationError(
            "No evaluation recordings were found."
        )

    training_participants = set(
        metadata.get("participants", [])
    )

    evaluation_participants = {
        item.participant_id for item in recordings
    }

    overlapping_participants = (
        training_participants & evaluation_participants
    )

    if overlapping_participants:
        raise EvaluationError(
            "Participant leakage detected. These participants "
            "were already used for training: "
            + ", ".join(sorted(overlapping_participants))
        )

    training_recording_count = metadata.get("training_recordings")

    print(f"   Evaluation recordings: {len(recordings)}")
    print(f"   Evaluation participants: {len(evaluation_participants)}")
    print(f"   Training recordings: {training_recording_count}")

    # 5. Preprocess evaluation recordings.
    print("\n5. Preprocessing evaluation recordings...")

    processed = preprocess_dataset(recordings)

    X_test = _prepare_features(processed)
    y_true = [item.label for item in processed]

    # 6. Predict.
    print("\n6. Running predictions...")

    try:
        y_pred = model.predict(X_test)
    except (ValueError, TypeError) as error:
        raise EvaluationError(
            f"Prediction failed during evaluation: {error}"
        ) from error

    y_pred = [str(label) for label in y_pred]

    # 7. Calculate metrics.
    print("\n7. Calculating evaluation metrics...")

    try:
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
        )
    except ImportError as error:
        raise EvaluationError(
            "scikit-learn is required for evaluation."
        ) from error

    all_labels = sorted(set(y_true) | set(y_pred))

    accuracy = float(accuracy_score(y_true, y_pred))

    precision = float(
        precision_score(
            y_true,
            y_pred,
            labels=all_labels,
            average="macro",
            zero_division=0,
        )
    )

    recall = float(
        recall_score(
            y_true,
            y_pred,
            labels=all_labels,
            average="macro",
            zero_division=0,
        )
    )

    macro_f1 = float(
        f1_score(
            y_true,
            y_pred,
            labels=all_labels,
            average="macro",
            zero_division=0,
        )
    )

    report = classification_report(
        y_true,
        y_pred,
        labels=all_labels,
        zero_division=0,
        output_dict=True,
    )

    matrix = confusion_matrix(
        y_true,
        y_pred,
        labels=all_labels,
    )

    # Labels absent from the trained model cannot be recognized.
    unseen_labels = sorted(
        set(y_true) - model_classes
    )

    # 8. Build report.
    result = {
        "status": "completed",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "independent_participant_evaluation",
        "training_recordings": training_recording_count,
        "evaluation_recordings": len(recordings),
        "training_participants": sorted(training_participants),
        "evaluation_participants": sorted(evaluation_participants),
        "participant_overlap": False,
        "evaluation_classes": all_labels,
        "classes_not_seen_during_training": unseen_labels,
        "metrics": {
            "accuracy": accuracy,
            "macro_precision": precision,
            "macro_recall": recall,
            "macro_f1": macro_f1,
        },
        "classification_report": report,
        "confusion_matrix": {
            "labels": all_labels,
            "values": matrix.tolist(),
        },
        "warning": (
            "Evaluation results apply only to this independent "
            "evaluation dataset. They do not guarantee performance "
            "on all Bulgarian Sign Language users or gestures."
        ),
    }

    # 9. Save report.
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    report_path = MODELS_DIR / REPORT_FILENAME

    try:
        with report_path.open("w", encoding="utf-8") as file:
            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=4,
            )
    except OSError as error:
        raise EvaluationError(
            f"Could not save evaluation report: {error}"
        ) from error

    # 10. Print summary.
    print("\n=== EVALUATION RESULTS ===")
    print(f"   Accuracy:       {accuracy:.2%}")
    print(f"   Macro precision: {precision:.2%}")
    print(f"   Macro recall:    {recall:.2%}")
    print(f"   Macro F1:        {macro_f1:.2%}")

    print("\n   Classes not seen during training:")

    if unseen_labels:
        for label in unseen_labels:
            print(f"      {label}")
    else:
        print("      None")

    print(f"\n   Report saved: {report_path}")

    print("\nEvaluation completed: PASSED")

    return result


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the trained model on independent recordings."
        )
    )

    parser.add_argument(
        "evaluation_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_EVALUATION_DIR,
        help="Directory containing independent landmarks JSONL files.",
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=MODELS_DIR / MODEL_FILENAME,
        help="Path to the trained model.",
    )

    parser.add_argument(
        "--metadata",
        type=Path,
        default=MODELS_DIR / METADATA_FILENAME,
        help="Path to model metadata.",
    )

    args = parser.parse_args()

    try:
        evaluate_model(
            evaluation_dir=args.evaluation_dir,
            model_path=args.model,
            metadata_path=args.metadata,
        )

    except (
        DatasetError,
        PreprocessingError,
        EvaluationError,
    ) as error:
        print(f"\nEvaluation could not be completed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
