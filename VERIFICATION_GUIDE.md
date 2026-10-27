# How to check everything

A stepwise pass over the whole system, cheapest and least invasive first. Every step
lists the command, what a good result looks like, and what it means when it is not.

Steps 1-6 need no keys and no network. Steps 7-9 need Pinecone (and Groq for the answer).
Step 10-13 need a running API. Step 14-16 need Gmail/Redis/Postgres and are noted as such.

The results recorded under each step are what this repository actually produced on
2026-10-15, so you have a baseline to compare against.

---

## Step 0 - Know what "working" means

| Component | Expected state |
| --- | --- |
| Vector store | Pinecone `ask-ai`, `ready`, ~33,781 vectors |
| Keyword index | `lexical_index.db`, ~33,736 rows, 4,544 documents |
| LLM | Groq key set (or Ollama running) |
| Database | PostgreSQL for users/chat/feedback (optional; SQLite works for a local check) |
| Redis | optional: answer cache falls back in-process; dedup/usage fail open |

---

## Phase 1 - Offline checks (no keys, no network)

### 1. The test suite

```bash
python -m pytest tests/ -q
```

Good: `111 passed`, exit status `0`.
Bad: any failure - read the assertion; the suite pins Pinecone, Groq, Postgres and Redis
to fakes or unreachable addresses, so a failure is a code problem, not an environment
problem.

### 2. Syntax and imports across the tree

```bash
python -m compileall -q . && echo "compile ok"
```

Good: `compile ok`, exit `0`. This is what caught `sync_new_emails.py` having two
statements on one line, which made the script unrunnable.

### 3. Configuration matches the code

```bash
python - <<'EOF'
import pathlib, re
root = pathlib.Path('.')
skip = {'frontend', '.git', 'node_modules', '__pycache__', '.freebuff', 'storage'}
used = set()
for path in root.rglob('*.py'):
    if any(part in skip for part in path.parts):
        continue
    used |= set(re.findall(r'getenv\(\s*["\']([A-Z0-9_]+)["\']', path.read_text(encoding='utf-8', errors='ignore')))
doc = set(re.findall(r'^([A-Z0-9_]+)=', pathlib.Path('.env.example').read_text(encoding='utf-8'), re.M))
print("documented but unused:", sorted(doc - used))
print("used but undocumented:", sorted(used - doc))
EOF
```

Good: `documented but unused` is empty, and the only `used but undocumented` entry is
`GROK_API_KEY`, which is a deliberate alias read as a fallback for `GROQ_API_KEY`.
Recorded baseline: exactly that.
Bad: a variable the code reads that is absent from the template - a fresh deployment
would silently fall back to a default.

### 4. The image builds

```bash
docker build -t askai:check .
```

Good: build completes. Needs `Dockerfile` (api/worker/beat share one image) and
`tesseract-ocr`/`poppler-utils` present for OCR. This step was **not** run in this
environment - Docker is not installed here - so it is the one command in this guide
without a recorded result.

---

## Phase 2 - Data and index state

### 5. Does the keyword index cover the vector store?

```bash
python -c "import sqlite3;print('rows:', sqlite3.connect('lexical_index.db').execute('select count(*) from chunks').fetchone()[0])"
```

Good: within a few dozen of the vector count (`/health/ready` reports the vector count).
Recorded baseline: **33,736 rows vs 33,781 vectors**.

If it is short, rebuild - it now reads only what is missing, so it resumes:

```bash
python rebuild_lexical_index.py
```

Good: `[Rebuild] Wrote N chunks ... (M read back by query, K already present, 0 skipped)`.
It ends by listing any IDs it could not read at all; expected: 45 image chunks whose
vector duplicates a sibling's. If that list grows, something else is wrong.

### 6. Corpus quality

```bash
python audit_index_metadata.py --report index_metadata_audit.md
```

Good: a report whose headline tells you the unreadable-OCR count (those documents need
re-OCR or removal - no retrieval change can make them answerable), how many pages were
scanned upside down, duplicate text groups, chunk-position gaps, and how many IDs the
fetch endpoint cannot return. Compare the unreadable percentage against the last run
rather than against zero.

