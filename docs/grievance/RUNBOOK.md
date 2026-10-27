# Runbook

For the person who looks after the server (IT cell). Commands assume the Docker installation described in
`DEPLOYMENT.md`; the systemd equivalents are in the last section. Run Docker commands in the `deploy` folder.

## 1. What runs

| Part | What it does | If it stops |
|---|---|---|
| `web` (nginx) | serves the screens, forwards `/api/grievance` to the API, sets security headers | the site is unreachable |
| `api` | the backend: sign-in, tickets, files | nobody can use the system |
| `worker` | every minute: escalates overdue tickets, closes stale ones, sends emails | **tickets stop escalating and no email is sent**. Everything else still works, and *Admin → System health* turns red |
| `db` (PostgreSQL) | all data | the API stops answering |
| `backup` | one backup per day into `deploy/backups` | no new backups |
| `uploads` volume | uploaded photos and PDFs | files cannot be shown |

## 2. Everyday commands

```bash
docker compose ps                        # all services should be "running" (worker "healthy")
docker compose logs -f --tail=100 api    # watch the API    (also: worker, web, db, backup)
docker compose restart worker            # restart one part
docker compose up -d --build             # apply a new version (see "Updating")
./scripts/smoke-test.sh https://your-site   # checks the live system from outside
```

## 3. Alarms and what to do

| Alarm | Meaning | Action |
|---|---|---|
| E-mail "background worker is not running" (or red worker on the health page) | no heartbeat for an hour | `docker compose ps`; `docker compose logs --tail=100 worker`; `docker compose restart worker`. Overdue tickets will then escalate by themselves. Meanwhile an admin can escalate by hand |
| Health page: emails "gave up" | the mail server refused or was unreachable | check `SMTP_*` in `.env` and the mail server; fix; restart `worker`. Old failed emails are not resent, the in-system notifications still exist |
| Health page: "Upload folder is not writable" | disk full or permissions | `docker compose exec api df -h /data/uploads`; free space |
| Site shows "Sign-in is not configured" | `GOOGLE_CLIENT_ID` missing when the front end was built | set it in `.env`, then `docker compose up -d --build web` |
| Everybody gets "Please sign in again" | `SECRET_KEY` changed or sessions expired | normal after a key change: everyone signs in again |
| API will not start: "Unsafe production configuration" | the app refuses unsafe settings in production | the message names the setting (dev sign-in on, short secret key, cookies not secure, no Google client) |
| Students at one place cannot sign in, others can | many students share one address and hit the per-address limit | raise `LOGIN_RATE_LIMIT_PER_MINUTE` in `.env`, restart `api` |

## 4. Backups

The `backup` service writes `deploy/backups/grievance-<time>.tar` (or `.tar.enc` if `BACKUP_PASSPHRASE` is set) every day and
keeps `BACKUP_KEEP_DAYS` (14) days. Each file holds the database and all uploads, with checksums.

* **Copy the `backups` folder to another machine or storage every day.** A backup on the same disk does not survive a
  disk failure.
* If you use `BACKUP_PASSPHRASE`, store it somewhere safe and separate: **without it the backups cannot be opened.**
* **Prove that restores work** (once before go-live, then every few months):
  ```bash
  docker compose --profile tools run --rm restore-test /backups/grievance-<time>.tar
  ```
  It restores into a scratch database, checks the contents (users, tickets, that every attachment has its file),
  prints `RESTORE TEST PASSED` and deletes the scratch copy. It never touches the live data.

## 5. Restoring the live system (disaster recovery)

1. Stop the users of the database: `docker compose stop web api worker backup`.
2. Make the database and the uploads volume empty:
   ```bash
   docker compose up -d db
   docker compose exec db psql -U grievance -d postgres -c 'DROP DATABASE grievance;' -c 'CREATE DATABASE grievance OWNER grievance;'
   docker volume rm grievance_uploads          # the volume name is <project>_uploads; check with: docker volume ls
   ```
3. Restore: `docker compose --profile tools run --rm restore /backups/grievance-<time>.tar --yes`
   (the script refuses to restore into a database that has tables, so it cannot overwrite live data by accident).
4. Start everything: `docker compose up -d`. Tickets, users, routing and files are back as of the backup time.
   Anything reported after the backup is lost; tell students if that applies.

## 6. Updating to a new version

1. Take a backup now: `docker compose exec backup /scripts/backup.sh` (or wait for the daily one) and copy it away.
2. Replace the `backend` and `frontend` folders with the new version; keep `deploy/.env`.
3. `docker compose up -d --build`. The `migrate` step upgrades the database tables automatically; `api` and `worker`
   start only after it succeeds. If it fails, nothing is started; read `docker compose logs migrate`, restore the backup
   if needed.
4. Run `./scripts/smoke-test.sh https://your-site`.

## 7. Routine care

| When | What |
|---|---|
| Weekly | open *Admin → System health*; check free disk space; check the off-site copy of the backups exists |
| Monthly | read the Change log for surprises; remove staff who left (Users → deactivate) |
| Every term | review the designated officers; run the restore test; check the Google OAuth client and the HTTPS certificate expiry date |
| Yearly | decide about old data (`RETENTION.md`); update the software (`docker compose pull`, rebuild) |

## 8. If confidential information may have leaked

1. Note what, when and who. Do not delete anything; the change log and server logs are evidence.
2. Tell the designated officers and the college's data protection contact at once; the college decides on notifying
   the people concerned (the Digital Personal Data Protection Act may require it: ask counsel).
3. Rotate secrets if the server may be compromised: new `SECRET_KEY` (everyone is signed out), new database password, new
   Google OAuth client secret if used, new `BACKUP_PASSPHRASE` for future backups.
4. Review who has server and database access; remove anyone who does not need it.

## 9. Without Docker (systemd)

The services are `grievance-api`, `grievance-worker` and `grievance-backup.timer` (files in `deploy/systemd`).

```bash
sudo systemctl status grievance-api grievance-worker
sudo journalctl -u grievance-worker -n 100 --no-pager
sudo systemctl restart grievance-worker
sudo systemctl list-timers grievance-backup.timer
```

Backups and restores use the same scripts in `deploy/scripts` with `PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`,
`UPLOAD_DIR` and `BACKUP_DIR` set (see the top of each script).
