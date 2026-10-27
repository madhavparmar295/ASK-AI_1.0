import threading
import time

_buckets: dict[str, dict] = {}
_lock = threading.Lock()


DEFAULT_CAPACITY = 20  # max tokens held at once
DEFAULT_REFILL_RATE = 5  # tokens added per second


def _get_bucket(bucket: str) -> dict:
    if bucket not in _buckets:
        _buckets[bucket] = {
            "tokens": DEFAULT_CAPACITY,
            "last_refill": time.monotonic(),
        }
    return _buckets[bucket]


def try_acquire(
    bucket: str,
    capacity: int = DEFAULT_CAPACITY,
    refill_rate: float = DEFAULT_REFILL_RATE,
) -> bool:
    """
    Non-blocking token acquisition for request paths.

    The blocking variant below is right for background ingestion, which can afford to
    wait. A request cannot: it must be told immediately that it is over the limit, so
    this returns False instead of sleeping.
    """
    with _lock:
        state = _get_bucket(bucket)
        now = time.monotonic()
        elapsed = now - state["last_refill"]
        state["tokens"] = min(capacity, state["tokens"] + elapsed * refill_rate)
        state["last_refill"] = now

        if state["tokens"] >= 1:
            state["tokens"] -= 1
            return True
        return False


def retry_after_seconds(bucket: str, refill_rate: float = DEFAULT_REFILL_RATE) -> float:
    """Seconds until the bucket holds one token, for a Retry-After header."""
    with _lock:
        state = _buckets.get(bucket)
        if not state:
            return 0.0
        deficit = max(0.0, 1.0 - state["tokens"])
        if refill_rate <= 0:
            return float(DEFAULT_CAPACITY)
        return round(deficit / refill_rate, 1)


def acquire_token(
    bucket: str,
    capacity: int = DEFAULT_CAPACITY,
    refill_rate: float = DEFAULT_REFILL_RATE,
) -> None:
    """Blocks (briefly) until a token is available for the given bucket."""
    while True:
        with _lock:
            state = _get_bucket(bucket)
            now = time.monotonic()
            elapsed = now - state["last_refill"]
            state["tokens"] = min(capacity, state["tokens"] + elapsed * refill_rate)
            state["last_refill"] = now

            if state["tokens"] >= 1:
                state["tokens"] -= 1
                return

        time.sleep(0.1)
