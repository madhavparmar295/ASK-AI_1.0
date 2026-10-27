# ASK-AI 2.0

The newly reformed repository for the ASK AI project.

It contains two products that share one API process and one front end:

* **ASK AI** — the chatbot that answers questions from indexed email, documents and web pages.
* **Grievance system** — the student portal that turns a problem into a ticket with a
  named owner, escalation and closure feedback, at `/grievance`.

```
pip install -r requirements.txt
uvicorn main:app --reload --port 8000        # chat + /api/grievance + /chat/api/ask
python -m grievance_app.seed                 # development data for the grievance pages
python -m grievance_app.worker               # escalations and email (second process)
cd frontend && npm install && npm run dev    # http://localhost:5173
```

Read [GRIEVANCE_INTEGRATION.md](GRIEVANCE_INTEGRATION.md) for how the two fit together,
the settings, and deployment. The grievance system's own guides are in
[docs/grievance/](docs/grievance/).
