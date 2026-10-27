"""
Live check: does hybrid retrieval find the name-typo cases now?

Runs against the real Pinecone index, the real FTS5 index and the real LLM, and
prints the top sources for each question plus the answer the model produces, so the
names can be checked in the output rather than inferred from a score.

    python verify_hybrid_live.py
"""

import os
import sys

# The corpus contains emoji and non-Latin text; a cp1252 Windows console would abort
# the run half way through printing a source.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from services import lexical_index, rag  # noqa: E402
from services.llm import LLMError  # noqa: E402
from services.retrieval import retrieve_chunks  # noqa: E402

# (question, access tag, names the answer must contain)
CASES = [
    ("who is the corrdinator of e cell", "Student", ["Vidhan", "Savaliya"]),
    ("who are the coordinators of raid", "Student", ["Suhani", "Soham", "Abhinav"]),
    ("vidhan savaliya", "Student", ["Vidhan"]),
]


def main() -> int:
    print("lexical index:", lexical_index.stats(), flush=True)

    failures = 0
    for question, tag, expected in CASES:
        print("\n" + "=" * 78, flush=True)
        print(f"Q: {question}   (tag={tag}, expect {expected})", flush=True)

        matches = retrieve_chunks(question, tag)
        print(f"retrieved {len(matches)} chunks", flush=True)
        for match in matches[:6]:
            metadata = match.get("metadata") or {}
            text = (metadata.get("text") or "").replace("\n", " ")
            print(
                f"  - {match.get('score', 0):.4f} {metadata.get('source_type')} "
                f"{match.get('id')} :: {text[:110]}",
                flush=True,
            )

        context = [
            {
                "text": (match.get("metadata") or {}).get("text", ""),
                "score": match.get("score", 0.0),
                "doc_id": (match.get("metadata") or {}).get("doc_id", ""),
                "access_level": (match.get("metadata") or {}).get("access_level", "public"),
                "sender": (match.get("metadata") or {}).get("sender", ""),
                "subject": (match.get("metadata") or {}).get("subject", ""),
                "date": (match.get("metadata") or {}).get("date", ""),
                "source_type": (match.get("metadata") or {}).get("source_type", ""),
                "filename": (match.get("metadata") or {}).get("filename", ""),
                "source": (match.get("metadata") or {}).get("source", ""),
            }
            for match in matches
        ]

        try:
            result = rag.answer_question(question, context, [])
        except LLMError as exc:
            # Provider quota, not a retrieval problem: report it as a licence to retry
            # rather than as a failed retrieval check.
            failures += 1
            print(f"  PROVIDER UNAVAILABLE: {str(exc)[:300]}", flush=True)
            continue

        print(f"answer ({result['latency_ms']}ms, grounded={result['grounded']}, cited={result['cited_sources']}):", flush=True)
        print("  " + result["answer"].replace("\n", "\n  "), flush=True)

        missing = [name for name in expected if name.lower() not in result["answer"].lower()]
        if missing:
            failures += 1
            print(f"  FAIL: answer does not mention {missing}", flush=True)
        else:
            print("  OK: expected names present", flush=True)

    print("\n" + "=" * 78)
    print(f"{len(CASES) - failures}/{len(CASES)} cases produced the expected names")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
