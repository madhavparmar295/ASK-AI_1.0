"""Shared definitions: roles, statuses and the legal status transitions.

These are part of the team contract. Later stages import them; do not
redefine them elsewhere.
"""


class Role:
    STUDENT = "student"
    STAFF = "staff"
    OFFICER = "officer"   # designated officer for confidential tickets
    ADMIN = "admin"
    ALL = (STUDENT, STAFF, OFFICER, ADMIN)


class Status:
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    NEEDS_INFO = "NEEDS_INFO"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

    ALL = (ASSIGNED, IN_PROGRESS, ESCALATED, NEEDS_INFO, RESOLVED, CLOSED, CANCELLED)
    # tickets with a running deadline (the escalation job looks at these)
    CLOCK_RUNNING = (ASSIGNED, IN_PROGRESS, ESCALATED)
    OPEN = (ASSIGNED, IN_PROGRESS, ESCALATED, NEEDS_INFO)
    FINAL = (CLOSED, CANCELLED)


class UnitType:
    HOSTEL = "hostel"
    DEPARTMENT = "department"
    BUILDING = "building"
    MESS = "mess"
    CAMPUS = "campus"
    ALL = (HOSTEL, DEPARTMENT, BUILDING, MESS, CAMPUS)


# Legal status transitions (from the lifecycle diagram).
# Additions to the original diagram: ESCALATED -> NEEDS_INFO (an escalated handler can ask the
# student) and ESCALATED -> ESCALATED (escalating again to the next level).

FALLBACK_CATEGORY = "Other"   # unmatched tickets use this category's default route
TRANSITIONS = {
    Status.ASSIGNED: {Status.IN_PROGRESS, Status.ESCALATED, Status.NEEDS_INFO,
                      Status.RESOLVED, Status.CANCELLED},
    Status.IN_PROGRESS: {Status.ESCALATED, Status.NEEDS_INFO, Status.RESOLVED,
                         Status.CANCELLED},
    Status.ESCALATED: {Status.ESCALATED, Status.IN_PROGRESS, Status.NEEDS_INFO,
                       Status.RESOLVED, Status.CANCELLED},   # ESCALATED -> ESCALATED = next level
    Status.NEEDS_INFO: {Status.IN_PROGRESS, Status.CLOSED, Status.CANCELLED},
    Status.RESOLVED: {Status.CLOSED, Status.ASSIGNED},   # ASSIGNED = student says "not fixed"
    Status.CLOSED: set(),
    Status.CANCELLED: set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())
