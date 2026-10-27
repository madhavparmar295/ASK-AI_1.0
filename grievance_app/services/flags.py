"""Flags used when a ticket is created (Stage 2 calls detect_flags).

The system may RAISE confidential/urgent, never lower them.
"""
from .classifier import flags


def detect_flags(text: str) -> dict:
    return flags(text)
