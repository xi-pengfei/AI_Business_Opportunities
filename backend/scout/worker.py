from celery import Celery

from scout.config import settings
from scout.service import execute

app = Celery("scout", broker=settings().redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_soft_time_limit=100,
    task_time_limit=120,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 180},
)


@app.task(name="scout.execute")
def run_task(task_id: str):
    execute(task_id)
