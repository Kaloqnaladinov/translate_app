
"""
Independent dataset and label audit for Translate App.

- Does not modify dataset files.
- Does not import project modules.
- Uses only Python standard library.
- Checks labels, participants, landmarks and split feasibility.
"""

from __future__ import annotations

import argparse
import json
import math
import re

from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = PROJECT_ROOT / "dataset" / "processed"

EXPECTED_POINTS = {
    "pose": 33,
    "left_hand": 21,
    "right_hand": 21,
}

# Heuristic thresholds: warnings, not automatic proof of bad data.
MIN_FRAMES = 10
MIN_LANDMARK_FRAME_RATIO = 0.80
MIN_HAND_FRAME_RATIO = 0.25
MIN_PARTICIPANTS_PER_LABEL = 2
MIN_RECORDINGS_PER_LABEL = 3


def normalize_label(value):
    """Normalize label for grouping and comparison."""
    value = str(value).strip().casefold()
    value = re.sub(r"[_\s]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def inspect_recording(path):
    """Inspect one JSONL recording without changing it."""

    result = {
        "file": path.name,
        "status": "OK",
        "errors": [],
        "warnings": [],
        "label": None,
        "category": None,
        "participant": None,
        "recording_id": None,
        "frames": 0,
        "landmark_frames": 0,
        "hand_frames": 0,
        "pose_frames": 0,
    }

    try:
        records = []

        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    result["errors"].append(
                        f"Invalid JSON at line {line_number}: {error.msg}"
                    )
                    continue

                if not isinstance(record, dict):
                    result["errors"].append(
                        f"Line {line_number} is not a JSON object."
                    )
                    continue

                records.append(record)

        if not records:
            result["errors"].append("Empty JSONL file.")
            result["status"] = "INVALID"
            return result

        metadata_records = [
            item for item in records
            if item.get("record_type") == "metadata"
        ]

        if len(metadata_records) != 1:
            result["errors"].append(
                f"Expected exactly one metadata record; "
                f"found {len(metadata_records)}."
            )
        else:
            metadata = metadata_records[0]

            result["label"] = metadata.get("label")
            result["category"] = metadata.get("category")
            result["participant"] = metadata.get("participant_id")
            result["recording_id"] = metadata.get("recording_id")

            required = (
                "label",
                "participant_id",
                "recording_id",
                "source_filename",
                "fps",
            )

            for field in required:
                value = metadata.get(field)

                if value is None or value == "":
                    result["errors"].append(
                        f"Missing metadata field: {field}"
                    )

            if metadata.get("schema_version") != "1.1":
                result["errors"].append(
                    "Unsupported or missing schema_version."
                )

            if metadata.get("category") not in ("letters", "words"):
                result["errors"].append("Invalid category.")

            if (
                not finite_number(metadata.get("fps"))
                or metadata["fps"] <= 0
            ):
                result["errors"].append("Invalid FPS.")

        frames = [
            item for item in records
            if item.get("record_type") == "frame"
        ]

        result["frames"] = len(frames)

        if not frames:
            result["errors"].append("No frame records.")

        previous_index = -1

        for frame_number, frame in enumerate(frames, start=1):
            index = frame.get("frame_index")

            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
            ):
                result["errors"].append(
                    f"Invalid frame_index at frame {frame_number}."
                )
            elif index <= previous_index:
                result["errors"].append(
                    f"Frame indexes are not strictly increasing "
                    f"at frame {frame_number}."
                )

            if isinstance(index, int) and not isinstance(index, bool):
                previous_index = index

            timestamp = frame.get("timestamp_ms")

            if not finite_number(timestamp) or timestamp < 0:
                result["errors"].append(
                    f"Invalid timestamp at frame {frame_number}."
                )

            has_any = False
            has_hand = False
            has_pose = False

            for name, expected_count in EXPECTED_POINTS.items():
                points = frame.get(name)

                if points is None:
                    continue

                if not isinstance(points, list):
                    result["errors"].append(
                        f"Frame {frame_number}: {name} is not a list."
                    )
                    continue

                if len(points) != expected_count:
                    result["errors"].append(
                        f"Frame {frame_number}: {name} has "
                        f"{len(points)} points, expected {expected_count}."
                    )
                    continue

                valid_points = True

                for point in points:
                    if not isinstance(point, dict):
                        valid_points = False
                        break

                    for coordinate in ("x", "y", "z"):
                        if not finite_number(point.get(coordinate)):
                            valid_points = False
                            break

                    if not valid_points:
                        break

                if not valid_points:
                    result["errors"].append(
                        f"Frame {frame_number}: invalid coordinates "
                        f"in {name}."
                    )
                    continue

                has_any = True

                if name == "pose":
                    has_pose = True

                if name in ("left_hand", "right_hand"):
                    has_hand = True

            if has_any:
                result["landmark_frames"] += 1

            if has_hand:
                result["hand_frames"] += 1

            if has_pose:
                result["pose_frames"] += 1

        if result["frames"] < MIN_FRAMES:
            result["warnings"].append(
                f"Very short recording: {result['frames']} frames."
            )

        if result["frames"]:
            landmark_ratio = (
                result["landmark_frames"] / result["frames"]
            )
            hand_ratio = (
                result["hand_frames"] / result["frames"]
            )

            if landmark_ratio < MIN_LANDMARK_FRAME_RATIO:
                result["warnings"].append(
                    f"Low landmark coverage: "
                    f"{landmark_ratio:.1%}."
                )

            if hand_ratio == 0:
                result["warnings"].append(
                    "No hand landmarks detected in any frame."
                )
            elif hand_ratio < MIN_HAND_FRAME_RATIO:
                result["warnings"].append(
                    f"Low hand detection: {hand_ratio:.1%} "
                    f"of frames."
                )

        if result["errors"]:
            result["status"] = "INVALID"
        elif result["warnings"]:
            result["status"] = "REVIEW"

    except Exception as error:
        result["errors"].append(str(error))
        result["status"] = "INVALID"

    return result


