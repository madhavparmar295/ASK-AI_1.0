"""Measure the classifier on a labelled file.

    python -m grievance_app.services.classifier_eval tests/data/classifier_samples.csv

File format (separator |):   category|text|flags      flags: C = confidential, U = urgent, CU = both.
Add real sentences from students; the starter file was written by the developers, so the score on it is
optimistic. The score on sentences the keywords were NOT written from is the one to trust.
"""
import csv
import sys
from collections import Counter

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Category
from .classifier import classify

CODES = {
    "HOS": "Hostel and housing", "INF": "Campus infrastructure", "IT": "IT and network", "ACA": "Academics",
    "EXM": "Examinations", "FEE": "Fees and accounts", "SCH": "Scholarships and documents", "LIB": "Library",
    "TRN": "Transport", "MES": "Mess and canteen", "CON": "Harassment, ragging, discrimination, safety",
    "OTH": "Other",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def evaluate(db, rows):
    total = hits = 0
    conf_expected = conf_found = conf_false = non_conf = 0
    urg_expected = urg_found = 0
    per_cat, misses = Counter(), []
    for r in rows:
        want = CODES[r["category"]]
        res = classify(db, r["text"])
        got = res["suggested"]["name"] if res["suggested"] else None
        total += 1
        per_cat[(want, got == want)] += 1
        if got == want:
            hits += 1
        else:
            misses.append((want, got, res["confidence"], r["text"]))
        if "C" in r["flags"]:
            conf_expected += 1
            conf_found += res["confidential"]
        else:
            non_conf += 1
            conf_false += res["confidential"]
        if "U" in r["flags"]:
            urg_expected += 1
            urg_found += res["urgent"]
    return {"total": total, "accuracy": hits / total, "per_category": per_cat, "misses": misses,
            "confidential_recall": conf_found / conf_expected if conf_expected else None,
            "confidential_false_alarm_rate": conf_false / non_conf if non_conf else None,
            "urgent_recall": urg_found / urg_expected if urg_expected else None}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/data/classifier_samples.csv"
    with SessionLocal() as db:
        if not db.scalar(select(Category).limit(1)):
            sys.exit("No categories in the database. Run: python -m grievance_app.seed")
        out = evaluate(db, load(path))
    print(f"Sentences: {out['total']}   Category accuracy: {out['accuracy']:.0%}")
    print(f"Confidential recall: {out['confidential_recall']:.0%}   false alarms: {out['confidential_false_alarm_rate']:.1%}")
    print(f"Urgent recall: {out['urgent_recall']:.0%}")
    print("\nMisses (expected -> got, confidence):")
    for want, got, conf, text in out["misses"]:
        print(f"  {want} -> {got} ({conf}): {text}")
