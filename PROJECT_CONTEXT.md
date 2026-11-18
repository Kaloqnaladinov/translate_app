# Translate App — AI Project Context

## Goal
Build a practical communication tool between Deaf/hard-of-hearing people and hearing people, focused on Bulgarian Sign Language (Български жестов език, БЖЕ).

## Product directions
1. Camera → sign recognition → Bulgarian text (speech output may follow).
2. Typed/spoken Bulgarian → corresponding sign presentation through an animated character.

This is an MVP, not a claim of full real-time sign-language translation.

## MVP scope
- Bulgarian alphabet fingerspelling (30 letters), using validated sign references.
- A small starter dictionary of 5 validated words/phrases.
- User can enter a name and see it spelled letter by letter.
- Dataset recording and management foundations.
- Recognition comes after collecting and validating enough recordings.

Do not invent signs. БЖЕ is a full natural language; fingerspelling is not a replacement for sign language. Sign descriptions and labels must be checked with competent БЖЕ users.

## Planned architecture
- Frontend: HTML, CSS, vanilla JavaScript.
- Camera capture: browser MediaDevices + MediaRecorder.
- Backend: Python + FastAPI.
- Raw recordings: dataset/raw/, preserving original video and metadata.
- Landmark extraction: MediaPipe-based pipeline, producing derived data under dataset/processed/.
- ML: Python pipeline under ml/ for preprocessing, dataset loading, training, evaluation and prediction.
- Model artifacts: dataset/models/.
- Future avatar: reusable character with separate animation clips for letters and validated signs.

## Target project structure
    translate_app/
    ├── index.html
    ├── kamera.html
    ├── tekst.html
    ├── dataset.html
    ├── assets/
    │   ├── images/
    │   ├── avatars/
    │   ├── models/
    │   ├── letters/animations/
    │   └── words/animations/
    ├── css/
    │   ├── style.css
    │   └── animation.css
    ├── js/
    │   ├── app.js
    │   ├── recorder.js
    │   ├── dataset.js
    │   ├── landmarks.js
    │   └── spelling.js
    ├── data/
    │   ├── signs.json
    │   └── labels.json
    ├── backend/
    │   ├── main.py
    │   ├── recorder.py
    │   ├── dataset_manager.py
    │   └── extraction.py
    ├── ml/
    │   ├── preprocess.py
    │   ├── dataset.py
    │   ├── train.py
    │   ├── evaluate.py
    │   └── predict.py
    └── dataset/
        ├── raw/
        ├── processed/
        └── models/

## Data principles
- Preserve raw videos. Never overwrite or discard originals during preprocessing.
- Every recording must have a label and pseudonymous participant/session IDs.
- Record consent status; do not collect real names unless strictly necessary.
- Keep metadata with each sample (label, participant, session, timestamp, format, dimensions, fps where available).
- Split train/validation/test by participant or recording session, not random clips from the same signer, to reduce data leakage.
- Do not train or report accuracy before there are enough correctly labelled and reviewed samples.
- Treat landmark files as derived data; version the extraction method.

## Engineering rules
- Inspect the current file and its imports/callers before changing it.
- Make the smallest coherent change. Do not rewrite unrelated UI or files.
- Preserve the existing visual design unless the task explicitly concerns design.
- Use relative paths that work from the project root.
- Do not add dependencies without explaining why and giving the exact install command.
- Do not fabricate API behavior, sample data, signs, model accuracy or test results.
- Keep functions focused and add clear error handling.
- If a requirement is unclear, ask one specific question rather than guessing.
- After changes, provide: files changed, what changed, how to run/test, expected result, and any limitations.
- Do not output the entire project. Return only complete contents of the files explicitly requested for the current task.

## Current working method with AI
Work one folder at a time. The repository is the shared reference. For each task, provide the AI with:
1. This file: PROJECT_CONTEXT.md.
2. The exact target file(s) and any directly imported/calling file(s).
3. A short task instruction.

Before proposing a code change, inspect the latest repository version. Never assume local and GitHub files are identical; check the current branch and commit.