`--no-recover` skips the per-ID query fallback and is much faster for a sample, but it
reports the unfetchable count as 0 by construction - the report says so.

---

## Phase 3 - Retrieval and answers, live

### 7. The two questions that used to fail

```bash
python verify_hybrid_live.py
```

Good: `3/3 cases produced the expected names`, exit `0`, and each case prints the sources
behind the answer:

| Question | Answer must contain |
| --- | --- |
| `who is the corrdinator of e cell` | Vidhan Savaliya |
| `who are the coordinators of raid` | Suhani Shah, Soham Wad, Abhinav Kumar |
| `vidhan savaliya` | Vidhan Savaliya |

Recorded baseline: 3/3, answers grounded with 2-4 citations; the multi-source answer took
~12s, the single-source one ~0.7s.

If it prints `PROVIDER UNAVAILABLE`, that is the provider's quota, not retrieval - the
error text names the limit and the wait. The script exits non-zero so you can tell the
difference.

### 8. Is the keyword half actually populated?

```bash
python - <<'EOF'
from dotenv import load_dotenv; load_dotenv('.env')
from services import lexical_index
hits = lexical_index.search("TEM Characterization Requisition Form", allowed_levels=["public", "iitj_restricted"], limit=3)
print(len(hits), "hits"); [print(" ", h["id"], str(h["metadata"].get("chunk_index"))) for h in hits]
EOF
```

Good: hits include the legacy attachment chunk
`19a6d7d0d0b46815:Characterisation Requisition Form -TEM.pdf-0`. That chunk was invisible
to keyword search before the fetch-gap fix, so its presence proves the recovery worked.

### 9. Load and latency

```bash
python load_test_ask.py --mode pipeline --repeat 2        # retrieval + answer, in process
python load_test_ask.py --mode http --url http://127.0.0.1:8010 --concurrency 4
```

Good: every question answered, with per-question latencies and a summary. Compare
`--mode pipeline` (retrieval and generation only) against `--mode http` (adds the API) to
see where time goes.

Recorded for one question: `errors: 0`, `empty_results: 0`, 21 chunks in 14,462 ms. That
number is dominated by the model provider, not by retrieval - check the retrieval log line
for the stage breakdown before blaming the index.

---

## Phase 4 - The API

Start it (any free port):

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

Without PostgreSQL you will see `startup_degraded` in the log with
`"hint": "users, chat history and feedback will fail until the database is reachable"`.
That is expected and the API still answers questions. For a self-contained local check
of the database-backed endpoints, point both URLs at SQLite:

```bash
DATABASE_URL="sqlite:///./check_askai.db" VECTOR_DB_URL="sqlite:///./check_askai.db" \
  python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

Good: the log shows `pgvector_init_skipped` (informational - those tables are legacy) and
then `startup_complete` with `"database": "ready"`.

### 10. Liveness and readiness

```bash
curl -s localhost:8010/health; echo
curl -s localhost:8010/health/ready; echo
```

Good: `/health` is `{"status":"ok",...}` and never touches a dependency. `/health/ready`
reports `"pinecone":{"ok":true,"vectors":33781}`, lists anything broken under `degraded`,
and answers **503 only when Pinecone is unreachable**. A missing database or Redis is a
`degraded` entry, not a 503.

Recorded: `/health/ready` → 200, `degraded: ["database"]`, Pinecone ok with 33,781
vectors.

### 11. Ask a question, twice

```bash
curl -s -i -X POST localhost:8010/query/ask -H 'content-type: application/json' \
  -d '{"question":"who is the corrdinator of e cell","user_email":"you@iitj.ac.in"}'
```

Good, first call: `200`, answer naming **Vidhan Savaliya**, `"grounded": true`,
`"cited_sources"` non-empty, `X-Cache: MISS`, and an `X-Request-ID` you can grep in the
logs. Second call with the same body: `X-Cache: HIT`.

Also worth checking the edges:

```bash
# empty question -> 400
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8010/query/ask \
  -H 'content-type: application/json' -d '{"question":"   ","user_email":"you@iitj.ac.in"}'

# over 2000 characters -> 422
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8010/query/ask \
  -H 'content-type: application/json' -d "{\"question\":\"$(python -c 'print("x"*3000)')\",\"user_email\":\"you@iitj.ac.in\"}"
