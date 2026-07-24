# AgentCare

Agentic AI for patient administration and care coordination — a hospital assistant that
understands a patient's free-text administrative request, plans the required steps, invokes
real tools against a real database, and completes the task safely, escalating anything
uncertain, emergency, or clinical to a human. It never diagnoses, prescribes, or recommends
treatment.

This is the **core submission**: registration → intent detection → department routing →
appointment booking → document coordination → confirmation/reminders → follow-up. Optional
extensions from the brief (insurance, billing, bed allocation, pharmacy, staff scheduling,
multilingual/voice, analytics dashboard, FHIR, etc.) are explicitly out of scope for this
submission.

See [`docs/architecture.md`](docs/architecture.md) for the full agent/tool/data-flow breakdown
and [`docs/challenge_brief.md`](docs/challenge_brief.md) for the original spec.

## What was built

- **Backend** — FastAPI + SQLAlchemy 2.0 + Alembic + SQLite (swappable to Postgres via one env
  var), JWT auth (`python-jose`) with bcrypt password hashing, server-enforced RBAC
  (`patient` / `staff` / `admin`).
- **Six distinct Google ADK agents** (own instruction + own tools/responsibility each):
  Coordinator, Department Routing, Appointment, Document, Follow-up, Safety & Escalation —
  wired into a Python orchestrator (`app/agents/pipeline.py`) that persists `WorkflowRun` state
  after every step and enforces the safety guardrail and dispatch decisions in code, not just
  in a prompt.
- **A two-layer safety boundary**: a deterministic keyword screen (no LLM call, can't be
  talked around) plus an LLM-based Safety Agent for nuance — both can create a real
  `Escalation` row and halt the pipeline before any booking/document action happens.
- **Eight real tools** backed by real services/DB logic (patient, department, slot,
  appointment, document, reminder, escalation, audit) — no tool ever returns a fixed value
  regardless of input.
- **A separate Jinja2 + vanilla-JS frontend** (its own FastAPI process) that talks to the
  backend only over HTTP — patient and staff screens for every required flow.
- **55 automated tests** (`pytest`), including an end-to-end workflow test suite that mocks the
  LLM-call boundary so the suite runs deterministically without real API credentials.

## Repository layout

```
agentcare/
├── docs/
│   ├── challenge_brief.md       # original spec
│   └── architecture.md          # agents, tools, data flow, RBAC, escalation
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app factory + router registration
│   │   ├── config.py             # env-based settings
│   │   ├── db/                   # SQLAlchemy models, session, base
│   │   ├── schemas/               # pydantic request/response models
│   │   ├── auth/                  # JWT + bcrypt, RBAC dependencies
│   │   ├── api/                   # routes_* — one file per resource area
│   │   ├── agents/                # ADK LlmAgent definitions + orchestration pipeline
│   │   ├── tools/                 # ADK tool functions, wrapping services
│   │   ├── services/               # business logic (used by routes AND tools)
│   │   └── seed/                  # synthetic sample data
│   ├── alembic/                    # migrations
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app.py, config.py, deps.py, backend_client.py, templating.py
│   ├── routers/                   # auth, patient, staff
│   ├── templates/                 # Jinja2, patient/ and staff/ subfolders
│   ├── static/                    # css, js
│   ├── requirements.txt
│   └── .env.example
└── README.md
```

Backend and frontend are independently runnable processes; the frontend never imports backend
Python modules — it only calls the backend's documented HTTP API.

## Prerequisites

