"""Background worker. Run as its own process next to the API:

    python -m grievance_app.worker            # loops forever (use systemd / docker restart policy)
    python -m grievance_app.worker --once     # one pass, for cron

Safe to run more than once, but one is enough.
"""
import argparse
import logging
import signal
import threading

from .config import get_settings
from .db import SessionLocal
from .services.scheduler import run_once

log = logging.getLogger("grievance.worker")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    tick = get_settings().worker_tick_seconds
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                summary = run_once(db)
            log.info("pass done: %s", summary)
        except Exception:
            log.exception("pass failed")
        if args.once:
            break
        stop.wait(tick)


if __name__ == "__main__":
    main()