def print_section(title):
    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(
        description="Independent Translate App dataset audit."
    )

    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Directory containing .landmarks.jsonl files.",
    )

    args = parser.parse_args()
    dataset_dir = args.dataset_dir.resolve()

    if not dataset_dir.is_dir():
        raise SystemExit(
            f"Dataset directory does not exist: {dataset_dir}"
        )

    files = sorted(dataset_dir.glob("*.landmarks.jsonl"))

    if not files:
        raise SystemExit(
            f"No JSONL files found in: {dataset_dir}"
        )

    print("TRANSLATE APP - INDEPENDENT LABEL AUDIT")
    print(f"Dataset: {dataset_dir}")
    print(f"Files found: {len(files)}")

    results = [inspect_recording(path) for path in files]

    valid = [r for r in results if r["status"] == "OK"]
    review = [r for r in results if r["status"] == "REVIEW"]
    invalid = [r for r in results if r["status"] == "INVALID"]

    # Duplicate recording IDs
    id_files = defaultdict(list)

    for item in results:
        if item["recording_id"]:
            id_files[item["recording_id"]].append(item["file"])

    duplicate_ids = {
        key: value for key, value in id_files.items()
        if len(value) > 1
    }

    # Use only structurally valid recordings for label statistics.
    usable = [r for r in results if r["status"] != "INVALID"]

    label_recordings = defaultdict(list)
    participant_recordings = Counter()
    category_counts = Counter()

    for item in usable:
        label = normalize_label(item["label"])

        if not label:
            continue

        label_recordings[label].append(item)
        participant_recordings[item["participant"]] += 1
        category_counts[item["category"]] += 1

    print_section("1. RECORDING QUALITY")

    print(f"Total files: {len(results)}")
    print(f"OK: {len(valid)}")
    print(f"REVIEW: {len(review)}")
    print(f"INVALID: {len(invalid)}")
    print(f"Duplicate recording IDs: {len(duplicate_ids)}")

    for item in results:
        if item["status"] != "OK":
            print(f"\n[{item['status']}] {item['file']}")

            for warning in item["warnings"]:
                print(f"  WARNING: {warning}")

            for error in item["errors"]:
                print(f"  ERROR: {error}")

    if duplicate_ids:
        print("\nDUPLICATE IDs:")
        for recording_id, names in duplicate_ids.items():
            print(f"  {recording_id}: {', '.join(names)}")

    print_section("2. LABEL DISTRIBUTION")

    print(f"Unique labels: {len(label_recordings)}")
    print(f"Categories: {dict(category_counts)}")

    print(
        f"\n{'LABEL':25} {'RECORDINGS':>11} "
        f"{'PARTICIPANTS':>13} {'STATUS':>12}"
    )

    for label, items in sorted(label_recordings.items()):
        recordings = len(items)
        participants = len({
            item["participant"] for item in items
        })

        problems = []

        if recordings < MIN_RECORDINGS_PER_LABEL:
            problems.append("FEW RECORDINGS")

        if participants < MIN_PARTICIPANTS_PER_LABEL:
            problems.append("FEW PARTICIPANTS")

        status = ", ".join(problems) if problems else "OK"

        print(
            f"{label[:25]:25} {recordings:>11} "
            f"{participants:>13} {status:>12}"
        )

    print_section("3. PARTICIPANT COVERAGE PER LABEL")

    all_participants = sorted({
        item["participant"]
        for item in usable
        if item["participant"]
    })

    print("Participants:", ", ".join(all_participants))

    for label, items in sorted(label_recordings.items()):
        counts = Counter(item["participant"] for item in items)

        details = ", ".join(
            f"{participant}: {counts.get(participant, 0)}"
            for participant in all_participants
        )

        print(f"{label}: {details}")

    print_section("4. LABELS WITH INSUFFICIENT DATA")

    few_recordings = []
    few_participants = []

    for label, items in sorted(label_recordings.items()):
        if len(items) < MIN_RECORDINGS_PER_LABEL:
            few_recordings.append(label)

        count = len({
            item["participant"] for item in items
        })

        if count < MIN_PARTICIPANTS_PER_LABEL:
            few_participants.append(label)

    print(
        f"Labels with fewer than {MIN_RECORDINGS_PER_LABEL} "
        f"recordings: {len(few_recordings)}"
    )

    for label in few_recordings:
        print(f"  - {label}")

    print(
        f"\nLabels with fewer than {MIN_PARTICIPANTS_PER_LABEL} "
        f"participants: {len(few_participants)}"
    )

    for label in few_participants:
        print(f"  - {label}")

    print_section("5. PARTICIPANT-INDEPENDENT SPLIT")

    print(
        "A label is covered by a split only if at least one "
        "recording exists from a participant assigned to it."
    )

    participant_label_sets = {}

    for participant in all_participants:
        participant_label_sets[participant] = {
            label
            for label, items in label_recordings.items()
            if any(
                item["participant"] == participant
                for item in items
            )
        }

    all_labels = set(label_recordings)

    if len(all_participants) < 3:
        print(
            "NOT POSSIBLE: fewer than 3 participants. "
            "Cannot create three non-empty independent splits."
        )
    else:
        print(
            "Testing all assignments with one or more participants "
            "in each split..."
        )

        # For current 3 participants this tests all possible
        # train / validation / test assignments.
        from itertools import product

        best = None
        best_score = -1

        for assignments in product(
            ("train", "validation", "test"),
            repeat=len(all_participants),
        ):
            groups = {
                "train": set(),
                "validation": set(),
                "test": set(),
            }

            for participant, group in zip(
                all_participants, assignments
            ):
                groups[group].add(participant)

            if any(not group for group in groups.values()):
                continue

            covered = {}

            for group_name, participants in groups.items():
                covered[group_name] = set().union(
                    *(
                        participant_label_sets[p]
                        for p in participants
                    )
                )

            common = set.intersection(
                *(covered[name] for name in groups)
            )

            score = len(common)

            if score > best_score:
                best_score = score
                best = (groups, covered, common)

        if best:
            groups, covered, common = best

            for name in ("train", "validation", "test"):
                print(
                    f"\n{name.upper()}: "
                    f"{', '.join(sorted(groups[name]))}"
                )
                print(
                    f"  Covered labels: "
                    f"{len(covered[name])}/{len(all_labels)}"
                )
                missing = sorted(all_labels - covered[name])

                if missing:
                    print("  Missing:", ", ".join(missing))

            print(
                f"\nLabels present in ALL three splits: "
                f"{len(common)}/{len(all_labels)}"
            )

            missing_common = sorted(all_labels - common)

            if missing_common:
                print("Labels not evaluable in all splits:")
                for label in missing_common:
                    print(f"  - {label}")
            else:
                print(
                    "All labels are represented in all three splits."
                )

            if len(common) == len(all_labels):
                print("\nSPLIT COVERAGE: PASSED")
            else:
                print("\nSPLIT COVERAGE: INCOMPLETE")

    print_section("6. FINAL RESULT")

    print(f"Usable recordings: {len(usable)}")
    print(f"Invalid recordings: {len(invalid)}")
    print(f"Labels: {len(label_recordings)}")
    print(f"Participants: {len(all_participants)}")

    if invalid or duplicate_ids:
        print("DATASET AUDIT: FAILED")
    elif review:
        print("DATASET AUDIT: PASSED WITH WARNINGS")
    else:
        print("DATASET AUDIT: PASSED")

    print(
        "\nIMPORTANT: This script checks file integrity and "
        "statistical coverage. It cannot determine whether a "
        "gesture was performed correctly. Manual visual review "
        "and validation by competent BSL/BGSL users are still needed."
    )


if __name__ == "__main__":
    main()
