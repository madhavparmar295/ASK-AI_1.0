from sqlalchemy import func, select

from grievance_app.models import Category, Routing, Unit, User
from grievance_app.seed import ROUTES, seed


def test_seed_counts(db_session, world):
    assert db_session.scalar(select(func.count()).select_from(Category)) == 12
    assert db_session.scalar(select(func.count()).select_from(Routing)) == len(ROUTES)
    assert db_session.scalar(select(func.count()).select_from(Unit)) == 8


def test_seed_is_idempotent(db_session, world):
    before = db_session.scalar(select(func.count()).select_from(User))
    seed(db_session)
    seed(db_session)
    assert db_session.scalar(select(func.count()).select_from(User)) == before
    assert db_session.scalar(select(func.count()).select_from(Routing)) == len(ROUTES)


def test_every_category_has_a_default_route(db_session, world):
    for cat in world["categories"].values():
        default = db_session.scalar(select(Routing).where(
            Routing.category_id == cat.id, Routing.unit_id.is_(None)))
        assert default is not None, cat.name
