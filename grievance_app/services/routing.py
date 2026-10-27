"""Routing: (category, unit) -> who gets the ticket (task T7).

Lookup order:  exact (category, unit)  ->  category default (unit empty)
               ->  the fallback category ("Other") default.
Confidential tickets always use the confidential category's default route,
because only officers may see them.
Inactive staff are skipped: the next level takes the ticket.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import FALLBACK_CATEGORY, Role
from ..models import Category, Routing, User
from .errors import ServiceError


@dataclass
class RouteChoice:
    route: Routing
    level: int          # level whose person takes the ticket (0 normally)
    assignee: User


def _default_route(db: Session, category_id) -> Optional[Routing]:
    return db.scalar(select(Routing).where(Routing.category_id == category_id,
                                           Routing.unit_id.is_(None)))


def _levels(route: Routing):
    return [(0, route.level0_user_id), (1, route.level1_user_id), (2, route.level2_user_id)]


def first_active_level(db: Session, route: Routing, start: int = 0, officers_only: bool = False):
    """First active person at level >= start, as (level, user) or None."""
    for level, uid in _levels(route):
        if level < start or uid is None:
            continue
        user = db.get(User, uid)
        if user is not None and user.active and (not officers_only or user.role == Role.OFFICER):
            return level, user
    return None


def next_level(db: Session, route: Optional[Routing], current_level: int, officers_only: bool = False):
    """The next active person above current_level, as (level, user) or None.

    officers_only=True is used for confidential tickets: they never go to non-officers.
    """
    if route is None:
        return None
    return first_active_level(db, route, start=current_level + 1, officers_only=officers_only)


def find_route(db: Session, category: Category, unit_id, confidential: bool) -> RouteChoice:
    route = None
    if confidential:
        conf = db.scalar(select(Category).where(Category.confidential.is_(True),
                                                Category.active.is_(True)).order_by(Category.name))
        route = _default_route(db, conf.id) if conf else None
        if route is None:
            raise ServiceError(503, "Confidential routing is not configured. Contact the admin office.")
    else:
        if unit_id is not None:
            route = db.scalar(select(Routing).where(Routing.category_id == category.id,
                                                    Routing.unit_id == unit_id))
        if route is None:
            route = _default_route(db, category.id)
        if route is None:
            fallback = db.scalar(select(Category).where(Category.name == FALLBACK_CATEGORY))
            route = _default_route(db, fallback.id) if fallback else None
        if route is None:
            raise ServiceError(503, "No route is configured for this category. Contact the admin office.")

    choice = first_active_level(db, route)
    if choice is None:
        raise ServiceError(503, "Nobody active is configured for this route. Contact the admin office.")
    level, user = choice
    if confidential and user.role != Role.OFFICER:
        raise ServiceError(503, "Confidential routing must point to designated officers.")
    return RouteChoice(route=route, level=level, assignee=user)
