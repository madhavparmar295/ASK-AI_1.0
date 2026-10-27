# The grievance system inside ASK-AI

Two products now live in one repository and one API process:

| Piece | Where | What it does |
|---|---|---|
| Chatbot | `main.py`, `routers/`, `services/`, `frontend/src/` | answers questions from indexed email, documents and web pages |
| Grievance system | `grievance_app/`, `frontend/src/grievance/` | turns a problem into a ticket that a named person has to act on |

They meet in exactly three places:

1. **The pages.** `frontend/src/grievance/` is mounted at `/grievance`, reachable from the
   chat sidebar, with a **Chat** link back. It is the grievance project's own React module,
   unchanged except for the back link in `layout/GrievanceLayout.jsx`.
2. **The API.** `grievance_app/api.py` exports the same routers the grievance system ran
   standalone. `main.py` includes them, so `/api/grievance/...` is served by the chatbot's
   FastAPI process on the same port and origin.
3. **The hint.** While a student writes a problem, the form asks `POST /chat/api/ask`
   (`routers/grievance_bridge.py`) whether the indexed documents already answer it. The
   answer appears as "Before you submit: this may help", labelled as automated.

The two halves keep **separate databases and separate sign-in**. That is deliberate: both
apps define a `users` table and they are shaped differently (integer ids and a password
hash versus UUIDs and a role), so sharing one table would mean rewriting the grievance
identity model and its 267 tests. A student signs in to the grievance pages with Google
(or the development picker); the chat session is untouched.

## Layout

```
grievance_app/                 the grievance backend, as a package
  api.py                       mountable router, bootstrap, worker watchdog
  main.py                      the same routes as a standalone app
  config.py                    settings, all read as GRIEVANCE_<NAME>
  migrations/                  Alembic migrations (0001, 0002)
  worker.py                    escalation / auto-close / email worker
  seed.py, init_data.py, create_admin.py, retention.py
routers/grievance_bridge.py    POST /chat/api/ask (the form hint)
tests/grievance/               the grievance test suite (267 tests)
tests/test_grievance_bridge.py the two seams: mount + hint (8 tests)
frontend/src/grievance/        the grievance screens
frontend/src/integration/      ReportProblemButton (chat -> form)
alembic.grievance.ini          migrations, run from the repository root
```

## Run it on a laptop

```bash
# 1. database (the grievance side defaults to a SQLite file, so nothing is required)
pip install -r requirements.txt

# 2. the API and the chat pages  (one process, port 8000)
uvicorn main:app --reload --port 8000

# 3. grievance data (development only: it refuses to run when GRIEVANCE_ENV=production)
python -m grievance_app.seed

# 4. the worker: escalations, auto-close and emails do not happen without it
python -m grievance_app.worker

# 5. the screens
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Open `/grievance` on the dev server. With `GRIEVANCE_DEV_LOGIN_ENABLED=true` the sign-in
page lists the seeded users (`ravi@`, `caretaker_a@`, `warden@`, `admin@`, ...); pick one.
Vite forwards `/api/grievance` and `/chat/api` to port 8000, so cookies behave as they do
in production.

`GRIEVANCE_DATABASE_URL` defaults to `sqlite:///./grievance.db`. Tables are created on
startup while `GRIEVANCE_AUTO_CREATE_TABLES=true`; in production run the migrations
instead (below) and set it to false.

## Configuration

Every grievance setting is read as `GRIEVANCE_<NAME>` (`grievance_app/config.py`), which is
why one `.env` can hold both products. The full list with defaults is in `.env.example`.
The ones that matter first:

