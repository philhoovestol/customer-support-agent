# Running The App

These steps assume Windows PowerShell from the repository root.

## 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

If `.venv` already exists, skip `python -m venv .venv` and activate it directly.
On Windows, recreating the venv while the backend server is still running can
fail with `Permission denied` for `.venv\Scripts\python.exe`; stop the FastAPI
process first, then recreate the venv if you truly need a clean one.

The backend starts on `http://localhost:8000`.

Default mode is deterministic mock LLM mode. To use OpenAI instead, create
`backend/.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```

The SQLite database is created at `backend/support_agent.db` and seeded on first
startup.

To clear generated cases/logs and restore the initial mock seed state:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\reset_db.py
```

## 2. Frontend

Open a second PowerShell window from the repository root.

```powershell
cd frontend
npm install
npm run dev
```

The frontend starts on `http://localhost:5173`.

During local development, Vite proxies `/api` requests to the backend at
`http://localhost:8000`, so no frontend environment file is required for the
standard two-process setup.

If the backend runs somewhere else, create `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Production builds default to same-origin `/api` requests. The Docker deployment
builds the frontend and serves it from FastAPI as a single web service.

## 3. Useful Checks

Backend tests:

```powershell
cd backend
pytest
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Health endpoint:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

Example chat request:

```powershell
Invoke-RestMethod http://localhost:8000/api/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"message":"I need a refund for ORD-1002. The headphones are uncomfortable."}'
```
