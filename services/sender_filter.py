from email.utils import parseaddr


ALLOWED_DOMAIN = "iitj.ac.in"


def is_allowed_sender(from_header: str) -> bool:
    _, addr = parseaddr(from_header or "")

    if addr.count("@") != 1:
        return False

    domain = addr.rsplit("@", 1)[1].lower().strip()

    return (
        domain == ALLOWED_DOMAIN
        or domain.endswith("." + ALLOWED_DOMAIN)
    )


def fetch_from_header(gmail, message_id: str) -> str:
    message = (
        gmail.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From"],
        )
        .execute()
    )

    for header in message.get("payload", {}).get("headers", []):
        if header.get("name", "").lower() == "from":
            return header.get("value", "")

    return ""