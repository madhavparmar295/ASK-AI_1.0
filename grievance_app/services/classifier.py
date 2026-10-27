"""Keyword classifier (task T10). Rules only, no machine learning.

It SUGGESTS a category and raises two flags (confidential, urgent). It never decides:
the student confirms the category, and flags can only be raised, never lowered, by the system.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import FALLBACK_CATEGORY
from ..models import Category
from .keywords import CONFIDENTIAL_TERMS, URGENT_TERMS

_TOKEN = re.compile(r"[^\s.,;:!?()\[\]{}\"'“”‘’<>|\\/\-_=+@#$%^&~`]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFKC", text or "").lower())


@dataclass(frozen=True)
class Rule:
    kind: str       # word | prefix | phrase | phrase_prefix
    key: str
    weight: int


def parse_keywords(raw: Optional[str]) -> list[Rule]:
    rules = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        weight = None
        head, sep, tail = item.rpartition(":")
        if sep and tail.strip().isdigit():
            item, weight = head.strip(), int(tail)
        star = item.endswith("*")
        tokens = tokenize(item.rstrip("*"))
        if not tokens:
            continue
        key = " ".join(tokens)
        if len(tokens) == 1:
            kind = "prefix" if star else "word"
        else:
            kind = "phrase_prefix" if star else "phrase"
        rules.append(Rule(kind, key, weight if weight is not None else (1 if len(tokens) == 1 else 2)))
    return rules


def _matches(rule: Rule, tokens: list[str], token_set: set[str], joined: str) -> bool:
    if rule.kind == "word":
        return rule.key in token_set
    if rule.kind == "prefix":
        return any(t.startswith(rule.key) for t in tokens)
    if rule.kind == "phrase":
        return f" {rule.key} " in joined
    return f" {rule.key}" in joined      # phrase_prefix


def score(rules: list[Rule], text: str) -> int:
    tokens = tokenize(text)
    token_set, joined = set(tokens), " " + " ".join(tokens) + " "
    return sum(r.weight for r in rules if _matches(r, tokens, token_set, joined))


_CONF_RULES = parse_keywords(CONFIDENTIAL_TERMS)
_URGENT_RULES = parse_keywords(URGENT_TERMS)


def flags(text: str) -> dict:
    return {"confidential": score(_CONF_RULES, text) > 0, "urgent": score(_URGENT_RULES, text) > 0}


def classify(db: Session, text: str) -> dict:
    """Return the suggested category, alternatives, confidence and flags."""
    cats = db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
    scored = []
    for c in cats:
        s = score(parse_keywords(c.keywords), text)
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: (-x[0], x[1].name))

    if not scored:
        other = next((c for c in cats if c.name == FALLBACK_CATEGORY), None)
        suggested, confidence, top, second = other, "none", 0, 0
    else:
        top, suggested = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        if top >= 3 and top >= second + 2:
            confidence = "high"
        elif top >= 2 and top > second:
            confidence = "medium"
        else:
            confidence = "low"
    f = flags(text)
    if f["confidential"]:
        # The ticket will be routed to the confidential category anyway, so suggest it.
        conf = [(sc, c) for sc, c in scored if c.confidential] or [(0, c) for c in cats if c.confidential]
        if conf:
            suggested = conf[0][1]
            confidence = "high" if conf[0][0] >= 3 else "medium"
            scored = [(sc, c) for sc, c in [(top, suggested)] + [x for x in scored if x[1].id != suggested.id]]
    return {
        "suggested": {"id": suggested.id, "name": suggested.name} if suggested else None,
        "confidence": confidence,
        "alternatives": [{"id": c.id, "name": c.name} for _, c in scored if suggested is None or c.id != suggested.id][:2],
        "confidential": f["confidential"],
        "urgent": f["urgent"],
    }
