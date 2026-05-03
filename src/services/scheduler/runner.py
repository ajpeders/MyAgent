"""Scheduler runner — async loop that checks for overdue tasks and dispatches them."""
import asyncio
import logging

from src.services.news.curator import NewsCurator
from src.services.scheduler.store import SchedulerStore

log = logging.getLogger(__name__)

TASK_HANDLERS: dict[str, callable] = {
    "news_curation": lambda user_id: NewsCurator().curate(user_id),
}

_store = SchedulerStore()


async def scheduler_loop(poll_interval: float = 60.0) -> None:
    """Poll for overdue tasks and dispatch them. Runs until cancelled."""
    while True:
        try:
            overdue = _store.get_overdue_tasks()
            for task in overdue:
                handler = TASK_HANDLERS.get(task["task_type"])
                if handler is None:
                    log.warning("No handler for task type: %s", task["task_type"])
                    continue
                try:
                    await handler(task["user_id"])
                    _store.mark_completed(task["task_id"])
                    log.info(
                        "Completed task %s (%s) for user %s",
                        task["task_id"], task["task_type"], task["user_id"],
                    )
                except Exception:
                    log.exception(
                        "Failed task %s (%s) for user %s",
                        task["task_id"], task["task_type"], task["user_id"],
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler loop error")

        await asyncio.sleep(poll_interval)
