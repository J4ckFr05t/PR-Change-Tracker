from celery import Celery
import os

# Use env vars with fallback
broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

def make_celery(app_name=__name__):
    return Celery(
        app_name,
        broker=broker_url,
        backend=result_backend
    )

celery = make_celery()

# 👇 Import your task to ensure it's registered
import tasks  # This line is critical!