- **Python 3.12** (not 3.14 — some pinned dependencies had compatibility issues with the very
  newest CPython at the time this was built; 3.12 is what's tested).
- A Google AI Studio API key if you want real agent/LLM behavior (`GOOGLE_API_KEY`). The test
  suite does **not** need one — it mocks the LLM-call boundary. Running the app live without a
  key still works: the pipeline's retry/error-handling path will mark the workflow `FAILED`
  gracefully instead of crashing.

## Backend setup

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env — see "Environment variables" below
alembic upgrade head               # create/upgrade the SQLite schema
python -m app.seed.seed_data       # synthetic departments/doctors/slots/demo users

uvicorn app.main:app --reload --port 8000
```

The API is now at `http://localhost:8000` (interactive docs at `/docs`).

## Frontend setup

In a second terminal:

```bash
cd frontend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env               # BACKEND_API_URL defaults to http://localhost:8000

uvicorn app:app --reload --port 8501
```

Open `http://localhost:8501` — it redirects to `/login`.

## Demo accounts

Seeded by `python -m app.seed.seed_data` (synthetic, not real people):

| Role    | Email                          | Password       |
|---------|---------------------------------|----------------|
| Patient | patient1@agentcare.example       | Patient123!    |
| Patient | patient2@agentcare.example       | Patient123!    |
| Staff   | staff1@agentcare.example         | Staff123!      |
| Admin   | admin1@agentcare.example         | Admin123!      |

Staff can view/manage everything; only `admin` can create departments/doctors/staff accounts
(`staff` can create appointment slots and review escalations).

## Environment variables

### `backend/.env`

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./agentcare.db` | Swap to a Postgres URL to move off SQLite with no code changes. |
| `JWT_SECRET_KEY` | *(dev placeholder)* | **Set a real random value for anything beyond local dev** (`openssl rand -hex 32`). |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` (7 days) | |
| `GOOGLE_API_KEY` | *(placeholder)* | Needed for real agent/LLM behavior via ADK's native Gemini integration. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Swappable without code changes. |
| `USE_LITELLM` | `false` | Set `true` to route through ADK's LiteLLM path instead (e.g. OpenAI/Anthropic/Ollama). |
| `LLM_MODEL` | `gemini/gemini-3.5-flash` | Model id passed to `LiteLlm(...)` when `USE_LITELLM=true`. |
| `DOCUMENT_STORAGE_DIR` | `./storage/documents` | Must stay outside any web-servable static path. |
| `MAX_UPLOAD_SIZE_MB` | `10` | |
| `ENVIRONMENT` | `development` | |
| `CORS_ALLOW_ORIGINS` | `http://localhost:8501,http://localhost:8000` | Comma-separated. |

### `frontend/.env`

| Variable | Default | Notes |
|---|---|---|
| `BACKEND_API_URL` | `http://localhost:8000` | The only way the frontend reaches the backend. |
| `COOKIE_SECURE` | `false` | Set `true` when serving the frontend over HTTPS. |

Neither `.env` file is committed — only the `.env.example` templates are, with placeholder
values. No real credentials or patient data are ever checked in.

## Running tests

```bash
cd backend
source venv/bin/activate
pytest
```

55 tests across `tests/test_auth_rbac.py`, `test_appointments.py`, `test_documents.py`,
`test_escalations.py`, and `test_workflow_pipeline.py`. The last of these covers the full
agentic pipeline end-to-end — booking happy path, deterministic and LLM-caught safety
escalations, unsupported-department escalation, a document-only request that never touches
appointment booking, state surviving a simulated restart, the retry-then-`FAILED` path on a
persistent model failure, rescheduling correctly updating (not duplicating) reminders, and the
Appointment Agent resolving "my appointment" via a lookup tool when the request never states an
explicit appointment id — all via a `FakeAgentInvoker` test double that drives the *real*
tool/service/DB logic without calling any actual model, so the suite needs no API key and runs
deterministically.

Tests use an isolated temp-file SQLite database per test (via `conftest.py` fixtures), never
the dev database.

## Known limitations

- Refresh tokens are stateless (standard JWT behavior) — logging out clears the cookie but
  doesn't server-side-revoke the token before its own expiry. Fine for this scope; a
  production deployment would want a revocation list.
- No silent access-token refresh in the frontend UI yet — after the access token expires
  (30 min default) the user is redirected to log in again.
- Optional extensions from the brief (Section 13) are intentionally not implemented.

## License

MIT — see [`LICENSE`](LICENSE).
