# Deploying ASK-AI 2.0

The service answers questions from an email and document corpus. Nothing about
running it is unusual, but four things have to be in place before it answers well,
and three of them are not automatic.

## Components

| Component | What it does | Needs |
| --- | --- | --- |
| `main:app` | HTTP API: questions, uploads, chat history, Gmail webhook, feedback | Pinecone, optional Postgres |
| Celery worker | Gmail ingestion, attachment extraction, retention, watch renewal | Redis, Pinecone, Postgres, Gmail tokens |
| Celery beat | Schedules retention and watch renewal | Redis |
| SQLite `lexical_index.db` | Keyword half of retrieval (FTS5) | local disk, rebuilt from Pinecone |
| Pinecone index | The document store and the dense half of retrieval | `PINECONE_*` keys |
| PostgreSQL | Users, chat history, feedback (not documents) | `DATABASE_URL` |
| Redis | Celery broker, dedup ledger, usage tracking, answer cache | `CELERY_BROKER_URL` |

Retrieval is Pinecone-only. PostgreSQL is optional: if it is unreachable the API
still boots (it logs `startup_degraded`) and questions still work, but users, chat
history and feedback do not. Set `REQUIRE_DATABASE=true` to make that fatal instead.

## 1. Prerequisites

* Python 3.12 (the image uses `python:3.12-slim`)
* System packages for OCR and PDF work: `tesseract-ocr`, `poppler-utils`
* Accounts/keys: Groq (or a local Ollama), Pinecone (two keys: index + inference),
  Redis, and PostgreSQL if you want users and chat history
* Gmail OAuth credentials and a Pub/Sub topic, for live mail ingestion

Copy the template and fill it in:

```bash
cp .env.example .env
```

Everything required is marked `REQUIRED` in that file. The values only you can
supply are listed at the end of this document.

## 2. Install and run

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Check both probes:

```bash
curl -s localhost:8000/health          # liveness: never touches a dependency
curl -s localhost:8000/health/ready    # Pinecone (required), database, Redis
```

`/health/ready` answers 503 only when Pinecone is unreachable; a missing database or
Redis is reported under `degraded` with the reason.

## 3. Build the keyword index (once per deployment)

Retrieval fuses dense (Pinecone) results with keyword (FTS5) results. The keyword
index is derived data stored on the local disk, so a fresh deployment starts with it
empty and keyword search silently contributes nothing until it is built:

```bash
python rebuild_lexical_index.py                 # only what is missing from the index
python rebuild_lexical_index.py --rewrite-all   # re-read every chunk (a full first build)
python rebuild_lexical_index.py --limit 2000    # quick sanity check
python rebuild_lexical_index.py --dry-run       # report only
python rebuild_lexical_index.py --no-recover    # skip the slow part below
```

A first build on 34k chunks takes tens of minutes, because a fetch of a hundred chunks
takes seconds - the response carries their text. Rows already present are skipped, so an
interrupted run resumes instead of starting over; `--rewrite-all` forces a complete
re-read. Check the count with:

```bash
python -c "import sqlite3;print(sqlite3.connect('lexical_index.db').execute('select count(*) from chunks').fetchone())"
```

The row count should end up equal to the vector count. If it is short, the missing rows
are vectors whose IDs the fetch endpoint refuses: it carries IDs in the request line and
returns nothing at all for an ID containing a space or a plus sign, which in this corpus
is most attachment chunks (about one vector in six - 5,186 of 33,781 at the time of
writing). The rebuild reads those back with a query instead, eight at a time, which is
why `--no-recover` exists for a quick partial pass when only a sample is wanted.

A handful (45) cannot be read at all: they are image chunks whose vector is an exact
duplicate of their sibling's, so a query by ID answers with the sibling. The rebuild
lists them at the end rather than ending a few rows short without explanation; their text
is already searchable under the sibling ID.

Ingestion keeps the two in step from then on. Re-run it after restoring an older
`lexical_index.db`, after clearing the volume, or if `/query/cache` reports
`lexical_index.db` stats that look wrong.