```

Recorded: 400 and 422 respectively.

### 12. Cache and rate limit

```bash
curl -s localhost:8010/query/cache; echo
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8010/query/cache/clear          # 400
curl -s -X POST 'localhost:8010/query/cache/clear?confirm=true'; echo
```

Good: `/query/cache` reports backend, entries, hits, misses, stores for the answer cache
and the conversation store. Clearing without `confirm=true` is refused.

For the rate limit, send the same question 35 times from one scope - the first costs an
LLM call, the rest are cache hits, and the limiter still counts them:

```bash
for i in $(seq 1 35); do
  curl -s -o /dev/null -w "%{http_code} " -X POST localhost:8010/query/ask \
    -H 'content-type: application/json' \
    -d '{"question":"who are the coordinators of raid","user_email":"ratelimit@iitj.ac.in"}'
done; echo
```

Good: a run of `200`s then `429`s. Check the header once:

```bash
curl -s -D - -o /dev/null -X POST localhost:8010/query/ask -H 'content-type: application/json' \
  -d '{"question":"who are the coordinators of raid","user_email":"ratelimit@iitj.ac.in"}' | grep -i retry-after
```

Recorded: 429 with `Retry-After: 19` after a burst in one scope. The bucket is per
**domain and role**, not per address, so everyone at `iitj.ac.in` shares one.

### 13. Streaming

```bash
curl -sN -X POST localhost:8010/query/ask/stream -H 'content-type: application/json' \
  -d '{"question":"who are the coordinators of raid","user_email":"you@iitj.ac.in"}' | head -20
```

Good: `data:` lines in order - one `sources`, many `token`, then `done` with
`"grounded": true` and `cited_sources`. Recorded: 833 token events, and the streamed text
contained all three coordinator names.

### 14. Database-backed endpoints

```bash
# feedback
curl -s -X POST localhost:8010/feedback -H 'content-type: application/json' \
  -d '{"question":"who is the corrdinator of e cell","rating":"up","user_email":"you@iitj.ac.in","sources":["x"]}'
curl -s localhost:8010/feedback/summary; echo

# an invalid rating is refused
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8010/feedback \
  -H 'content-type: application/json' -d '{"question":"q","rating":"maybe"}'
```

Good: `{"success":true,"id":...}`, then a summary with `up`/`down`/`total`. Recorded:
`{"window_days":30,"up":1,"down":0,"total":1,"satisfaction":1.0}`.

Without a database these answer **503**, which is the documented degraded behaviour.

### 15. Endpoints that must refuse you

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/auth/me                      # 401
curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/chat/api/history/?email=someone@iitj.ac.in
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8010/webhook/gmail \
  -H 'content-type: application/json' -d '{"message":{"data":"e30="}}'                # 401
```

Good: `/auth/me` and the Gmail webhook answer 401 without a token - the webhook checks a
signed token, so an unsigned push is rejected.

Note what is *not* refused: `/chat/api/history/?email=...` returns that address's history
from the client-supplied `email`, and `/query/ask` derives access levels, the rate-limit
bucket and the cache partition from the client-supplied `user_email`. See "What these
checks do not cover" below.

### 16. The whole route map

```bash
curl -s localhost:8010/openapi.json | python -c "import json,sys; print('\n'.join(sorted(json.load(sys.stdin)['paths'])))"
```

Good: 25 paths, matching the routers in `routers/`. Use the interactive docs at
`localhost:8010/docs` for manual poking.

---

## Phase 5 - Background jobs

### 17. Gmail watches (they expire every 7 days)

```bash
python -m jobs.watch_tasks          # renew every mailbox in GMAIL_ACCOUNT_IDS
```

Good: a per-mailbox result line each. Silence after a week means mail simply stops
arriving for that mailbox, which is why this is scheduled.

Recorded: `[Watch] Renewed 1/1 mailboxes.` with
`{'accounts': 1, 'renewed': 1, 'results': {'student@iitj.ac.in': 'ok (history 1051255)'}}`
- so the Gmail credentials and token store in this checkout are live.

### 18. Retention (off by default, dry run first)

