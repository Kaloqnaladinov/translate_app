
"""Predict a sign label from an extracted landmark recording."""

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

MODEL_PATH = MODELS_DIR / "sign_classifier.pkl"
METADATA_PATH = MODELS_DIR / "sign_classifier.metadata.json"


class PredictionError(Exception):
    """Raised when a prediction cannot be completed."""


def load_model() -> tuple[Any, dict[str, Any]]:
    """Load the trained classifier and its metadata."""

    if not MODEL_PATH.is_file():
        raise PredictionError(
            f"Model not found: {MODEL_PATH}\n"
            "Train the model first using: python -m ml.train"
        )

    if not METADATA_PATH.is_file():
        raise PredictionError(
            f"Model metadata not found: {METADATA_PATH}"
        )

    try:
        with METADATA_PATH.open("r", encoding="utf-8") as file:
            metadata = json.load(file)

        with MODEL_PATH.open("rb") as file:
            model = pickle.load(file)

    except (OSError, json.JSONDecodeError, pickle.UnpicklingError) as error:
        raise PredictionError(
            f"Could not load the trained model: {error}"
        ) from error

    if not isinstance(metadata, dict):
        raise PredictionError("Model metadata must be a JSON object.")

    expected_features = (
        DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME
    )

    if metadata.get("sequence_length") != DEFAULT_SEQUENCE_LENGTH:
        raise PredictionError(
            "Model sequence length does not match preprocessing."
        )

    if metadata.get("features_per_frame") != FEATURES_PER_FRAME:
        raise PredictionError(
            "Model feature count does not match preprocessing."
        )

    if metadata.get("input_features") != expected_features:
        raise PredictionError(
            "Model input feature count is invalid."
        )

    if not hasattr(model, "predict_proba"):
        raise PredictionError(
            "Loaded model does not support probability predictions."
        )

    if not hasattr(model, "n_features_in_"):
        raise PredictionError(
            "Loaded model does not expose its input feature count."
        )

    if model.n_features_in_ != expected_features:
        raise PredictionError(
            "Loaded model expects a different number of features."
        )

    return model, metadata


def predict_recording(
    recording_path: str | Path,
    top_k: int = 5,
) -> dict[str, Any]:
    """Predict the most likely gesture classes for one recording."""

    if top_k < 1:
        raise PredictionError("top_k must be at least 1.")

    path = Path(recording_path)

    if not path.is_file():
        raise PredictionError(
            f"Recording file does not exist: {path}"
        )

    if path.suffix.lower() != ".jsonl":
        raise PredictionError(
            "Expected an extracted .landmarks.jsonl recording."
        )

    print("1. Loading trained model...")

    model, metadata = load_model()

    print("2. Loading landmark recording...")

    recording = load_recording(path)

    print(f"   Recording: {path.name}")
    print(f"   Frames: {recording.frame_count}")

    print("3. Preprocessing recording...")

    processed = preprocess_recording(recording)

    features = [
        value
        for frame in processed.sequence
        for value in frame
    ]

    expected_features = (
        DEFAULT_SEQUENCE_LENGTH * FEATURES_PER_FRAME
    )

    if len(features) != expected_features:
        raise PredictionError(
            f"Expected {expected_features} features, "
            f"received {len(features)}."
        )

    print("4. Predicting gesture...")

    probabilities = model.predict_proba([features])[0]
    classes = model.classes_

    if len(probabilities) != len(classes):
        raise PredictionError(
            "Model returned an invalid probability result."
        )

    ranked = sorted(
        zip(classes, probabilities),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    results = [
        {
            "label": str(label),
            "probability": float(probability),
        }
        for label, probability in ranked[:top_k]
    ]

    if not results:
        raise PredictionError(
            "The model returned no predictions."
        )

    result = {
        "recording": path.name,
        "recording_id": recording.recording_id,
        "frame_count": recording.frame_count,
        "participant_id": recording.participant_id,
        "predicted_label": results[0]["label"],
        "top_predictions": results,
        "model_name": metadata.get("model_name", "Unknown"),
        "evaluation_status": metadata.get(
            "evaluation_status",
            "UNKNOWN",
        ),
        "independently_evaluated": (
            metadata.get("evaluation_status")
            == "INDEPENDENTLY_EVALUATED"
        ),
        "warning": (
            "Prediction probabilities are model scores, not "
            "validated confidence values. The model has not been "
            "independently evaluated."
        ),
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Predict a gesture from an extracted landmark JSONL file."
        )
    )

    parser.add_argument(
        "recording",
        type=Path,
        help="Path to a .landmarks.jsonl recording.",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of highest-scoring predictions (default: 5).",
    )

    args = parser.parse_args()

    try:
        result = predict_recording(
            args.recording,
            top_k=args.top_k,
        )

        print("\n=== TRANSLATE APP PREDICTION ===")
        print(f"Predicted gesture: {result['predicted_label']}")

        print("\nTop predictions:")

        for index, item in enumerate(
            result["top_predictions"],
            start=1,
        ):
            percentage = item["probability"] * 100

            print(
                f"  {index}. {item['label']}: "
                f"{percentage:.2f}%"
            )

        print(
            "\nIndependent evaluation: "
            f"{'PASSED' if result['independently_evaluated'] else 'NOT PERFORMED'}"
        )

        print(f"\nWarning: {result['warning']}")

        print("\nPrediction validation: PASSED")

    except (
        DatasetError,
        PreprocessingError,
        PredictionError,
    ) as error:
        print(f"\nPrediction failed:\n{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
