# Code walkthrough: a request end-to-end

This traces one concrete request — a patient submitting free text on the "Submit a
request" page — from the browser, through both FastAPI processes, through the agent
pipeline, and back to the rendered page. Other flows (login, direct appointment
booking, document upload) follow the same frontend → `BackendClient` → backend route
shape; the submit flow is used here because it also exercises the agent pipeline.

For the agent/tool responsibilities themselves, see [`architecture.md`](architecture.md).
This document is about the *request plumbing* around them.

## 1. Browser → frontend route

The patient fills in the textarea on `patient/submit.html` and POSTs the form to the
**frontend** process (port 8501). [`frontend/routers/patient.py`](../frontend/routers/patient.py)
handles it:

```python
@router.post("/submit")
async def submit_action(request_text: str = Form(...), files: list[UploadFile] = File(default=[]),
                         user: dict = Depends(require_patient)):
    client = _client(user)          # BackendClient carrying the patient's JWT
    result = await client.post("/workflows/submit", data={"request_text": request_text},
                                files=upload_files or None, timeout=180)
    return render(request, "patient/submit.html", {"result": result, "error": None})
```

Two things happen before the handler body runs:
- `Depends(require_patient)` (in [`deps.py`](../frontend/deps.py)) reads the `access_token`
  cookie, calls the backend's `/auth/me` to resolve the session, and stashes the user dict
  on `request.state.user` (this is what lets `base.html` render the nav bar/logout link).
  If there's no valid cookie it raises `AuthRedirect`, which an exception handler in
  [`app.py`](../frontend/app.py) turns into a `302` to `/login`.
- The 180s timeout is deliberate — the backend call below may involve several sequential
  LLM calls with retries, which comfortably exceeds a typical default HTTP timeout.

The frontend **never** imports backend Python — `BackendClient` is a thin `httpx` wrapper
that talks to the backend only over HTTP, forwarding the same bearer token, and converting
network failures (timeout, connection refused) into a `BackendAPIError` the route can
render as a friendly message instead of crashing:

```python
# frontend/backend_client.py
except httpx.TimeoutException as exc:
    raise BackendAPIError(504, "The backend took too long to respond. Please try again.") from exc
```

## 2. Backend route → agent pipeline

The POST lands on the **backend** process (port 8000) at
[`routes_workflows.py`](../backend/app/api/routes_workflows.py). FastAPI dependencies
(`get_current_user`, `get_current_patient_profile`) re-validate the JWT and resolve the
`PatientProfile` server-side — the frontend's own session check is a UX convenience, not
the security boundary. The route reads any uploaded files into memory, then hands off to
the orchestrator:

```python
workflow_run = await run_agentic_workflow(db, current_user, patient, request_text,
                                           pending_documents=pending_documents,
                                           agent_invoker=agent_invoker)
return _build_submission_response(db, workflow_run)
```

## 3. The pipeline (`app/agents/pipeline.py`)

`run_agentic_workflow` is a plain Python function, not an LLM — the dispatch/halt logic
is enforced in code so it can't be talked around by a prompt. It creates a `WorkflowRun`
row up front and persists `WorkflowRun.state` after every step, so a run surviving a
process restart is a property of the database, not of anything held in memory:

1. **Deterministic safety screen** (`safety_rules.screen_text`) — regex-based, no LLM
   call. If it matches, an `Escalation` is raised and the pipeline returns immediately.
2. **Safety Agent (pre)** — an LLM pass over the raw request for nuance the regex can't
   catch. Can also halt the run (`WorkflowStatus.AWAITING_ESCALATION`).
3. **Coordinator Agent** — decides the plan (`needs_routing`, `needs_appointment`,
   `needs_document_check`, `needs_followup`).
4. **Routing Agent** (conditional) — resolves a department. `not_found`/`ambiguous` halts
   with an escalation.
5. **Appointment Agent + Document Agent — run concurrently** via `asyncio.gather`, since
   neither depends on the other's output:
   ```python
   if coros:
       results = await asyncio.gather(*coros.values())
   ```
6. Newly-stored documents are linked to a newly-booked appointment — plain Python, not an
   agent decision.
7. **Safety Agent (post)** — reviews what's about to be shown back to the patient.
8. **Follow-up Agent** (conditional) — schedules reminders once a real appointment exists.

Every agent call goes through `_invoke_with_retry`, which retries once on failure and,
if both attempts fail, raises `AgentInvocationError` — caught by `run_agentic_workflow`
and turned into a `WorkflowStatus.FAILED` run instead of a crash.

Each agent call itself goes through [`runner.py`](../backend/app/agents/runner.py)'s
`AgentInvoker`, which wraps ADK's `Runner` + a fresh `InMemorySessionService` per call
and returns the resulting `session.state` — this is the one seam the test suite replaces
with a fake, so the pipeline logic above is tested without any real model call.

## 4. Response assembly and back to the frontend

Once `run_agentic_workflow` returns, `_build_submission_response` reads the final
`WorkflowRun.state` and re-fetches the *real* rows it references (appointment, documents,
reminders, escalation) rather than trusting whatever the agents put in state — the DB
row is the source of truth, the state dict is just a pointer into it. This is serialized
as `SubmitRequestResponse` and returned as JSON to the frontend.

Back in `submit_action`, that JSON becomes the `result` dict passed into
`patient/submit.html`, which renders a human-readable summary (routing outcome,
appointment card, documents table, reminders table, or an escalation notice) instead of
raw JSON — with the full state still available underneath a collapsed
`<details>` block for debugging.

## Summary of the round trip

```
Browser (submit form)
  → frontend POST /patient/submit          (frontend/routers/patient.py)
      → BackendClient.post("/workflows/submit")     (frontend/backend_client.py, real HTTP)
          → backend POST /workflows/submit          (backend/app/api/routes_workflows.py)
              → run_agentic_workflow(...)            (backend/app/agents/pipeline.py)
                  → AgentInvoker.run(...) per agent   (backend/app/agents/runner.py, ADK Runner)
              ← SubmitRequestResponse (JSON)
      ← JSON decoded by BackendClient
  → render("patient/submit.html", {"result": ...})   (frontend/templating.py)
← rendered HTML back to the browser
```
