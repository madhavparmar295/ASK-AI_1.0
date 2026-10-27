"""Database tables (the shared schema).

Tables: users, categories, units, routing, tickets, attachments, events,
feedback, notifications, audit_log.

Additions to the original 9-table plan:
  * tickets.route_id  - the routing row used at assignment. The permission
                        checks use it to decide who is in the ticket's chain.
  * tickets.paused_at - set while a ticket is NEEDS_INFO (deadline clock paused).
  * audit_log         - who changed admin configuration and when.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, Uuid, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import Role, Status, UnitType
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", Role.ALL), name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    department: Mapped[Optional[str]] = mapped_column(String(100))
    hostel: Mapped[Optional[str]] = mapped_column(String(100))
    room: Mapped[Optional[str]] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default=Role.STUDENT)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint(_in("unit_type", UnitType.ALL), name="ck_categories_unit_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_hours: Mapped[int] = mapped_column(Integer, default=72)
    unit_type: Mapped[str] = mapped_column(String(20), default=UnitType.CAMPUS)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Comma-separated keywords for the text classifier, e.g. "hostel:3, warden:3, leak*, air conditioner".
    keywords: Mapped[Optional[str]] = mapped_column(Text)


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("type", "name", name="uq_units_type_name"),
        CheckConstraint(_in("type", UnitType.ALL), name="ck_units_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Routing(Base):
    """(category, unit) -> chain of three people. unit_id NULL = category default."""
    __tablename__ = "routing"
    __table_args__ = (
        UniqueConstraint("category_id", "unit_id", name="uq_routing_category_unit"),
        # NULLs are distinct in a normal unique constraint, so also guard the default row.
        Index("uq_routing_default", "category_id", unique=True,
              postgresql_where=text("unit_id IS NULL"),
              sqlite_where=text("unit_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"))
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("units.id"))
    level0_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    level1_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    level2_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))

    category = relationship("Category")
    unit = relationship("Unit")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(_in("status", Status.ALL), name="ck_tickets_status"),
        Index("ix_tickets_status_due", "status", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    ticket_no: Mapped[str] = mapped_column(String(30), unique=True)
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"))
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("units.id"))
    route_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("routing.id"))
    location_text: Mapped[Optional[str]] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=Status.ASSIGNED)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    reporter = relationship("User", foreign_keys=[reporter_id])
    assignee = relationship("User", foreign_keys=[assignee_id])
    category = relationship("Category")
    unit = relationship("Unit")
    route = relationship("Routing")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stored_name: Mapped[str] = mapped_column(String(100), unique=True)  # random, never the user's name
    original_name: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    scan_status: Mapped[str] = mapped_column(String(20), default="not_scanned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    """Timeline of everything that happens to a ticket."""
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))   # status, message, escalation, assignment ...
    from_status: Mapped[Optional[str]] = mapped_column(String(20))
    to_status: Mapped[Optional[str]] = mapped_column(String(20))
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))  # NULL = system
    text: Mapped[Optional[str]] = mapped_column(Text)
    visible_to_student: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_feedback_rating"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), primary_key=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("tickets.id"))
    text: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_error: Mapped[Optional[str]] = mapped_column(Text)
    email_attempts: Mapped[int] = mapped_column(Integer, default=0)
    email_last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemState(Base):
    """Small key-value store: scheduler heartbeat, last error, watchdog alerts."""
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Admin configuration changes: who did what, when."""
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))     # create | update | delete | import
    entity: Mapped[str] = mapped_column(String(50))     # category | unit | routing | user ...
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
