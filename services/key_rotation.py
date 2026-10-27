import itertools
import os

_GMAIL_ACCOUNTS = os.getenv("GMAIL_ACCOUNT_IDS", "").split(",")
_account_cycle = itertools.cycle(_GMAIL_ACCOUNTS) if _GMAIL_ACCOUNTS else None
_lock_free_next = None


def next_gmail_account_id() -> str:
    if not _account_cycle:
        raise RuntimeError("GMAIL_ACCOUNT_IDS is not configured")
    return next(_account_cycle)
