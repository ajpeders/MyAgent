"""Scheduler service models."""
from pydantic import BaseModel


class ScheduledTask(BaseModel):
    task_id: str
    user_id: str
    task_type: str
    schedule: str
    last_run_at: float | None
    next_run_at: float
    enabled: bool


class UpdateScheduleRequest(BaseModel):
    schedule: str | None = None
    enabled: bool | None = None
