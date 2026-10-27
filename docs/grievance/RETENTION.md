# How long is data kept?

By default **nothing is ever deleted**. This page is the decision form for the college, and explains the tool.

## The decision (fill in and sign off)

The college's data protection contact and the grievance cell decide; ask counsel about statutory minimums (for example for
harassment complaints handled under the college's committee procedures) before choosing a period.

| Data | Kept for | Decided by / date |
|---|---|---|
| Ordinary tickets (closed or cancelled), their files, notifications and feedback | ______ years after closing | |
| Confidential tickets and their files | ______ years after closing (or "never delete automatically") | |
| Change log (who changed settings) | not deleted by the tool; keep for at least ______ years | |
| Backups | 14 days by default (`BACKUP_KEEP_DAYS`). Note that deleted tickets remain in older backups until those expire | |
| Server logs | as set by IT | |

Why it matters: students describe personal problems. The Digital Personal Data Protection Act expects personal data to
be kept no longer than needed. Keeping everything forever is a decision too; write it down if that is the choice.

## The tool

Set two values in `.env` (0 means "never delete", the default):

```
RETENTION_YEARS=3                  # ordinary tickets
RETENTION_CONFIDENTIAL_YEARS=7     # confidential tickets
```

Then, as a deliberate step (for example once a year, after a backup):

```bash
docker compose run --rm api python -m app.retention             # DRY RUN: only says what it would delete
docker compose run --rm api python -m app.retention --apply     # deletes
```

What it deletes: tickets that are **closed or cancelled** for longer than the period, with their history, notifications,
feedback and uploaded files. What it never deletes: open tickets, the change log, users, settings. It writes a line to the
change log (how many tickets and files, never what was in them).

It does **not** reach into backups. To remove old data from backups as well, let the backups expire (`BACKUP_KEEP_DAYS`) and do not restore old ones.

Individual deletion requests (a student asks for their data to be erased): delete the tickets directly in the database
under the college's procedure, or ask the developers; there is no screen for it, because such requests should be rare
and need a person to decide what the law and the college's records policy allow.