## 4. Inspect the corpus before tuning anything else

```bash
python audit_index_metadata.py --report index_metadata_audit.md
```

This reports missing citation metadata, duplicate content, chunk-position gaps and
unreadable OCR. Treat its headline numbers as the ceiling on answer quality: text
that OCR produced incorrectly cannot be retrieved, however good the search is. Note
that documents scanned upside down are reported separately, because rotating the page
and re-running OCR recovers them.

## 5. Background jobs

```bash
celery -A jobs.celery_app.celery_app worker --loglevel=INFO
celery -A jobs.celery_app.celery_app beat   --loglevel=INFO
python -m jobs.watch_tasks                  # renew Gmail watches (expire every 7 days)
python -m jobs.retention_tasks              # purge unused email chunks (RETENTION_ENABLED)
```

Gmail watches expire after seven days. If renewal stops, mail simply stops arriving
for that mailbox, so `renew_all_watches` runs on a schedule and reports per-mailbox
results rather than failing as a batch.

Retention deletes email chunks that have not been used for a year. It is off by
default, starts in dry-run mode, and refuses to delete more than
`RETENTION_MAX_FRACTION` of the index in one run.

## 6. Docker

```bash
docker build -t askai:latest .
docker run --rm -p 8000:8000 --env-file .env -v askai-storage:/app/storage askai:latest
```

The same image runs the worker and beat with a different command:

```bash
docker run --rm --env-file .env askai:latest \
  celery -A jobs.celery_app.celery_app worker --loglevel=INFO
```

Mount a volume for `storage/` (original attachments: re-indexing needs them) and for
the directory holding `lexical_index.db` (rebuilding it otherwise costs a full scan).

A minimal local stack:

```yaml
services:
  api:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    volumes: ["askai-state:/app/state"]
  worker:
    build: .
    env_file: .env
    command: celery -A jobs.celery_app.celery_app worker --loglevel=INFO
  beat:
    build: .
    env_file: .env
    command: celery -A jobs.celery_app.celery_app beat --loglevel=INFO
  redis:
    image: redis:7-alpine
volumes:
  askai-state:
```

## 7. Continuous integration

`.github/workflows/ci.yml` runs the test suite, a dependency check and a syntax check
on every push and pull request. The suite needs no network: Pinecone, Groq, Postgres
and Redis are all replaced or pinned to unreachable addresses in `tests/conftest.py`.

```bash
python -m pytest tests/ -q
python -m pytest tests/ -q -k retrieval      # just the retrieval work
```

## 8. Operating it

**Logs.** JSON lines by default (`LOG_FORMAT=json`), one line per request, per
retrieval, per LLM call and per answer. Every request carries an `X-Request-ID`
header that also appears in the logs, so one bad answer can be traced from the HTTP
request through the retrieval decision to the provider call.

**Rate limits.** `POST /query/ask` is limited per access scope (domain + role):
`ASK_RATE_CAPACITY` burst, refilling at `ASK_RATE_REFILL_PER_SECOND`. A limited caller
gets 429 with `Retry-After`, not a queue slot.

**Caches.** `GET /query/cache` reports the answer cache and conversation memory
backend; `POST /query/cache/clear?confirm=true` empties it. Cached answers are keyed
by question *and* access scope, so a guest can never receive a student's cached
answer. Ingestion scripts clear the cache when they finish, so a corrected document
is not shadowed by a stale answer; otherwise entries expire after
`ANSWER_CACHE_TTL_SECONDS`.

**Streaming.** `POST /query/ask/stream` emits server-sent events: `sources` first,
then `token` events, then `done` with `grounded` and `cited_sources`.

**Prompt size.** Retrieved context is capped by `PROMPT_CONTEXT_MAX_CHARS` (12,000 by
default, about 3k tokens) and trimmed best-first, because 25 chunks of up to 1,500
characters exceed the per-minute input ceiling of a free provider tier and the request
is rejected before the model sees it. Raise it if your tier allows. When a provider
answers with a rate limit it states how long the window needs; the client waits that
long, up to `LLM_RETRY_AFTER_MAX_SECONDS`, and otherwise fails over to the next provider
rather than holding the request open.

