from sqlalchemy.orm import Session

from app.db.models import Department


def lookup_department(db: Session, query: str) -> dict:
    """Resolve a free-text department name to a stored Department row.

    Real branching: exact match, then substring match, then ambiguous/not-found
    reporting so a caller (route or, later, the Routing Agent) can decide
    whether to escalate. Never returns a fixed result regardless of input.
    """
    cleaned = query.strip()
    if not cleaned:
        return {"status": "not_found", "reason": "empty department query"}

    exact = db.query(Department).filter(Department.name.ilike(cleaned)).first()
    if exact is not None:
        return _department_result(exact)

    candidates = db.query(Department).filter(Department.name.ilike(f"%{cleaned}%")).all()
    if len(candidates) == 1:
        return _department_result(candidates[0])
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "candidates": [{"id": d.id, "name": d.name} for d in candidates],
        }

    return {"status": "not_found", "reason": f"no department matches '{query}'"}


def _department_result(department: Department) -> dict:
    if not department.active:
        return {
            "status": "inactive",
            "department_id": department.id,
            "department_name": department.name,
        }
    return {
        "status": "found",
        "department_id": department.id,
        "department_name": department.name,
    }
