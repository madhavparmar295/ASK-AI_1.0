# Deployment guide

## What you need before starting

| Item | Details |
|---|---|
| A server | Linux, 2 CPU, 4 GB RAM, 20 GB disk plus room for photos and backups (start with 100 GB). Docker 24+ with Compose v2 |
| A web address | for example `grievance.college.edu`, pointing at the server, with an **HTTPS certificate**. Sign-in cookies are marked Secure and will not work over plain HTTP. If the college already has a reverse proxy or load balancer that handles HTTPS, send it traffic for this address to port 80 of this server |
| Google sign-in | a Google Cloud OAuth client, created by the college's Google Workspace admin (below) |
| Mail server (optional) | SMTP host, port, user, password. Without it, notifications appear only inside the system |
| The first admin | the college email of the person who will manage the system |
| Server access | only the people who run the system; the database and the uploaded files contain personal data |

## 1. Google OAuth client (about 10 minutes, by the Workspace admin)

1. Google Cloud Console → *APIs & Services → OAuth consent screen* → user type **Internal** (this limits sign-in to
   the college's accounts).
2. *Credentials → Create credentials → OAuth client ID* → type **Web application**.
3. *Authorised JavaScript origins:* `https://grievance.college.edu` (and `http://localhost:5173` while developing).
   No redirect address is needed.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`). It is not a secret.

## 2. Install (Docker)

```bash
cd deploy
cp .env.example .env
nano .env        # fill in every line marked CHANGE, and the SMTP lines if you have a mail server
```

Generate the secrets: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` for `SECRET_KEY`, and a different
long random value for `POSTGRES_PASSWORD` (put the same password inside `DATABASE_URL`). Set `GOOGLE_CLIENT_ID`,
`ALLOWED_EMAIL_DOMAIN` and `APP_BASE_URL`. Keep `.env` private (`chmod 600 .env`).

```bash
docker compose up -d --build                       # builds and starts everything; tables are created automatically
docker compose run --rm api python -m app.init_data       # the default categories (once)
docker compose run --rm api python -m app.create_admin --email first.admin@college.edu --name "First Admin"
./scripts/smoke-test.sh https://grievance.college.edu     # must print ALL CHECKS PASSED
```

> **Never run `python -m app.seed` on a real installation.** It creates fake test users. The program refuses to run
> it when `ENV=production`.

Then open the site, sign in with the first admin's college account, and follow `ADMIN_GUIDE.md` section 1 (locations,
users, categories, routing, test).

The application refuses to start in production if the dev sign-in is on, the secret key is short, cookies are not
Secure, or the Google client is missing, and tells you which.

## 3. Put it behind the college's address (if it is not the front door)

The `web` container listens on `HTTP_PORT` (default 80). The simplest layout is for the college's proxy to forward
`https://grievance.college.edu/` to it. If the chatbot lives at the same address, see `CHATBOT_INTEGRATION.md`: the
grievance pages then become part of the chatbot's front end and only `/api/grievance` needs forwarding.

If nginx here should serve HTTPS itself, follow the commented block at the end of `deploy/nginx.conf`, mount the
certificate files, and publish port 443 in `docker-compose.yml`.

## 4. Check it

* `./scripts/smoke-test.sh https://your-address`
* *Admin → System health:* worker **Running**, no red items. Clamav shows a warning unless you installed a virus scanner
  (see `LIMITATIONS.md`).
* Work through `ACCEPTANCE_CHECKLIST.md` with real people on real phones.
* **Run the backup restore test once** (`RUNBOOK.md` section 4).

## 5. Without Docker (a plain Linux server)

1. Install Python 3.12, PostgreSQL 16, nginx, and Node 22 (only to build the screens).
2. Create the database and a user: `createuser grievance -P` ; `createdb grievance -O grievance`.
3. Create a system user and folders:
   ```bash
   sudo useradd --system --home /opt/grievance --shell /usr/sbin/nologin grievance
   sudo mkdir -p /opt/grievance /etc/grievance /var/lib/grievance/uploads /var/backups/grievance
   sudo chown -R grievance /var/lib/grievance /var/backups/grievance
   ```
4. Copy this release to `/opt/grievance` (`backend`, `frontend`, `deploy`), then:
   ```bash
   cd /opt/grievance && python3.12 -m venv venv && ./venv/bin/pip install -r backend/requirements.txt
   cd frontend && npm ci && VITE_GOOGLE_CLIENT_ID=... npx vite build --base=/grievance/
   sudo mkdir -p /var/www/grievance && sudo cp -r dist /var/www/grievance/grievance
   ```
5. Write `/etc/grievance/env` (same variables as `.env.example`, `DATABASE_URL` pointing at `localhost`,
   `UPLOAD_DIR=/var/lib/grievance/uploads`) and `/etc/grievance/backup.env` (`PGHOST`, `PGUSER`, `PGPASSWORD`,
   `PGDATABASE`, `UPLOAD_DIR`, `BACKUP_DIR=/var/backups/grievance`, optional `BACKUP_PASSPHRASE`). `chmod 600` both.
6. Create the tables and first data (as the `grievance` user, with the env loaded):
   ```bash
   set -a; . /etc/grievance/env; set +a
   cd /opt/grievance/backend && /opt/grievance/venv/bin/alembic upgrade head
   /opt/grievance/venv/bin/python -m app.init_data
   /opt/grievance/venv/bin/python -m app.create_admin --email first.admin@college.edu --name "First Admin"
   ```
7. Install the services: `sudo cp deploy/systemd/* /etc/systemd/system/ && sudo systemctl daemon-reload &&
   sudo systemctl enable --now grievance-api grievance-worker grievance-backup.timer`.
8. nginx: use `deploy/nginx.conf` as the site, with `server 127.0.0.1:8000;` as the upstream, `root /var/www/grievance`
   in place of `/usr/share/nginx/html`, and your HTTPS certificate.
9. Run the checks in section 4.

## 6. What was tested, and what was not

Tested during development: the whole backend (267 automated tests, also on PostgreSQL 16) and the screens (161 automated tests), the migrations on PostgreSQL,
the real screens' API client against the real backend through a real nginx (17 live checks), the production start-up
guards, the backup, encrypted backup, restore, damaged-backup and wrong-passphrase paths, the nginx configuration (syntax and
live behaviour) and the smoke test against a production-mode server.

**Not tested here:** the Docker images and the Compose file were written and checked for correct syntax but could not be
built in the development environment (no Docker available); the first `docker compose up` on your server is their first
real run, so expect to fix a small thing or two. Google sign-in, real e-mail delivery, HTTPS, the systemd units and the
screens in a real browser or on phones also need checking on the real installation (`ACCEPTANCE_CHECKLIST.md`).
