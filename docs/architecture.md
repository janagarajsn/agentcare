# AgentCare Architecture

## 1. High-level flow

```
Patient (frontend)
   │  POST /workflows/submit  (request text + optional files)
   ▼
FastAPI route (routes_workflows.py)
   │  reads/validates uploads, calls the orchestrator
   ▼
run_agentic_workflow()  ─── app/agents/pipeline.py ───────────────────────────
   │
   ├─ 1. Deterministic safety screen (safety_rules.py — pure Python, no LLM)
   │       unsafe? ──► create Escalation, mark WorkflowRun AWAITING_ESCALATION, STOP
   │
   ├─ 2. Safety Agent (LLM)  — nuance layer on the raw request
   │       unsafe? ──► create Escalation (via its own tool call), STOP
   │
   ├─ 3. Coordinator Agent (LLM) — resolves patient, decides which steps are needed
   │
   ├─ 4. Department Routing Agent (LLM) — resolves a real Department row
   │       not found / ambiguous / inactive ──► create Escalation, STOP
   │
   ├─ 5. Appointment Agent (LLM)  ─┐  run concurrently (asyncio.gather) —
   │    Document Agent (LLM)      ─┘  both only depend on the resolved department
   │
   ├─ 6. Deterministic linking (plain Python) — attach any newly-stored
   │       document to a newly-booked appointment
   │
   ├─ 7. Safety Agent (LLM) again — reviews the aggregated output
   │       unsafe? ──► create Escalation, STOP
   │
   └─ 8. Follow-up Agent (LLM) — creates a pre-visit reminder + post-visit
           follow-up task, only if a real appointment now exists
   │
   ▼
WorkflowRun.state persisted (JSON) after every step, status → COMPLETED
   │
   ▼
Route re-queries the DB (Appointment / PatientDocument / Reminder / Escalation)
and returns a response built entirely from those persisted rows.
```

Every arrow above that reads from or writes to the database goes through the same
`app/services/*.py` functions the plain REST routes use — agents don't have a separate,
parallel, less-real code path. A tool call and a direct API call end up in the identical
service function.

## 2. The six agents

Each is a distinct `google.adk.agents.Agent` (`LlmAgent`) with its own instruction and its own
tool set or output responsibility — none of them share a prompt.

| Agent | File | Own tools | Responsibility |
|---|---|---|---|
| **Coordinator** | `app/agents/coordinator_agent.py` | `resolve_patient`, `record_plan` | Confirms the patient record, decides which of routing/appointment/document/follow-up this specific request needs (e.g. a document-only message skips booking). |
| **Department Routing** | `app/agents/routing_agent.py` | `resolve_department` | Classifies the request **administratively** ("cardiology follow-up"), never diagnostically. Escalates on ambiguous/unsupported/inactive department. |
| **Appointment** | `app/agents/appointment_agent.py` | `find_slots`, `book_slot`, `reschedule_appointment`, `cancel_appointment` | Real slot lookup + conflict-checked booking/reschedule/cancel. |
| **Document** | `app/agents/document_agent.py` | `store_pending_document`, `check_missing_documents` | Classifies attached files (filename heuristic), computes a checksum, flags duplicates, and reports missing required documents for the resolved department. |
| **Follow-up** | `app/agents/followup_agent.py` | `schedule_appointment_followups` | Creates a real appointment reminder and a post-visit follow-up task, timed from the actual booked slot. |
| **Safety & Escalation** | `app/agents/safety_agent.py` | `record_safety_verdict` | Reviews text for emergency language or diagnosis/prescription requests. When unsafe, its own tool call creates the `Escalation` row — the pipeline's Python code then reads that verdict and halts, so enforcement doesn't depend on the LLM "choosing" to stop. |

`app/agents/pipeline.py` is the Coordinator's orchestration made explicit in code — the actual
dispatch/halt decisions are plain Python `if` statements reading structured state that tools
write, not something left to an LLM's cooperation.

### Why this isn't "one prompt reused"

