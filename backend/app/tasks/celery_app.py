from __future__ import annotations
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "dv_acode",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.batch_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=settings.celery_concurrency,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
