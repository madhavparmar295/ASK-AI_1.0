import json
import os

STORE_PATH = os.getenv("DEDUP_STORE_PATH", "processed_message_ids.json")


def _load() -> set:
    if not os.path.exists(STORE_PATH) or os.path.getsize(STORE_PATH) == 0:
        return set()
    try:
        with open(STORE_PATH) as f:
            return set(json.load(f))
    except json.JSONDecodeError:
        return set()


def _save(ids: set) -> None:
    with open(STORE_PATH, "w") as f:
        json.dump(list(ids), f)


def is_already_processed(message_id: str) -> bool:
    return message_id in _load()


def mark_processed(message_id: str) -> None:
    ids = _load()
    ids.add(message_id)
    _save(ids)
