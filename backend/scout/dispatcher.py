"""DB-backed scheduler/dispatcher remains alive even when Redis is unavailable."""

import logging
import time

from scout.service import dispatch_pending, recover_expired, schedule_due
from scout.worker import run_task


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            recover_expired()
            schedule_due()
            dispatch_pending(
                lambda task_id: run_task.apply_async(
                    args=[task_id], retry=False, queue="collection"
                )
            )
        except Exception as exc:
            logging.warning("dispatcher tick failed (%s); retrying", type(exc).__name__)
        time.sleep(3)


if __name__ == "__main__":
    main()
