> **Status in this repository:** this is the original note from the standalone grievance project.
> The pages, the API mount and the hint endpoint it describes are all implemented now; the
> authoritative guide is [GRIEVANCE_INTEGRATION.md](../../GRIEVANCE_INTEGRATION.md).

# Joining the chatbot and the grievance system

The chatbot answers questions. The grievance system handles problems that need somebody to act. They stay separate
programs and meet in three places. Only the first is required.

## 1. Placing the grievance pages in the chatbot's front end (required)

The grievance screens are a React folder, `frontend/src/grievance`, built with the same tools as the chatbot front end
(React, Vite, Tailwind, react-router, lucide-react). Copy that folder into the chatbot repository and mount it at
`/grievance`. The steps are in `frontend/README.md`:

* chatbot **without** a router: render `<GrievanceApp />` when the address starts with `/grievance`;
* chatbot **with** react-router: add `<Route path="/grievance/*" element={<GrievanceRoutes />} />`.

Add a menu entry "Grievance" that links to `/grievance`. If the chatbot's shell already has a header, edit only
`src/grievance/layout/GrievanceLayout.jsx` (keep the menu and the content area).

The web server must forward `/api/grievance/*` to the grievance backend. Everything must be served from **one address**
so the sign-in cookie reaches both.

**Sign-in.** The grievance backend does its own Google sign-in and sets its own cookie (`grievance_session`). A student
who already signed in to the chatbot is asked to sign in once more with the same Google account; this is one click.
If the chatbot team wants true single sign-on later, the grievance backend only needs to accept the chatbot's session
(`app/security/sessions.py` and `deps.py` are the only places to change).

## 2. The "Report this as a problem" button (recommended, 10 minutes)

Copy `frontend/src/integration/ReportProblemButton.jsx` into the chatbot front end. After the chatbot shows an answer, render
`<ReportProblemButton text={theStudentsMessage} />`. It appears only when the message sounds like something broken or
wrong (English and Hinglish words such as "not working", "leaking", "kharab", "complaint"), and it opens
`/grievance/new?text=...` with the description filled in. Nothing is sent until the student presses Submit on the
grievance form. Questions such as "What is the attendance rule?" do not show the button. The word list is at the top of
the file; change it freely. Use `always` to show the button on every answer.

## 3. The "before you submit" hint (optional)

While a student writes a problem, the form can show the chatbot's answer: "Before you submit: this may help". It is
labelled as an automated suggestion and never blocks submitting.

To switch it on, the chatbot team provides **one endpoint** on the same address, for example `POST /chat/api/ask`:

```
request   POST  {"text": "The AC in my room is not working"}      (JSON, the sign-in cookie is sent)
answer    200   {"answer": "Report AC faults to the hostel caretaker ...",
                 "sources": [{"title": "Hostel Rules", "section": "4.2", "url": "/docs/hostel-rules.pdf"}]}
```

* `answer` is plain text (shown as text, never as HTML), up to 2000 characters. `sources` is optional (at most 5 are shown;
  `url` must start with `http://`, `https://` or `/`).
* Return an error or an empty answer when nothing useful is found; the form then shows nothing.
* The endpoint must answer within 13 seconds and must **not** store or log what students type beyond the chatbot's normal
  policy: students may describe personal problems.
* The hint is now on by default: `VITE_HINT_URL` falls back to `/chat/api/ask`, the endpoint this
  repository serves. Set it for a different address, or set it to an empty value to switch the hint off.

The hint is only as good as the chatbot's answers; it is shown for texts of 25 characters or more, after the student
stops typing for a moment. The form asks for a hint only after the grievance system has checked the description and found it **not sensitive**; it
never sends text that looks sensitive, text marked confidential, or text it could not check.

## What is not shared

The two programs do not share a database, user lists or code on the server. The grievance system never calls the chatbot
except for the optional hint, and the chatbot never writes into the grievance database.
