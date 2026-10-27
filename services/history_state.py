import os

import redis


_r = redis.Redis.from_url(
    os.getenv(
        "CELERY_BROKER_URL",
        "redis://localhost:6379/0",
    )
)


def get_last_history_id(user_id):
    value = _r.get(f"gmail:history:{user_id}")

    return value.decode() if value else None


def set_last_history_id(user_id, history_id):
    _r.set(
        f"gmail:history:{user_id}",
        str(history_id),
    )