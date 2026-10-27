"""
Load test for the question path.

Two modes, because they answer different questions:

    --mode pipeline   (default) drives retrieval directly: rewrite, dense search,
                      hybrid fusion, rerank, neighbour expansion. No LLM calls, so it
                      can be run freely, and it is the path whose latency and
                      correctness this work changed.
    --mode http       drives POST /query/ask against a running server, which also
                      exercises rate limiting, the answer cache and streaming. This
                      calls the LLM once per distinct question, so the questions are
                      deduplicated.

    python load_test_ask.py --questions "when is the mess bill due" "who is the ecell coordinator"
    python load_test_ask.py --concurrency 8 --repeat 5
    python load_test_ask.py --mode http --url http://127.0.0.1:8000

Reports throughput, latency percentiles and error rate, and in http mode the cache
hit rate. Run it before and after a retrieval change: the point is the comparison.
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

DEFAULT_QUESTIONS = [
    "when is the mess bill due",
    "who is the coordinator of the e-cell",
    "what are the hostel allotment rules",
    "vidan savaliya notice",
    "exam schedule for first year",
]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def run_pipeline_once(question: str) -> dict:
    from services.retrieval import retrieve_chunks

    started = time.time()
    matches = retrieve_chunks(question, user_tag="Student")
    return {
        "seconds": time.time() - started,
        "matches": len(matches),
        "top_score": matches[0].get("score") if matches else None,
        "top_doc": (matches[0].get("metadata") or {}).get("doc_id") if matches else None,
        "error": None,
    }


def run_http_once(url: str, question: str, email: str, session_id: str, timeout: float) -> dict:
    import requests

    started = time.time()
    try:
        response = requests.post(
            f"{url.rstrip('/')}/query/ask",
            json={"question": question, "user_email": email, "session_id": session_id},
            timeout=timeout,
        )
    except Exception as exc:
        return {"seconds": time.time() - started, "matches": 0, "error": str(exc)[:120], "cache": None, "status": None}

    elapsed = time.time() - started
    if response.status_code != 200:
        return {
            "seconds": elapsed,
            "matches": 0,
            "error": f"HTTP {response.status_code}: {response.text[:120]}",
            "cache": response.headers.get("X-Cache"),
            "status": response.status_code,
        }

    body = response.json()
    return {
        "seconds": elapsed,
        "matches": len(body.get("sources") or []),
        "grounded": body.get("grounded"),
        "error": None,
        "cache": response.headers.get("X-Cache"),
        "status": 200,
    }


def summarize(results: list[dict], label: str, mode: str) -> dict:
    latencies = [result["seconds"] for result in results]
    errors = [result for result in results if result.get("error")]
    empty = [result for result in results if not result.get("error") and result["matches"] == 0]

    summary = {
        "mode": label,
        "requests": len(results),
        "errors": len(errors),
        "empty_results": len(empty),
        "throughput_rps": round(len(results) / sum(latencies), 2) if sum(latencies) else 0,
        "latency_p50_ms": round(percentile(latencies, 0.5) * 1000, 1),
        "latency_p95_ms": round(percentile(latencies, 0.95) * 1000, 1),
        "latency_max_ms": round(max(latencies) * 1000, 1) if latencies else 0,
        "latency_mean_ms": round(statistics.fmean(latencies) * 1000, 1) if latencies else 0,
    }

    cache_hits = [result for result in results if result.get("cache") == "HIT"]
    if mode == "http":
        summary["cache_hits"] = len(cache_hits)
        summary["cache_hit_rate"] = round(len(cache_hits) / len(results), 3) if results else 0
        grounded = [result for result in results if result.get("grounded") is not None]
        if grounded:
            summary["grounded_rate"] = round(
                sum(1 for result in grounded if result["grounded"]) / len(grounded), 3
            )

    if errors:
        summary["error_examples"] = [error["error"] for error in errors[:3]]

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test the question path.")
    parser.add_argument("--mode", choices=["pipeline", "http"], default="pipeline")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="student@iitj.ac.in")
    parser.add_argument("--questions", nargs="*", default=DEFAULT_QUESTIONS)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=2, help="times each question is asked")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    if args.mode == "http":
        import requests  # noqa: F401  validate the dependency up front

    work = [question for _ in range(args.repeat) for question in args.questions]
    results: list[dict] = []
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for index, question in enumerate(work):
            session_id = f"loadtest-{index // max(1, len(args.questions))}"
            if args.mode == "http":
                futures[pool.submit(run_http_once, args.url, question, args.email, session_id, args.timeout)] = question
            else:
                futures[pool.submit(run_pipeline_once, question)] = question

        for future in as_completed(futures):
            question = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"seconds": 0.0, "matches": 0, "error": str(exc)[:120]}
            result["question"] = question
            results.append(result)
            status = result.get("error") or f"{result['matches']} chunks in {result['seconds']*1000:.0f} ms"
            print(f"  {question[:48]:<48} {status}")

    summary = summarize(results, args.mode, args.mode)
    summary["wall_seconds"] = round(time.time() - started, 1)
    print(json.dumps(summary, indent=2))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary, "results": results}, handle, indent=2)
        print(f"[LoadTest] Wrote {args.json_path}")

    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
