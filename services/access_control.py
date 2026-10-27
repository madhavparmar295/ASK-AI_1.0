import re

RESTRICTED_KEYWORDS = [
    "mess bill",
    "backlog",
    "cgpa",
    "sgpa",
    "grade",
    "roll no",
    "roll number",
    "attendance shortage",
    "fee due",
    "hostel allotment",
]


ROLL_NUMBER_HINT = re.compile(r"\b[A-Z]?\d{2}[\s-]?[A-Z]{2,4}[\s-]?\d{3,4}\b")


def classify_access_level(text: str) -> str:

    lowered = text.lower()

    if any(keyword in lowered for keyword in RESTRICTED_KEYWORDS):
        return "iitj_restricted"

    if ROLL_NUMBER_HINT.search(text):
        return "iitj_restricted"

    return "public"


def resolve_user_tag(email_domain: str) -> str:
    """
    Student -> iitj.ac.in

    Everyone else -> Guest
    """

    return "Student" if email_domain.lower() == "iitj.ac.in" else "Guest"


def allowed_access_levels(user_tag: str) -> list[str]:

    if user_tag == "Student":
        return [
            "public",
            "iitj_restricted",
        ]

    return [
        "public",
    ]