| Setting | Default | Note |
|---|---|---|
| `GRIEVANCE_DATABASE_URL` | `sqlite:///./grievance.db` | PostgreSQL in production, e.g. `postgresql+psycopg://...` |
| `GRIEVANCE_AUTO_CREATE_TABLES` | `true` | set `false` once migrations are in charge |
| `GRIEVANCE_SECRET_KEY` | `change-me` | 32+ random characters; required in production |
| `GRIEVANCE_GOOGLE_CLIENT_ID` | empty | the same client id the front end gets as `VITE_GOOGLE_CLIENT_ID` |
| `GRIEVANCE_DEV_LOGIN_ENABLED` | `true` | must be `false` in production |
| `GRIEVANCE_UPLOAD_DIR` | `./uploads` | outside anything the web server serves |
| `GRIEVANCE_HINT_TIMEOUT_SECONDS` | `12` | the form waits 13 seconds |

`GRIEVANCE_ENV=production` makes the service refuse to start with a default secret, dev
login enabled, insecure cookies, or no Google client id. Leave it unset in development.

## The hint endpoint

`POST /chat/api/ask` with `{"text": "The AC in my room is not working"}` answers:

```json
{"answer": "Report air-conditioner faults to the hostel caretaker ...",
 "sources": [{"title": "Hostel Rules", "section": "", "url": "https://college.edu/hostel-rules.pdf"}]}
```

Rules, all enforced server-side:

* Shorter than 25 characters, longer than 2000, or ungrounded → `{"answer": "", "sources": []}`
  and the form shows nothing. A hint that "may help" must never invent one.
* Text the grievance keyword screen marks confidential is refused **before retrieval**.
* The question is not written to the retrieval log (`retrieve_chunks(..., log_question=False)`).
  The bridge logs counts, latency and a grounded flag only.
* The retrieval path is the chatbot's normal one, so answers use the same hybrid search,
  reranker and citation rules as `/query/ask`, limited to public documents (`Guest` scope).
* Anything slower than 12 seconds returns empty rather than holding the form. The
  deadline used to be 7.5 s, which the first request after a restart could not meet
  (a cold hosted embedding alone measured ~4.9 s); the startup warm-up and a 4 s
  dense budget now keep it inside the deadline, with keyword search as the fallback.

`frontend/.env` sets `VITE_HINT_URL=/chat/api/ask`; leave it empty to switch the hint off.

## Production

* Serve the chat and the API from **one address** (the grievance sign-in cookie is
  `HttpOnly` and must reach both). The dev proxy and any reverse proxy need
  `/api/grievance/*` and `/chat/api/*` on the same host as the pages.
* Run the migrations once per deployment:

  ```bash
  GRIEVANCE_DATABASE_URL=postgresql+psycopg://... \
    python -m alembic -c alembic.grievance.ini upgrade head
  ```

* Run the worker as a second process from the same image:
  `python -m grievance_app.worker`. It escalates overdue tickets, closes stale ones and
  sends the queued emails. Without it nothing escalates and no email leaves the server;
  `/api/grievance/admin/health` and the watchdog show this.
* Set `GRIEVANCE_ENV=production`, `GRIEVANCE_DEV_LOGIN_ENABLED=false`,
  `GRIEVANCE_COOKIE_SECURE=true`, `GRIEVANCE_SECRET_KEY`, `GRIEVANCE_GOOGLE_CLIENT_ID`.
* Back up the grievance database and `GRIEVANCE_UPLOAD_DIR`. The chatbot can be restored
  without them and vice versa.

## What the grievance side still documents

The source project's guides are copied to `docs/grievance/` and remain the reference for
the case workflow, roles, retention and the admin screens: `ADMIN_GUIDE.md`,
`RUNBOOK.md`, `LIMITATIONS.md`, `RETENTION.md`, `ACCEPTANCE_CHECKLIST.md`,
`HANDOVER_CHECKLIST.md`, `CONTRACT.md`, `DEPLOYMENT.md` and the original
`CHATBOT_INTEGRATION.md`.

They were written when the service was standalone, so read `app` in a command as
`grievance_app`, and add the `GRIEVANCE_` prefix to every environment variable. The
behaviour they describe is unchanged, and the grievance test suite
(`python -m pytest tests/grievance -q`) passes unmodified in this repository.
