
"""Predict a sign-language gesture from a landmarks JSONL recording."""

from __future__ import annotations

import argparse
import json
import pickle
import sys

from pathlib import Path
from typing import Any

from ml.dataset import DatasetError, load_recording
from ml.preprocess import (
    DEFAULT_SEQUENCE_LENGTH,
    FEATURES_PER_FRAME,
    PreprocessingError,
    preprocess_recording,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "dataset" / "models"

MODEL_FILENAME = "sign_classifier.pkl"
METADATA_FILENAME = "sign_classifier.metadata.json"

DEFAULT_TOP_K = 3


class PredictionError(Exception):
    """Raised when gesture prediction cannot be completed."""


def _load_metadata(metadata_path: Path) -> dict[str, Any]:
    """Load and validate model metadata."""

    if not metadata_path.is_file():
        raise PredictionError(
            f"Model metadata not found: {metadata_path}"
        )

    try:
        with metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)

    except (OSError, json.JSONDecodeError) as error:
        raise PredictionError(
            f"Could not read model metadata: {error}"
        ) from error

    if not isinstance(metadata, dict):
        raise PredictionError(
            "Model metadata must contain a JSON object."
        )

    expected_features = DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME

    if metadata.get("sequence_length") != DEFAULT_SEQUENCE_LENGTH:
        raise PredictionError(
            "Model sequence length does not match preprocessing."
        )

    if metadata.get("features_per_frame") != FEATURES_PER_FRAME:
        raise PredictionError(
            "Model feature count per frame does not match preprocessing."
        )

    if metadata.get("input_features") != expected_features:
        raise PredictionError(
            "Model total input feature count is incorrect."
        )

    classes = metadata.get("classes")

    if (
        not isinstance(classes, list)
        or not classes
        or not all(isinstance(item, str) and item for item in classes)
    ):
        raise PredictionError(
            "Model metadata contains an invalid class list."
        )

    return metadata


def _load_model(model_path: Path) -> Any:
    """Load the trained classifier."""

    if not model_path.is_file():
        raise PredictionError(
            f"Trained model not found: {model_path}. "
            "Run python -m ml.train first."
        )

    try:
        # Only load pickle files created by this trusted project.
        with model_path.open("rb") as file:
            model = pickle.load(file)

    except (OSError, pickle.UnpicklingError, EOFError) as error:
        raise PredictionError(
            f"Could not load trained model: {error}"
        ) from error

    if not hasattr(model, "predict"):
        raise PredictionError(
            "Loaded model does not provide predict()."
        )

    if not hasattr(model, "predict_proba"):
        raise PredictionError(
            "Loaded model does not provide predict_proba()."
        )

    return model


def _flatten_recording(recording: Any) -> list[float]:
    """Convert one preprocessed recording into model input."""

    if recording.sequence_length != DEFAULT_SEQUENCE_LENGTH:
        raise PredictionError(
            "Preprocessed recording has an invalid sequence length."
        )

    if recording.feature_count != FEATURES_PER_FRAME:
        raise PredictionError(
            "Preprocessed recording has an invalid feature count."
        )

    features = [
        value
        for frame in recording.sequence
        for value in frame
    ]

    expected_size = DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME

    if len(features) != expected_size:
        raise PredictionError(
            f"Expected {expected_size} input features, "
            f"received {len(features)}."
        )

    return features


