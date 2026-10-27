# Acceptance checklist

The automated tests cover the logic. This list covers what only a person on the real installation can check.
Use real phones and the real address. Mark **Auto** items as already covered; do the rest by hand and write the date.

## A. Sign-in
- [ ] A student signs in with a college Google account. A personal Gmail account is refused
- [ ] A person who is not in the user list is refused with a clear message
- [ ] A deactivated person cannot sign in
- [ ] Sign out works; the back button after sign-out does not show tickets
- [ ] The sign-in works on the phones students use (Android Chrome, iPhone Safari)

## B. Student
- [ ] Report a problem: type, the category is suggested, the student's hostel is preselected
- [ ] Add a photo from the phone camera and a PDF; both open from the ticket page
- [ ] A fourth file, a Word file, a very big file are refused with a clear message
- [ ] A second report of the same thing shows the existing ticket
- [ ] Track the ticket; reply to a question; cancel; confirm a fix; say "not fixed"; leave feedback
- [ ] Text with a sensitive word locks the confidential box; the ticket is then invisible to wardens and admins
- [ ] The page is usable on a small phone screen (no sideways scrolling, buttons reachable)

## C. Handlers, heads, officers
- [ ] A caretaker sees only their own tickets, with the student's room; starts, asks a question, resolves
- [ ] A warden sees the team list and the overdue list; escalates and reassigns; the person chosen receives it
- [ ] An officer sees confidential tickets; nobody else in the college does (try with a warden and an admin)
- [ ] The Grievance Cell sees tickets that matched no other route
- [ ] The conflict rule: a caretaker who reports a problem cannot handle their own ticket

## D. Time (do these with a short test deadline, then restore it)
- [ ] Set a category's deadline to 1 hour, report a ticket, wait: it moves to level 1 within a minute of the deadline,
      the new person and the student are notified
- [ ] An unanswered question pauses the clock; the answer resumes it
- [ ] A resolved ticket nobody answers closes by itself after the set days (set `AUTO_CLOSE_RESOLVED_DAYS=1` to test)
- [ ] Stop the worker for the alert time: the health page turns red and an alert email arrives. Restart it

## E. Email and notifications
- [ ] Each event sends one email to the right person; the links open the right ticket
- [ ] Emails for a confidential ticket contain no title, category or description
- [ ] The bell shows a count and marks notifications as read

## F. Admin
- [ ] Add and edit a category, a location, a user, a routing row; the next new ticket follows the change
- [ ] A CSV import: preview shows the problems, nothing saved until "Save"; bad rows are skipped and explained
- [ ] Deactivating a person shows the warning with their routing rows
- [ ] The admin cannot deactivate or demote themselves; the "Other" category and the confidential route cannot be removed
- [ ] The dashboard numbers match the ticket list; confidential tickets are counted but not listed
- [ ] The change log shows each of the changes above

## G. Security spot checks (by someone who did not build it)
- [ ] A student who types an admin or staff address sees "Page not found"
- [ ] Changing the ticket number in an address to another student's ticket shows "not found"
- [ ] An attachment address pasted into another student's browser shows "not found"
- [ ] `./scripts/smoke-test.sh` passes; the test sign-in is off; there is no `/docs` page
- [ ] The site only works over HTTPS; the browser shows a valid certificate

## H. Operations
- [ ] Backup made, copied away, **restore test passed**
- [ ] Restart the server: everything returns by itself (api, worker, database, web)
- [ ] The runbook's steps for "worker not running" and "restore" were followed once by IT, not the developers

## I. Already covered by automated tests (no need to repeat by hand)
**Auto:** permissions between every role and every ticket (including confidential), state changes, routing and escalation
logic, the worker's escalation being safe to run twice, uploads validation, import preview/apply, database migrations on
PostgreSQL, production start-up guards, backup/restore/encryption scripts, the nginx configuration and security headers.
