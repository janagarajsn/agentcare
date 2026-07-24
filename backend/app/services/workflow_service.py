from sqlalchemy.orm import Session

from app.db.models import WorkflowRun, WorkflowStatus


class WorkflowRunNotFoundError(Exception):
    pass


def create_workflow_run(db: Session, patient_id: int, request_text: str) -> WorkflowRun:
    run = WorkflowRun(
        patient_id=patient_id,
        current_step="intake",
        state={},
        status=WorkflowStatus.RUNNING,
        request_text=request_text,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_workflow_run(db: Session, workflow_run_id: int) -> WorkflowRun:
    run = db.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise WorkflowRunNotFoundError(f"WorkflowRun {workflow_run_id} not found")
    return run


def update_workflow_state(
    db: Session,
    workflow_run_id: int,
    *,
    current_step: str | None = None,
    state_patch: dict | None = None,
    status: WorkflowStatus | None = None,
) -> WorkflowRun:
    run = get_workflow_run(db, workflow_run_id)
    if current_step is not None:
        run.current_step = current_step
    if state_patch is not None:
        run.state = {**run.state, **state_patch}
    if status is not None:
        run.status = status
    db.commit()
    db.refresh(run)
    return run


def list_workflow_runs(db: Session, patient_id: int | None = None) -> list[WorkflowRun]:
    query = db.query(WorkflowRun)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    return query.order_by(WorkflowRun.created_at.desc()).all()
