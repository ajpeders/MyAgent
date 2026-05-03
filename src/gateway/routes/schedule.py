"""Schedule routes — /api/schedule/*."""
from fastapi import APIRouter, HTTPException, Request

from src.gateway.middleware import jwt_required
from src.services.scheduler.models import UpdateScheduleRequest
from src.services.scheduler.service import SchedulerService

router = APIRouter()
_scheduler = SchedulerService()


@router.get("/api/schedule")
async def list_tasks(request: Request):
    payload = jwt_required(request)
    tasks = _scheduler.get_user_tasks(payload["user_id"])
    return {"tasks": [t.model_dump() for t in tasks]}


@router.put("/api/schedule/{task_id}")
async def update_task(request: Request, task_id: str, body: UpdateScheduleRequest):
    payload = jwt_required(request)
    updated = _scheduler.update_task(
        task_id, payload["user_id"],
        schedule=body.schedule, enabled=body.enabled,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated.model_dump()
