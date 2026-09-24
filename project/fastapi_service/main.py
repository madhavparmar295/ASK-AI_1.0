import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, gmail_webhook, query, upload
from services.postgres import init_db

load_dotenv()

app = FastAPI(
    title="ASK-AI",
    description="AI-powered email & document Q&A system",
    version="1.0",
)

# Allow the chatbot frontend (any origin) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception:
        if os.getenv("ENVIRONMENT") == "test" and not (os.getenv("VECTOR_DB_URL") or os.getenv("DATABASE_URL")):
            return
        raise


app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(query.router)
app.include_router(gmail_webhook.router)
