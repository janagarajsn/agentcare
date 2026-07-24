from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    actor_role: str
    action: str
    entity_type: str
    entity_id: int | None
    event_metadata: dict
    created_at: datetime
