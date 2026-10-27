# Known limitations

Read this before go-live and keep it with the other handover documents. The admin block should confirm it accepts them.

## Decisions are made by people, not by the system
1. The system **routes and records**. It does not decide any complaint, and it must not be described as doing so.
   Discipline, harassment and ragging procedures follow the college's own committees outside this system.
2. The category is **suggested from keywords** and confirmed by the student. Some tickets will be mislabelled and sent
   to the wrong person; heads and the Grievance Cell can reassign. On fresh wording, about three in four suggestions were
   right in our test (see below); the starter test set scored higher because it was written alongside the keywords.
3. The **confidential and urgent word lists will miss some cases and flag some harmless ones** (for example "scared of the
   exam", "fire alarm test"). A miss means a sensitive complaint is treated as ordinary; the student is told to contact
   security or the police directly in an emergency. Review the lists with the designated officers every term
   (`backend/app/services/keywords.py`).

## Confidentiality
4. Confidential tickets are protected by **access rules, not separate encryption**. Anyone with direct access to the
   database server or its backups can read them. Limit that access to one or two named people and keep backups encrypted
   (`BACKUP_PASSPHRASE`).
5. Email is not a secure channel. Emails about confidential tickets contain no details, but students should be told to
   use the website, not email, for sensitive matters.
6. Administrators cannot open confidential tickets in the system, but someone who administers the server can read the
   database. This is a trust and access-control question for the college, not something the software can fully solve.

## Files
7. Uploaded files are **not virus-scanned** unless ClamAV is installed and `CLAMAV_ENABLED=true`. Files are checked by
   their real content (JPG, PNG and PDF only), stored under random names, never opened by the server, and downloaded as
   attachments only. PDFs can still carry harmful content for the person who opens them.
8. Photos are stored exactly as taken. They may contain the place and time they were taken and sometimes people. The form warns students.
9. Nothing checks that a photo matches the description.

## Time and availability
10. Deadlines run **24 hours a day, every day**: there is no calendar of holidays, weekends or staff leave. A ticket reported
    on Saturday night can be escalated on Sunday morning. Choose deadlines in whole days for slow categories, and name a
    backup person for people who go on leave.
11. The background worker must be running. If it stops, **nothing escalates and no email is sent** until it is restarted.
    The health page and an alert email (after an hour) warn about this; the watchdog that emails depends on the API
    being up and email working.
12. The system is one server with one database. If the server is down, the system is down. Backups restore it, with the
    loss of anything reported after the last backup.
13. The sign-in limit is counted per address and per server process. Many students behind one college NAT share an address;
    raise `LOGIN_RATE_LIMIT_PER_MINUTE` if students are refused at busy times.

## Email and notifications
14. Without a mail server (`SMTP_HOST` empty), there is no email; notifications appear in the bell only. Failed emails are
    retried a few times and then given up; they are not resent after a mail-server outage ends.
15. The bell checks for news once a minute; it is not instant. There are no SMS, WhatsApp or push notifications.

## Reports and data
16. Reports are limited to the dashboard, ticket lists and counts. There are no exports or trend reports.
17. Old data is kept until the admin block decides otherwise (see `RETENTION.md`). Deleting is a deliberate, separate step.
18. One ticket belongs to one student. If fifty students report the same broken light, there are fifty tickets;
    there is no automatic grouping.

## Technical
19. The sign-in uses the college's Google accounts only. Staff without a college Google account cannot use the system.
20. People are identified by email address. If a person's email changes, add the new address and deactivate the old one;
    old tickets stay with the old record.
21. The screens support current versions of Chrome, Edge, Firefox and Safari. They were tested in a simulated browser and
    through the real server, but a real-device check (`ACCEPTANCE_CHECKLIST.md`) is part of go-live.
22. The Docker setup was not run in the development environment (see `DEPLOYMENT.md`, section 6).

## Measured accuracy of the category suggestion
| Test set | Sentences | Right category | Confidential found |
|---|---|---|---|
| Written alongside the keywords | 145 | 98% | 100% |
| Written afterwards, in new wording (blind) | 35 | 77% | 100% after tuning (50% before) |

Both sets were written by the developers, not by students. Real student text will differ. Add real sentences to
`backend/tests/data/classifier_samples.csv` and measure with `python -m app.services.classifier_eval`.