def predict_recording(
    landmarks_path: str | Path,
    model_path: str | Path = MODELS_DIR / MODEL_FILENAME,
    metadata_path: str | Path = MODELS_DIR / METADATA_FILENAME,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """
    Predict the gesture represented by one landmarks JSONL recording.

    The recording must use the same landmark schema and preprocessing
    configuration as the training dataset.
    """

    if top_k < 1:
        raise PredictionError(
            "top_k must be at least 1."
        )

    landmarks_path = Path(landmarks_path).resolve()
    model_path = Path(model_path).resolve()
    metadata_path = Path(metadata_path).resolve()

    forbidden_dir = (
        PROJECT_ROOT / "dataset" / "raw" / "source" / "nonedited"
    ).resolve()

    try:
      landmarks_path.relative_to(forbidden_dir)
    except ValueError:
     pass
    else:
      raise PredictionError(
        "Prediction from dataset/raw/source/nonedited is forbidden."
    )

    print("\n=== TRANSLATE APP GESTURE PREDICTION ===")

    # 1. Load metadata.
    print("\n1. Loading model metadata...")

    metadata = _load_metadata(metadata_path)

    # 2. Load trained model.
    print("\n2. Loading trained model...")

    model = _load_model(model_path)

    model_classes = sorted(str(label) for label in model.classes_)
    metadata_classes = sorted(metadata["classes"])

    if model_classes != metadata_classes:
        raise PredictionError(
            "Model classes do not match the saved metadata."
        )

    expected_features = metadata["input_features"]

    if getattr(model, "n_features_in_", None) != expected_features:
        raise PredictionError(
            "Model input dimensions do not match metadata."
        )

    # 3. Load and validate the new recording.
    print("\n3. Loading landmarks recording...")

    recording = load_recording(landmarks_path)

    print(f"   Recording ID: {recording.recording_id}")
    print(f"   Frames:       {recording.frame_count}")

    # 4. Apply exactly the same preprocessing as training.
    print("\n4. Preprocessing recording...")

    processed = preprocess_recording(recording)

    features = _flatten_recording(processed)

    print(f"   Sequence length: {processed.sequence_length}")
    print(f"   Features:        {len(features)}")
    print(f"   Detection ratio: {processed.detection_ratio:.1%}")

    # 5. Predict.
    print("\n5. Predicting gesture...")

    try:
        probabilities = model.predict_proba([features])[0]
    except (ValueError, TypeError) as error:
        raise PredictionError(
            f"Model prediction failed: {error}"
        ) from error

    classes = list(model.classes_)

    if len(classes) != len(probabilities):
        raise PredictionError(
            "Prediction probabilities do not match model classes."
        )

    ranked = sorted(
        zip(classes, probabilities),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    best_label, best_probability = ranked[0]

    results = [
        {
            "label": str(label),
            "probability": float(probability),
        }
        for label, probability in ranked[:min(top_k, len(ranked))]
    ]

    # 6. Return structured result.
    result = {
        "status": "success",
        "recording_id": recording.recording_id,
        "predicted_label": str(best_label),
        "confidence": float(best_probability),
        "top_predictions": results,
        "frames": recording.frame_count,
        "detection_ratio": processed.detection_ratio,
        "model_type": metadata.get("model_type"),
        "model_created_at": metadata.get("created_at"),
        "evaluation_status": metadata.get("evaluation_status"),
        "warning": (
            "Experimental prediction. Probability is not a guarantee "
            "that the gesture was recognized correctly."
        ),
    }

    print("\n=== PREDICTION RESULT ===")
    print(f"   Predicted gesture: {result['predicted_label']}")
    print(f"   Probability:       {result['confidence']:.2%}")

    print("\n   Top predictions:")

    for index, item in enumerate(results, start=1):
        print(
            f"      {index}. {item['label']}: "
            f"{item['probability']:.2%}"
        )

    print("\nPrediction completed: PASSED")

    return result


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Predict a gesture from an extracted landmarks JSONL file."
        )
    )

    parser.add_argument(
        "landmarks",
        type=Path,
        help="Path to the input .landmarks.jsonl recording.",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of alternative predictions (default: 3).",
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
        help="Path to the model metadata JSON.",
    )

    args = parser.parse_args()

    try:
        result = predict_recording(
            landmarks_path=args.landmarks,
            model_path=args.model,
            metadata_path=args.metadata,
            top_k=args.top_k,
        )

        print("\nJSON RESULT:")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=4,
            )
        )

    except (
        DatasetError,
        PreprocessingError,
        PredictionError,
    ) as error:
        print(f"\nPrediction could not be completed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
