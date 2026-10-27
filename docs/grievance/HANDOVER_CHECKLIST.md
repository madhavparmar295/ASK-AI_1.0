# Handover checklist

Tick each line together with the admin block. The system is not handed over until every line is ticked or its
exception is written down and accepted.

## People
- [ ] A named **maintainer** in the admin block or IT cell: ______________________  (backup: ______________________)
- [ ] The **Grievance Cell** (receives anything that matches no other route): ______________________
- [ ] The **designated officers** for confidential complaints, each with a backup: ______________________
- [ ] The people who may be **admins** (at least two): ______________________
- [ ] The data protection contact: ______________________

## Decisions from the college
- [ ] Categories, who handles each, and the deadline of each (entered in the system, reviewed by the owners)
- [ ] Escalation chain for every category (level 0, 1, 2)
- [ ] **Retention** decided and written in `RETENTION.md`
- [ ] Which person or office students are told to contact in an emergency (shown on the confidential complaint page)
- [ ] The limitations in `LIMITATIONS.md` read and accepted (signature / date: ____________)

## System
- [ ] Server installed; HTTPS working on the final address; `./scripts/smoke-test.sh` prints ALL CHECKS PASSED
- [ ] Google OAuth client is Internal, with the final address as an authorised origin
- [ ] Mail server details entered and a real email received by a real person (or "no email" accepted)
- [ ] The first admin created; real students, staff and officers imported; routing complete (every category has a default row)
- [ ] **Backup runs daily, a copy is taken off the server, and one restore test has passed** (date: ____________)
- [ ] The backup passphrase (if used) is stored safely by two people
- [ ] Worker is running; *System health* is green; the alert email address is correct and was tested by stopping the worker
- [ ] Test sign-in is **off** (health page shows no warning); no test users exist (`python -m app.seed` was never run)
- [ ] Acceptance checklist completed (`ACCEPTANCE_CHECKLIST.md`)

## Access and secrets
- [ ] Server access limited to named people; the developers' access is **removed**
- [ ] `.env` (or `/etc/grievance/env`) readable only by the service user; secrets are not in e-mail or chat
- [ ] Developers' personal accounts removed from the Google Cloud project, the repository and the server
- [ ] Source code in a repository the college owns, with the README and these documents

## Knowledge
- [ ] Admin guide walked through live with the admin block (they added a user, a routing row and a category themselves)
- [ ] Runbook walked through live with IT (restart the worker, read the health page, run a restore test)
- [ ] Heads, caretakers and officers shown their screens (queue, ticket page, escalation)
- [ ] Students told where to find the system, and that emergencies go to security or the police first
- [ ] A date set to review: keywords, officers list, limits and deadlines (suggest: end of the first term)
