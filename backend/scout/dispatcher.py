"""DB-backed scheduler/dispatcher remains alive even when Redis is unavailable."""

import logging
import time

from scout.retention import archive_expired
from scout.service import dispatch_pending, recover_expired, schedule_due
from scout.worker import run_task


def main():
    logging.basicConfig(level=logging.INFO)
    next_archive = 0
    while True:
        if time.monotonic() >= next_archive:
            try:
                archive_expired()
                next_archive = time.monotonic() + 60
            except Exception as exc:
                logging.warning("archive tick failed (%s); retrying", type(exc).__name__)
        try:
            recover_expired()
            schedule_due()
            dispatch_pending(
                lambda task_id: run_task.apply_async(
                    args=[task_id], retry=False, queue="collection"
                ),
                publish_customer=lambda task_id: run_task.apply_async(
                    args=[task_id], retry=False, queue="customers"
                )
            )
        except Exception as exc:
            logging.warning("dispatcher tick failed (%s); retrying", type(exc).__name__)
        time.sleep(3)


if __name__ == "__main__":
    main()