## 9. What you have to provide

These cannot be generated or defaulted, and the app will not work correctly without
them:

| Value | Where it goes | What breaks without it |
| --- | --- | --- |
| `GROQ_API_KEY` | `.env` (or run Ollama) | Questions cannot be answered or rewritten (503) |
| `PINECONE_API_KEY` | `.env` | No retrieval at all; readiness fails |
| `PINECONE_EMBEDDING_API_KEY` | `.env` | Nothing can be ingested or queried (embeddings) |
| `JWT_SECRET_KEY` | `.env`, long random value | Login and any bearer-token endpoint |
| `PII_HASH_SALT` | `.env` | Roll numbers and grades would not be hashed |
| `DATABASE_URL` | `.env` | Users, chat history, feedback (retrieval still works) |
| `CELERY_BROKER_URL` | `.env` | Ingestion, retention and watch renewal stop |
| Gmail OAuth client + tokens | `client_secret.json`, `tokens/` | Live mail ingestion |
| `GCP_PUBSUB_TOPIC` | `.env` | Push notifications for new mail |
| `CORS_ALLOW_ORIGINS` | `.env` | The frontend is blocked; `*` is unsafe with credentials |

The Pinecone embedding key can be a second account: the project already separates
index and inference keys so a per-account inference quota does not cap how much can
be stored.

## 10. Known limitations

**The caller's identity is not verified.** `POST /query/ask` takes `user_email` in the
request body and derives everything from it: the access levels a question may see, the
rate-limit bucket and the answer-cache partition. Anyone who can reach the API can send
`someone@iitj.ac.in` and be treated as a student, so restricted chunks are protected by
obscurity and not by authentication. Treat the access level as a relevance filter, not
as a security boundary: put the API behind authentication (the JWT flow in
`routers/auth.py` already exists for the other routes) before exposing restricted
material to the internet, or serve only public content. The 429 and cache behaviour
inherit the same caveat - per-scope limits are per *claimed* scope.

**Some attachment chunks cannot be reached by ID.** The vector store's fetch endpoint
returns nothing for a vector ID containing a space or a plus sign, and the legacy
attachment IDs are `{doc_id}:{filename}-{chunk}`. Those chunks are still found by
similarity, keyword and rerank, and the audit and rebuild scripts read them back with a
query, but neighbour expansion (`fetch_neighbours`) builds IDs as `{doc_id}-{chunk}` and
so finds nothing for those documents. Their answers rest on the matched chunks alone.

**The index contains legacy duplicates.** Documents indexed before the current ID
scheme are present under both `{doc_id}:{filename}-{chunk}` and `{doc_id}-{chunk}`, so
the vector count is higher than the number of distinct chunks. Retrieval deduplicates by
ID, not by text, so a duplicate can occupy two context slots. `audit_index_metadata.py`
reports exact-duplicate text groups; re-indexing the affected documents removes them.

## 11. First-deployment checklist

`VERIFICATION_GUIDE.md` walks every check below as commands with expected results, from
the offline test suite through to the API endpoints, plus a troubleshooting map and the
list of things those checks cannot cover.

1. Fill `.env` (`GROQ_API_KEY`, both Pinecone keys, `JWT_SECRET_KEY`, `PII_HASH_SALT`,
   `CORS_ALLOW_ORIGINS`).
2. Start the API, confirm `/health/ready` reports Pinecone `ok`.
3. Run `python rebuild_lexical_index.py` and confirm the row count equals the vector
   count (see section 3 for what a short count means).
4. Run `python verify_hybrid_live.py`: it asks the two questions that used to fail, checks
   the expected names are in the answers, and prints the sources behind each one.
5. Ask the sample questions in `load_test_ask.py --questions ...` with
   `--mode pipeline`, then with `--mode http` once the server is up.
6. Run `python audit_index_metadata.py` and act on the unreadable-OCR number: those
   documents need re-OCR or removal.
7. Register Gmail watches (`python -m jobs.watch_tasks`) and schedule them.
