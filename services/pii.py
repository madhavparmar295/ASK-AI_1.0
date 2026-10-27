import hashlib
import hmac
import os
import re

PII_HASH_SALT = os.getenv("PII_HASH_SALT")


ROLL_NUMBER_PATTERN = re.compile(r"\b[A-Z]?\d{2}[\s-]?[A-Z]{2,4}[\s-]?\d{3,4}\b")

GRADE_PATTERN = re.compile(
    r"\bGrade[:\s]+([A-F][+-]?)\b",
    re.IGNORECASE,
)


def _salted_hash(value: str) -> str:
    salt = PII_HASH_SALT or "default_ask_ai_pii_salt_2026"
    return hmac.new(
        key=salt.encode(),
        msg=value.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()[:16]


def hash_identifier(value: str) -> str:
    """
    Used by tests.
    """

    normalized = value.upper().replace(" ", "").replace("-", "")

    return _salted_hash(normalized)


def hash_roll_numbers(text: str) -> str:

    def replace(match: re.Match):

        raw = match.group(0).upper().replace(" ", "").replace("-", "")

        return f"[ROLL:{_salted_hash(raw)}]"

    return ROLL_NUMBER_PATTERN.sub(
        replace,
        text,
    )


def hash_grades(text: str) -> str:

    def replace(match: re.Match):

        grade = match.group(1).upper()

        return f"Grade: [GRADE:{_salted_hash(grade)}]"

    return GRADE_PATTERN.sub(
        replace,
        text,
    )


def apply_pii_protection(text: str) -> str:

    text = hash_roll_numbers(text)

    text = hash_grades(text)

    return text