```bash
python -m jobs.retention_tasks                  # report only
python -m jobs.retention_tasks --apply          # actually delete
```

Good: a report of what would be deleted, and a refusal to delete more than
`RETENTION_MAX_FRACTION` of the index in one run. `--days` and `--force` exist; reach for
`--force` only deliberately.

Recorded: `nothing_to_delete`, 0 candidates of 33,782 vectors, 31 documents recently
used, and 10,000 email chunks kept because they have no usage data yet - conservative by
design: a chunk with no recorded use is kept, so retention only ever removes what it can
justify.

### 19. Celery

```bash
celery -A jobs.celery_app.celery_app worker --loglevel=INFO
celery -A jobs.celery_app.celery_app beat   --loglevel=INFO
```

Good: the worker registers the email tasks and connects to `CELERY_BROKER_URL`; beat
schedules retention and watch renewal.

### 20. Ingestion scripts

```bash
python -m py_compile sync_new_emails.py index_postgres_to_pinecone.py index_all_storage.py restore_processed_message_ids.py
echo $?
```

Good: `0`. These scripts take `load_dotenv(override=True)`, so they read `.env` even when
you have overridden variables in your shell - worth knowing before you run one against a
live index.

---

### 21. Removing a document

When a document has to go, remove it from both stores - the vector store and the keyword
index:

```bash
python - <<'EOF'
from dotenv import load_dotenv; load_dotenv('.env')
from services import lexical_index
from services.vectorstore import delete_vectors

doc_id = "https://example.com"
print("keyword rows removed:", lexical_index.delete_document(doc_id))
print("vectors requested:", delete_vectors([f"{doc_id}-0"]))
EOF
```

Then clear the answer cache, or a cached answer will keep quoting it:

```bash
curl -s -X POST 'localhost:8010/query/cache/clear?confirm=true'; echo
```

Recorded: this exact sequence removed one `website` chunk and returned the index to
33,781 vectors / 33,736 keyword rows. Ingestion scripts clear the cache themselves when
they finish.

---

## Phase 6 - When something is wrong

| Symptom | Look here |
| --- | --- |
| Answer names the wrong thing | `verify_hybrid_live.py` prints the top sources with scores; the retrieval log line has per-stage timings and the corrections applied |
| Answer says it could not find the answer | Compare the sources printed against the question; if the right document is in the list, it is a prompt issue, not retrieval |
| A document is never cited | `audit_index_metadata.py` - unreadable OCR cannot be retrieved; also check its `access_level` against the caller's tag |
| `/health/ready` is 503 | Pinecone. Everything else is reported as `degraded`, not fatal |
| Questions fail in bursts | Provider quota. The error names the limit and the wait; `LLM_RETRY_AFTER_MAX_SECONDS` bounds how long a request will wait |
| Answers repeat after a document was fixed | The answer cache. Ingestion clears it when it finishes; otherwise `POST /query/cache/clear?confirm=true` |
| 429 sooner than expected | The bucket is per access scope (domain + role), so other people on the same campus domain share it |

---

## What these checks do not cover

* **Identity is not verified.** `user_email` is supplied by the caller, so access levels,
  the rate-limit bucket and the cache partition are per *claimed* scope, and
  `/chat/api/history/?email=` returns that address's history. Treat access levels as a
  relevance filter, not a security boundary, until the API sits behind the JWT flow in
  `routers/auth.py`. Recorded in `DEPLOYMENT.md` section 10.
* **`POST /website/crawl` needs no authentication** and starts a background fetch and
  ingestion of whatever URL you pass. Verified by accident during this pass: it fetched
  `https://example.com` and wrote nothing to the corpus. It is a live ingestion endpoint
  reachable without credentials - protect it before exposing the API.
* **Neighbour expansion for legacy attachment documents** (IDs shaped
  `{doc_id}:{filename}-{chunk}`) finds nothing, because it builds IDs as
  `{doc_id}-{chunk}`. Their answers rest on the matched chunks alone.
* **PostgreSQL and Redis behaviour is covered by fakes, not by a live server** - the
  suite and this guide's SQLite path prove the code paths, not the wire behaviour.
* **Legacy duplicate vectors** remain in the index under both ID schemes, so the vector
  count exceeds the number of distinct chunks.
