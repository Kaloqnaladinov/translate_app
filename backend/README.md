# Backend — local development

## 1. Create and activate a virtual environment

Python 3.12 is recommended.

Linux / Codespaces:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Start the API

Run this command from the repository root:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## 3. Check the API

- Health: `http://localhost:8000/health`
- Interactive API docs: `http://localhost:8000/docs`
- Recordings list: `http://localhost:8000/api/recordings`

Uploaded videos are stored in `dataset/raw/`. Metadata is stored in the ignored local SQLite file `dataset/metadata.sqlite3`.

The upload endpoint accepts WebM, MP4 or MOV files up to 100 MB. It requires a pseudonymous participant ID and explicit consent. This is a development foundation, not a public production service: do not expose it to the internet or upload real participant recordings until access controls, privacy procedures and backups are in place.