Each agent has its own `instruction` string and its own `tools=[...]` list (Coordinator and
Safety don't even share tools with anyone). State flows between them via ADK's `output_key` /
`session.state`, and — critically — via `WorkflowRun.state` in the database, written explicitly
by `pipeline.py` after every step (not left to ADK's own transient session, which is
`InMemorySessionService` and is discarded once the request finishes; see §5).

### The LLM-call boundary and testing

`app/agents/runner.py` defines `AgentInvoker` — the seam between the pipeline and ADK's
`Runner`/`InMemorySessionService`. `tests/fake_agent_invoker.py` provides a test double that
still invokes the *real* tool closures (real DB writes, real conflict checks, real checksums)
but replaces the model's *decision* of which tool to call with a small deterministic script.
This lets `tests/test_workflow_pipeline.py` exercise the full pipeline, including genuine
`Appointment`/`Reminder`/`Escalation` rows, without any API credentials.

## 3. Tools

All tools are real functions backed by `app/services/*.py`, which hit the actual SQLite/Postgres
database — none returns a fixed value regardless of input.

| Tool file | Backs | Real logic |
|---|---|---|
| `patient_tool.py` | Coordinator | Finds/creates the `PatientProfile` for the authenticated user. |
| `department_tool.py` | Routing | Exact → substring → ambiguous/not-found resolution against real `Department` rows. |
| `slot_tool.py` | Appointment | Filters real `AppointmentSlot` rows by department/doctor/date range, `OPEN` only. |
| `appointment_tool.py` | Appointment | Book/reschedule/cancel with two distinct conflict checks (slot already taken; patient double-booking). |
| `document_tool.py` | Document | Filename-keyword classification, SHA-256 checksum, duplicate flagging, department-scoped missing-document check. |
| `reminder_tool.py` | Follow-up | Creates `Reminder` rows and a simulated `NotificationLog` entry with a message built from the real appointment/doctor/slot data. |
| `escalation_tool.py` | Safety | Creates/resolves `Escalation` rows, transitions `WorkflowRun.status`. |
| `audit_tool.py` | All services | Writes `AuditEvent` rows — called directly by services on every write path that matters (registration, booking, reschedule, cancel, upload, escalation create/resolve, reminder create), not only from agent tool calls. |

## 4. RBAC — enforced server-side, not in the frontend

- JWT access/refresh tokens (`app/auth/security.py`); passwords hashed with bcrypt, never
  logged or returned in any response schema (`UserOut` excludes `password_hash`).
- `app/auth/rbac.py` provides three FastAPI dependencies used across every protected route:
  - `get_current_user` — validates the bearer token, loads the live `User` row, rejects
    inactive users.
  - `require_role(*roles)` — a dependency *factory*; e.g. `require_role(UserRole.ADMIN)` on
    department/doctor creation, `require_role(UserRole.STAFF, UserRole.ADMIN)` on
    escalation review.
  - `get_current_patient_profile` — wraps `require_role(PATIENT)` and additionally scopes to
    `current_user.id`, so a patient can never act on another patient's data by passing a
    different id in the request body/query. Routes that use `get_current_user` alone (where
    both patients and staff can hit the same endpoint) do an explicit ownership check inside
    the handler (see `_assert_can_view_appointment` in `routes_appointments.py`, and the
    equivalent check in `routes_documents.py`) — every one of these was audited during the
    Phase 7 hardening pass; one gap (`GET /documents/appointment/{id}/missing` missing an
    ownership check) was found and fixed there.
- The frontend never makes an authorization decision — it just forwards the bearer token; a
  403 from the backend is the only thing that actually blocks an action. Hiding a nav link is
  cosmetic only.

## 5. Persistence — SQL is the source of truth, not ADK state

- `WorkflowRun.state` (JSON column) is written by `pipeline.py` after every single pipeline
  step via `workflow_service.update_workflow_state`. This is our own explicit code — ADK's own
  `InMemorySessionService` session is transient scratch space for one agent turn and is
  discarded once that turn ends; it is never the durable record.
- Every escalation is a real `Escalation` row tied to a `WorkflowRun` via `workflow_run_id`.
- Every audit-worthy action (see the tool table above) produces an `AuditEvent` row with
  `actor_id`, `actor_role`, `action`, `entity_type`/`entity_id`, and metadata — queryable by
  staff at `GET /staff/audit-events` and rendered in the frontend's Audit Log page.

## 6. How escalation works end to end

1. Something flags a request or output as unsafe — either the deterministic keyword screen
   (`safety_rules.py`, e.g. "chest pain", "prescribe me") or the Safety Agent's LLM judgment
   (e.g. a phrasing that asks for a diagnosis without using any of the keyword patterns).
2. An `Escalation` row is created (`reason`, `detail`, `status=OPEN`) tied to the current
   `WorkflowRun`, and `WorkflowRun.status` becomes `AWAITING_ESCALATION`.
3. The pipeline halts — no further agents run, no booking/document/reminder action is taken
   for that request.
4. The patient sees this in the UI as "escalated for human review" with the real escalation id
   and reason (never a canned message — the frontend renders whatever the API returned).
5. A `staff` or `admin` user reviews it at `/staff/escalations`, and calls
   `POST /escalations/{id}/resolve` with `approved` or `rejected` (+ optional note). This is
   staff/admin-only, updates `reviewed_by`/`resolved_at`, and moves the underlying
   `WorkflowRun.status` to `RUNNING` (approved) or `FAILED` (rejected) — an audited, persisted
   human decision, not a UI-only toggle.

## 7. Error handling and recoverability

`app/agents/pipeline.py` wraps every LLM-call boundary in a retry-with-backoff
(`_invoke_with_retry`, one retry). If an agent still fails, the whole run is caught, the
`WorkflowRun` is marked `FAILED` with the error recorded in its `state`, and the function
returns normally — never a raw 500 or a silently stuck workflow. This was verified against a
real (mis)configured LLM call during hardening, not just simulated in tests.
