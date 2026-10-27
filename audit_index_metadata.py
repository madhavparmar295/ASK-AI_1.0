"""
Audit the metadata and text quality of everything in the vector store.

Retrieval can only be as good as the corpus. This report answers the questions that
have to be answered before tuning search further:

    * how much of the index is missing the metadata that makes a chunk citable
      (doc_id, filename, subject, sender, access level)?
    * how much of the stored text is unreadable OCR? A scanned page whose font has no
      usable text encoding yields Latin letters that spell nothing, and no amount of
      retrieval work will make that text answer a question. Such chunks are reported
      as unreadable, and separately as recoverable-by-rotation when reading them
      upside down produces more English.
    * is the same content indexed under several document IDs?
    * are chunk positions complete (no missing middle chunks)?
    * is the access-level distribution what it should be?

    python audit_index_metadata.py                      # full scan
    python audit_index_metadata.py --limit 2000          # sample
    python audit_index_metadata.py --report audit.md     # write the markdown report
    python audit_index_metadata.py --json audit.json     # also write raw counts
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from services.index_scan import is_fetchable_id, iter_records  # noqa: E402

WORD_RE = re.compile(r"[A-Za-z]{2,}")
HEADER_RE = re.compile(r"^\[[^\]]{0,300}\]\s*\n")

# Frequent English words. A chunk that contains almost none of these is not readable
# English, whatever else it contains - which is the signal for a failed OCR pass.
COMMON_WORDS = frozenset(
    """
    the be to of and a in that have i it for not on with he as you do at this but his by from they we say her she or
    an will my one all would there their what so up out if about who get which go me when make can like time no just
    him know take people into year your good some could them see other than then now look only come its over think also
    back after use two how our work first well way even new want because any these give day most us is are was were been
    has had did does done being am shall should may might must can cannot into within without before during between under
    above below again further once here where why while each few more both own same such nor too very s t don now total
    students student college university institute course courses exam exams form apply application fees fee date dates
    register registration notice circular office department hostel mess room list final result results academic semester
    approved approval request required submitted submit available contact email mail phone number detail details address
    committee meeting schedule report name roll sign signature authority director dean professor dr mr ms mrs please
    dear sir madam kind regards thanks thank including include included subject matter campus event events club clubs
    """.split()
)

# 180-degree glyph swaps, used to test whether a page was scanned upside down.
ROTATE_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎzᗡꓭƆᗡƎℲ⅁HIſꓘ˥WNOԀÒᴚS⊥∩ΛMX⅄Z0ƖᄅƐㄣϛ9ㄥ86",
)


def _englishness(text: str) -> float:
    """Share of words that are common English words."""
    words = [word.lower() for word in WORD_RE.findall(text)]
    if len(words) < 15:
        return 1.0  # too short to judge; do not flag
    hits = sum(1 for word in words if word in COMMON_WORDS)
    return hits / len(words)


def _rotated(text: str) -> str:
    return text[::-1].translate(ROTATE_MAP)


def _chunk_index(vector_id: str, doc_id: str) -> int:
    suffix = str(vector_id)[len(str(doc_id)) + 1 :] if doc_id else ""
    try:
        return int(suffix)
    except ValueError:
        return -1


def audit(
    limit: int | None = None,
    unreadable_threshold: float = 0.06,
    recover_unfetchable: bool = True,
) -> dict:
    started = time.time()

    documents: dict[str, dict] = {}
    access_levels: Counter = Counter()
    source_types: Counter = Counter()
    missing = Counter()
    text_hashes: dict[int, list[str]] = defaultdict(list)
    size_buckets: Counter = Counter()
    total_chunks = 0
    total_chars = 0
    unreadable = 0
    recoverable_by_rotation = 0
    unfetchable_ids = 0
    unreadable_examples: list[dict] = []
    duplicate_examples: list[dict] = []

    for batch in iter_records(
        batch_size=100,
        limit=limit,
        recover_unfetchable=recover_unfetchable,
    ):
        for record in batch:
            metadata = record.get("metadata") or {}
            total_chunks += 1
            if not is_fetchable_id(record["id"]):
                # These are readable only through a query, not through fetch, so they are
                # counted separately: a scan that skipped them would understate the corpus.
                unfetchable_ids += 1

            text = str(metadata.get("text") or "")
            text = HEADER_RE.sub("", text)
            total_chars += len(text)

            doc_id = metadata.get("doc_id") or ""
            if not doc_id:
                missing["doc_id"] += 1
            if not text.strip():
                missing["text"] += 1
            if not metadata.get("access_level"):
                missing["access_level"] += 1
            if not metadata.get("source_type"):
                missing["source_type"] += 1

            source_type = str(metadata.get("source_type") or "unknown")
            source_types[source_type] += 1
            access_levels[str(metadata.get("access_level") or "missing")] += 1

            if source_type in ("email", "email_attachment", "gmail"):
                if not metadata.get("subject"):
                    missing["subject"] += 1
                if not metadata.get("sender"):
                    missing["sender"] += 1
                if not metadata.get("filename"):
                    missing["filename"] += 1

            # Chunk sizes: the old 500-character window shows up as a spike at 500.
            if text:
                if len(text) < 200:
                    size_buckets["<200"] += 1
                elif len(text) < 800:
                    size_buckets["200-800"] += 1
                elif len(text) < 1600:
                    size_buckets["800-1600"] += 1
                else:
                    size_buckets[">=1600"] += 1

            entry = documents.setdefault(
                doc_id,
                {
                    "chunks": 0,
                    "indices": set(),
                    "access_levels": set(),
                    "source_types": set(),
                    "filenames": set(),
                    "subjects": set(),
                },
            )
            entry["chunks"] += 1
            entry["indices"].add(_chunk_index(record["id"], doc_id))
            entry["access_levels"].add(str(metadata.get("access_level") or ""))
            entry["source_types"].add(source_type)
            if metadata.get("filename"):
                entry["filenames"].add(str(metadata["filename"])[:80])
            if metadata.get("subject"):
                entry["subjects"].add(str(metadata["subject"])[:80])

            # Duplicate content detection. Hash in Python (not Redis): this is
            # deliberately a read-only report, and it must work with Redis down.
            if len(text) > 120:
                digest = hash(re.sub(r"\s+", " ", text).strip().casefold())
                text_hashes[digest].append(doc_id)

            score = _englishness(text)
            if score < unreadable_threshold:
                rotated_score = _englishness(_rotated(text))
                if rotated_score > max(score * 3, 0.06):
                    recoverable_by_rotation += 1
                    kind = "recoverable_by_rotation"
                else:
                    unreadable += 1
                    kind = "unreadable"

                if len(unreadable_examples) < 12:
                    unreadable_examples.append(
                        {
                            "kind": kind,
                            "doc_id": doc_id,
                            "filename": str(metadata.get("filename") or "")[:60],
                            "englishness": round(score, 3),
                            "rotated_englishness": round(rotated_score, 3),
                            "sample": text[:110].replace("\n", " "),
                        }
                    )

    duplicate_chunks = 0
    duplicate_groups = 0
    for digest, doc_ids in text_hashes.items():
        unique = set(doc_ids)
        if len(unique) > 1:
            duplicate_groups += 1
            duplicate_chunks += sum(1 for doc_id in doc_ids if doc_id in unique) - 1
            if len(duplicate_examples) < 10:
                duplicate_examples.append(
                    {"documents": sorted(unique)[:4], "chunks_in_group": len(doc_ids)}
                )

    conflicting_access = [
        doc_id
        for doc_id, entry in documents.items()
        if len({level for level in entry["access_levels"] if level}) > 1
    ]

    gapped_documents = []
    for doc_id, entry in documents.items():
        indices = {index for index in entry["indices"] if index >= 0}
        if not indices:
            continue
        expected = set(range(min(indices), max(indices) + 1))
        if expected - indices:
            gapped_documents.append({"doc_id": doc_id, "missing": len(expected - indices)})

    report = {
        "scanned_chunks": total_chunks,
        "documents": len(documents),
        "average_chunk_chars": round(total_chars / total_chunks, 1) if total_chunks else 0,
        "chunk_size_buckets": dict(size_buckets.most_common()),
        "access_levels": dict(access_levels.most_common()),
        "source_types": dict(source_types.most_common(15)),
        "missing_fields": dict(missing.most_common()),
        "unreadable_chunks": unreadable,
        "recoverable_by_rotation": recoverable_by_rotation,
        "unfetchable_ids": unfetchable_ids,
        "unfetchable_recovered": recover_unfetchable,
        "duplicate_text_groups": duplicate_groups,
        "duplicate_chunks": duplicate_chunks,
        "documents_with_conflicting_access_levels": len(conflicting_access),
        "documents_with_missing_chunk_indices": len(gapped_documents),
        "unreadable_examples": unreadable_examples,
        "duplicate_examples": duplicate_examples,
        "gap_examples": gapped_documents[:10],
        "conflicting_access_examples": conflicting_access[:10],
        "seconds": round(time.time() - started, 1),
        "limit": limit,
    }
    return report


def _markdown(report: dict) -> str:
    def table(counts: dict, key: str = "count") -> str:
        if not counts:
            return "_none_\n"
        rows = "\n".join(f"| {name} | {value} |" for name, value in counts.items())
        return f"| value | {key} |\n| --- | --- |\n{rows}\n"

    readable = report["scanned_chunks"] - report["unreadable_chunks"] - report["recoverable_by_rotation"]
    share = (report["unreadable_chunks"] / report["scanned_chunks"] * 100) if report["scanned_chunks"] else 0

    lines = [
        "# Index metadata and text-quality audit",
        "",
        f"Scanned {report['scanned_chunks']} chunks across {report['documents']} documents "
        f"in {report['seconds']}s.",
        "",
        "## Headline",
        "",
        f"- Unreadable OCR chunks: **{report['unreadable_chunks']}** ({share:.1f}%) - "
        "no retrieval change can make these answerable; they need re-OCR or removal.",
        f"- Recoverable by rotation: **{report['recoverable_by_rotation']}** - the page was "
        "scanned upside down, so re-running OCR after rotating it recovers the text.",
        f"- IDs the fetch endpoint cannot return: **{report.get('unfetchable_ids', 0)}** - "
        "read back through a query instead; they hold attachment text and would be "
        "missing from any scan that only used fetch."
        + (
            ""
            if report.get("unfetchable_recovered", True)
            else " This run used --no-recover, so the count is zero by construction."
        ),
        f"- Readable chunks: {readable}.",
        f"- Exact duplicate text across different documents: **{report['duplicate_chunks']}** chunks "
        f"in {report['duplicate_text_groups']} groups.",
        f"- Documents with conflicting access levels: **{report['documents_with_conflicting_access_levels']}**.",
        f"- Documents with missing chunk positions (gaps): **{report['documents_with_missing_chunk_indices']}**.",
        f"- Average chunk size: {report['average_chunk_chars']} characters.",
        "",
        "## Chunk sizes",
        "",
        table(report["chunk_size_buckets"], "chunks"),
        "## Missing metadata fields",
        "",
        table(report["missing_fields"], "chunks"),
        "## Access levels",
        "",
        table(report["access_levels"], "chunks"),
        "## Source types",
        "",
        table(report["source_types"], "chunks"),
    ]

    if report["unreadable_examples"]:
        lines += ["## Unreadable text examples", ""]
        for example in report["unreadable_examples"]:
            lines.append(
                f"- `{example['kind']}` doc `{example['doc_id']}` file `{example['filename']}` "
                f"englishness {example['englishness']} (rotated {example['rotated_englishness']}): "
                f"{example['sample']}"
            )
        lines.append("")

    if report["duplicate_examples"]:
        lines += ["## Duplicate groups", ""]
        for example in report["duplicate_examples"]:
            lines.append(f"- {example['chunks_in_group']} chunks shared by {example['documents']}")
        lines.append("")

    if report["gap_examples"]:
        lines += ["## Documents with chunk gaps", ""]
        for example in report["gap_examples"]:
            lines.append(f"- `{example['doc_id']}`: {example['missing']} missing chunk(s)")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit vector-store metadata and text quality.")
    parser.add_argument("--limit", type=int, default=None, help="only scan the first N vectors")
    parser.add_argument("--report", default="index_metadata_audit.md", help="markdown output path")
    parser.add_argument("--json", dest="json_path", default=None, help="raw counts output path")
    parser.add_argument("--threshold", type=float, default=0.06, help="englishness cut-off")
    parser.add_argument(
        "--no-recover",
        action="store_true",
        help="skip the query fallback for vector IDs fetch cannot read (faster, partial)",
    )
    args = parser.parse_args()

    report = audit(
        limit=args.limit,
        unreadable_threshold=args.threshold,
        recover_unfetchable=not args.no_recover,
    )

    print(json.dumps({key: value for key, value in report.items() if not key.endswith("examples")}, indent=2))

    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write(_markdown(report))
    print(f"[Audit] Wrote {args.report}")

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        print(f"[Audit] Wrote {args.json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
