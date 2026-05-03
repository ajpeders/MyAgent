"""Scheduler service — thin wrapper over SchedulerStore, returns models."""
from src.services.scheduler.models import ScheduledTask
from src.services.scheduler.store import SchedulerStore


class SchedulerService:
    def __init__(self):
        self._store = SchedulerStore()

    def create_task(self, user_id: str, task_type: str, schedule: str) -> ScheduledTask:
        row = self._store.create_task(user_id, task_type, schedule)
        return ScheduledTask(**row)

    def get_user_tasks(self, user_id: str) -> list[ScheduledTask]:
        rows = self._store.get_user_tasks(user_id)
        return [ScheduledTask(**r) for r in rows]

    def get_overdue_tasks(self) -> list[ScheduledTask]:
        rows = self._store.get_overdue_tasks()
        return [ScheduledTask(**r) for r in rows]

    def mark_completed(self, task_id: str) -> None:
        self._store.mark_completed(task_id)

    def update_task(
        self, task_id: str, user_id: str,
        schedule: str | None = None, enabled: bool | None = None,
    ) -> ScheduledTask | None:
        row = self._store.update_task(task_id, user_id, schedule=schedule, enabled=enabled)
        return ScheduledTask(**row) if row else None

    def delete_task(self, task_id: str, user_id: str) -> bool:
        return self._store.delete_task(task_id, user_id)
