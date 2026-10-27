# Admin guide

For the people in the admin block who run the grievance system day to day. No technical knowledge is needed.
Everything below is done in the **Admin** section of the grievance pages (sign in with your college account; you
must have been added as an admin).

## 1. First-time setup (do it in this order)

1. **Locations.** *Admin → Locations.* Add every hostel, department, building and mess hall students may name
   (for example "Hostel A", "CSE", "Main Block", "Main Mess"). Names must match what is written in the student list
   (step 2), because the report form uses them to preselect a student's own hostel or department.
2. **Users.** *Admin → Users.* Add people in bulk with a CSV file:
   *Download the template → fill it in Excel (save as CSV UTF-8) → Choose the file → "1. Check the file" → read the
   result → "2. Save the valid rows".* Nothing is saved until you press step 2, and rows with problems are skipped and
   explained. Roles: **Student**, **Staff** (handles tickets: caretakers, clerks, coordinators, wardens, HODs),
   **Designated officer** (handles confidential complaints only), **Admin**.
3. **Categories.** *Admin → Categories.* Twelve are provided. For each, check the **deadline in hours**: when a ticket
   waits longer than this, it moves up one level. Add or remove categories if your college needs it.
4. **Routing.** *Admin → Routing.* This decides **who gets which ticket**. One row = one category (and optionally one
   location) with up to three people: level 0 gets the ticket first, level 1 gets it if the deadline passes, level 2
   after that. Use the CSV import for many rows, or "Add a routing row" for one. Rules:
   * Every category needs **one default row** (no location). It covers every location without its own row.
   * The **Other** category's default row should point to your **Grievance Cell**: it receives everything that matches
     nothing else.
   * The confidential category's rows may contain **designated officers only**.
5. **Test it.** Ask a colleague with a student account to report a test problem. Watch it arrive in the right
   person's queue, then have them cancel it. Do this for a hostel, a department and a confidential category before
   announcing the system.

## 2. Every day or week

| Task | Where |
|---|---|
| See what is overdue | *Admin → Dashboard* (red number), then *All tickets → Overdue only* |
| Push a stuck ticket on | open the ticket → **Escalate** (moves it to the next level) or **Reassign** (choose a person) |
| Check the system is alive | *Admin → System health*. "Background worker: Running" must be green. If it is red, follow the runbook |
| Look at feedback | *Admin → Dashboard* (average rating) |

The ticket page shows what happened and when. Administrators **cannot open confidential tickets**; the dashboard
only counts them.

## 3. When things change

| Situation | What to do |
|---|---|
| A staff member leaves or goes on long leave | *Users →* Edit → untick **Active**. The page tells you in how many routing rows the person appears. Then *Routing →* replace them in those rows. Tickets already assigned to them move on when their deadline passes, or a head can **Reassign** them straight away |
| A person moves to another role or hostel | *Routing →* Edit the row and choose the new person |
| A new hostel or department opens | *Locations →* Add it, then *Routing →* add a row for each category that uses it (or let the default row cover it) |
| A deadline is too short or too long | *Categories →* Edit → change the hours |
| The system suggests the wrong category for common phrases | *Categories →* Edit the right category → add the words students use to "Words that suggest this category". `word:3` makes a word count more; `leak*` matches leak, leaking, leakage. Hinglish spellings are welcome |
| A new academic year starts | *Users →* import the new student list (existing people are updated, nobody is deleted). Deactivate people who have left |
| Someone cannot sign in | *Users →* search their email. They must exist, be **Active**, and use their college Google account |

## 4. Confidential complaints

* Students tick "Keep this confidential", or the system raises the flag when the text sounds sensitive (for example
  ragging, threats, harassment). The student cannot turn it off.
* Only **designated officers** see these tickets, and the student. Nobody else: not wardens, not heads, not admins.
* Emails and notifications for them never contain details, only "there is an update, log in".
* The system **records and routes**; it does not investigate or decide. Real cases follow the college's own
  committee procedure outside this system. Students are told to contact campus security or the police at once if they
  are in danger.
* Keep the list of designated officers short, name a backup for each, and review it every term.

## 5. Questions people ask

**A ticket went to the wrong person.** Open it and **Reassign**. If it keeps happening for one category, fix the
routing row or add keywords.

**A student says nobody replied.** Open the ticket. Check "Handled by" and the deadline. If the person is on leave,
Reassign; if the deadline has passed it moves up by itself within a minute (if the worker is running).

**No emails are arriving.** *System health → Email.* "Not configured" means IT has not entered the mail server details.
Notifications still appear inside the system (the bell).

**I added someone as staff but they see nothing.** They only see tickets routed to them. Check *Routing*.

**I made a mistake in a CSV import.** Fix the file and import again; existing rows are updated. For one wrong row, edit it in
*Routing* or *Users*.

**Where can I see who changed what?** *Admin → Change log*.

## 6. Do not

* Do not share admin accounts. Each admin signs in with their own college account (the change log records who did what).
* Do not add personal Gmail addresses; only college accounts can sign in.
* Do not leave a category without a default routing row.
* Do not promise outcomes in confidential cases. The system only routes them.
