"""Delete old finished tickets (data retention).

    python -m grievance_app.retention            # shows what WOULD be deleted (default)
    python -m grievance_app.retention --apply    # deletes it

What counts: tickets that are CLOSED or CANCELLED for longer than RETENTION_YEARS (normal tickets) or
RETENTION_CONFIDENTIAL_YEARS (confidential ones). 0 means "never delete" and is the default for both.
Open tickets are never touched. The audit log is never touched. Uploaded files are deleted with their ticket.
Take a backup first (docs/RUNBOOK.md).
"""
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import Status
from .models import Attachment, Event, Feedback, Notification, Ticket
from .services.audit import audit
from .services.tickets import utcnow

log = logging.getLogger("grievance.retention")


def _candidates(db: Session, years: int, confidential: bool, now: datetime) -> list[Ticket]:
    if years <= 0:
        return []
    cutoff = now - timedelta(days=365 * years)
    finished = Ticket.status.in_(Status.FINAL)
    when = or_(Ticket.closed_at < cutoff, (Ticket.closed_at.is_(None)) & (Ticket.updated_at < cutoff))
    return list(db.scalars(select(Ticket).where(finished, when, Ticket.confidential.is_(confidential))).all())


def purge(db: Session, now: Optional[datetime] = None, apply: bool = False) -> dict:
    now = now or utcnow()
    s = get_settings()
    tickets = _candidates(db, s.retention_years, False, now) + _candidates(db, s.retention_confidential_years, True, now)
    summary = {"applied": apply, "tickets": len(tickets), "confidential": sum(t.confidential for t in tickets),
               "files": 0, "retention_years": s.retention_years,
               "retention_confidential_years": s.retention_confidential_years}
    if not tickets:
        return summary
    ids = [t.id for t in tickets]
    atts = db.scalars(select(Attachment).where(Attachment.ticket_id.in_(ids))).all()
    summary["files"] = len(atts)
    if not apply:
        return summary
    folder = Path(s.upload_dir)
    for a in atts:
        try:
            (folder / a.stored_name).unlink(missing_ok=True)
        except OSError:
            log.warning("Could not delete a file of a purged ticket")
    for model, col in ((Feedback, Feedback.ticket_id), (Notification, Notification.ticket_id),
                       (Event, Event.ticket_id), (Attachment, Attachment.ticket_id)):
        db.execute(delete(model).where(col.in_(ids)))
    db.execute(delete(Ticket).where(Ticket.id.in_(ids)))
    audit(db, None, "purge", "ticket", None,
          f"{summary['tickets']} tickets ({summary['confidential']} confidential), {summary['files']} files "
          f"older than {s.retention_years}/{s.retention_confidential_years} years")
    db.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="really delete (default is a dry run)")
    args = parser.parse_args()
    from .db import SessionLocal
    s = get_settings()
    if s.retention_years <= 0 and s.retention_confidential_years <= 0:
        print("Retention is switched off (RETENTION_YEARS and RETENTION_CONFIDENTIAL_YEARS are 0). Nothing to do.")
        return
    with SessionLocal() as db:
        result = purge(db, apply=args.apply)
    verb = "Deleted" if args.apply else "Would delete"
    print(f"{verb} {result['tickets']} tickets ({result['confidential']} confidential) and {result['files']} files.")
    if not args.apply:
        print("This was a dry run. Run again with --apply to delete.")


if __name__ == "__main__":
    main()
