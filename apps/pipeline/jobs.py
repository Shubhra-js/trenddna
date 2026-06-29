"""
Lightweight job execution framework — Strategy Pattern for background tasks.

WHY THIS FILE EXISTS:
    Raw threading.Thread scattered across services creates tight coupling.
    This module provides a clean abstraction: submit a callable, get back
    a job_id, check status later. The service layer doesn't know or care
    whether the job runs synchronously, in a thread, or via Celery.

INTERVIEW Q: "Why not just use Celery from the start?"
    "Celery requires Redis or RabbitMQ as a broker — that's infrastructure
    I don't need for an MVP handling one topic at a time. This abstraction
    gives me async behavior with zero infrastructure. When I need Celery,
    I implement CeleryJobRunner and swap one line in settings. The ingestion
    service doesn't change at all. That's the Strategy Pattern."

INTERVIEW Q: "How does this compare to Django-Q or Dramatiq?"
    "Same idea — decouple task definition from task execution. Django-Q uses
    the ORM as a broker (clever but slow). Dramatiq needs RabbitMQ. My
    abstraction is simpler because I only need 'run this function in the
    background.' If my needs grow, I swap the runner — not the architecture."
"""
import logging
import time
import threading
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable

from django.db import connection

logger = logging.getLogger("apps.pipeline")

# In-memory job status store (sufficient for single-process MVP)
# Production would use Redis or database-backed status
_job_registry: dict[str, dict] = {}


class JobRunner(ABC):
    """
    Abstract base for job execution strategies.

    Every runner must implement submit() — which accepts a callable
    and returns a job_id. The callable receives *args and **kwargs
    and can be any plain Python function (no decorators needed).
    """

    @abstractmethod
    def submit(self, job_fn: Callable, *args, **kwargs) -> str:
        """
        Submit a job for execution.

        Args:
            job_fn: The function to execute.
            *args, **kwargs: Arguments passed to job_fn.

        Returns:
            A unique job_id string for tracking.
        """
        pass

    def get_status(self, job_id: str) -> dict:
        """
        Check the status of a submitted job.

        Returns:
            {
                "job_id": "...",
                "status": "pending" | "running" | "completed" | "failed",
                "started_at": float | None,
                "completed_at": float | None,
                "error": str | None,
            }
        """
        return _job_registry.get(job_id, {
            "job_id": job_id,
            "status": "unknown",
        })


class SyncJobRunner(JobRunner):
    """
    Runs jobs synchronously — blocks until completion.

    WHY THIS EXISTS:
        1. Tests: Django's TestCase wraps everything in a transaction.
           Background threads can't see the test database. SyncJobRunner
           runs inline, so tests work naturally.
        2. Debugging: Synchronous execution makes stack traces readable.
        3. Fallback: If threading causes issues, flip to sync.
    """

    def submit(self, job_fn: Callable, *args, **kwargs) -> str:
        job_id = _generate_job_id()
        _job_registry[job_id] = {
            "job_id": job_id,
            "status": "running",
            "started_at": time.time(),
            "completed_at": None,
            "error": None,
        }

        try:
            job_fn(*args, **kwargs)
            _job_registry[job_id]["status"] = "completed"
        except Exception as e:
            _job_registry[job_id]["status"] = "failed"
            _job_registry[job_id]["error"] = str(e)
            logger.error("Sync job %s failed: %s", job_id, e)
        finally:
            _job_registry[job_id]["completed_at"] = time.time()

        return job_id


class ThreadJobRunner(JobRunner):
    """
    Runs jobs in a background daemon thread.

    WHY daemon=True:
        Daemon threads are killed when the main process exits.
        This prevents threads from blocking Django shutdown.

    WHY connection.close():
        Django creates one DB connection per thread. Background threads
        must close their connection when done, or it leaks. The finally
        block guarantees cleanup even if the job crashes.
    """

    def submit(self, job_fn: Callable, *args, **kwargs) -> str:
        job_id = _generate_job_id()
        _job_registry[job_id] = {
            "job_id": job_id,
            "status": "running",
            "started_at": time.time(),
            "completed_at": None,
            "error": None,
        }

        def _run():
            try:
                job_fn(*args, **kwargs)
                _job_registry[job_id]["status"] = "completed"
            except Exception as e:
                _job_registry[job_id]["status"] = "failed"
                _job_registry[job_id]["error"] = str(e)
                logger.error("Thread job %s failed: %s", job_id, e)
            finally:
                _job_registry[job_id]["completed_at"] = time.time()
                connection.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        logger.info("Job %s started in background thread", job_id)
        return job_id


def _generate_job_id() -> str:
    """Generate a short, unique job identifier."""
    return f"job_{uuid.uuid4().hex[:12]}"


def get_job_runner() -> JobRunner:
    """
    Factory function — returns the configured job runner.

    WHY a factory instead of a global instance:
        Tests can override this to use SyncJobRunner. The ingestion
        service calls get_job_runner() each time, so swapping runners
        at runtime works without restarting the server.

    INTERVIEW Q: "How would you swap to Celery?"
        "1. Install celery + redis.
         2. Create CeleryJobRunner that calls job_fn.delay().
         3. Change this factory to return CeleryJobRunner.
         4. Zero changes to ingestion_service.py or views.py."
    """
    from django.conf import settings
    runner_class = getattr(settings, "JOB_RUNNER_CLASS", None)

    if runner_class == "sync":
        return SyncJobRunner()

    return ThreadJobRunner()
