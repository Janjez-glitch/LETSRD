# LETSRD ecosystem

LETSRD is a learning app with a React Native/Expo frontend and a Python API.
The backend can turn student-notes PDFs into source-grounded illustrated
slideshows with narration.

## Project structure

```text
letsrd-ecosystem/
├── .gitignore
├── README.md
├── backend/
│   ├── api.py
│   ├── config.py
│   ├── requirements.txt
│   └── letsrd_backend/
└── frontend/
    ├── App.tsx
    ├── app.json
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    └── src/
```

`config.py`, `letsrd_backend/`, the frontend lockfile, TypeScript config, and
`frontend/src/theme.ts` are included because the main app imports them at
runtime/build time.

## Backend setup

Python 3.10 or newer is recommended. From the repository root, create and
activate a virtual environment, then install the backend dependencies:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Set `GEMINI_API_KEY` in the environment (or use `GOOGLE_API_KEY` as the
backward-compatible alias), then start the API:

```powershell
$env:GEMINI_API_KEY = "your-key"
python -m uvicorn api:app --app-dir backend --reload
```

The slideshow endpoint is `POST /v1/educational/slideshow`; upload the PDF in
the multipart `file` field. Set the multipart `visual_style` field to
`whiteboard`, `cinematic`, or `infographic` to choose an illustration style;
it defaults to `whiteboard` for clients that omit it. Set `language` to the
narration/subtitle language code. Pasted notes can be sent as JSON to
`POST /v1/educational/slideshow/text` with `text`, `language`, `visual_style`,
and `account_tier`. The player can request a different style for
an individual generated scene through
`POST /v1/educational/slideshows/{job_id}/scenes/{scene_index}/style`.
Multiple-choice recall results are aggregated by user and style at
`/v1/learning-style/results`; recommendations are shown after at least three
answers have been recorded for a style. Generated scene images and narration
are served from URLs returned in the response. The default image model is
`gemini-2.5-flash-image`; set `GEMINI_IMAGE_MODEL` to another image-generation
model available to your Google AI Studio account if needed.

## Frontend setup

From the frontend directory, install dependencies and start Expo:

```powershell
cd frontend
npm ci --legacy-peer-deps
npm start
```

The app's API base URL is configured in `frontend/App.tsx`. Set it to the
reachable backend address for your device or emulator before testing API-backed
features.

## GitHub

Initialize and commit this folder from its root after reviewing the files:

```powershell
git init
git add .
git commit -m "Initial commit: unified letsrd backend and frontend"
git branch -M main
```

Create an empty GitHub repository, then add its full clone URL as the `origin`
remote and push `main`:

```powershell
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Never commit `.env` files or API keys. The root `.gitignore` excludes local
environment files, dependency folders, Python caches, and build output.
