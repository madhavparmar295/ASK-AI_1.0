import os

# Set environment variables BEFORE importing main to prevent import-time failures
os.environ.setdefault("PINECONE_API_KEY", "fake-key-for-ci")
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-key-for-ci")
os.environ.setdefault("GROQ_API_KEY", "fake-key-for-ci")
os.environ.setdefault("ENVIRONMENT", "test")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"Hello": "World"}
