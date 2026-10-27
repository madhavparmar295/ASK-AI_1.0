"""
Shared test configuration.

The environment is pinned here, before pytest imports any test module or
application module. Several services call ``load_dotenv()`` at import time, which
would otherwise pull real values out of ``.env`` - a live PostgreSQL URL, real
Pinecone and Groq keys - into the test run and make the suite depend on local
infrastructure.

Values are assigned rather than defaulted so a populated ``.env`` cannot leak into
a test. Redis is pointed at an unroutable local port: the ledger and usage tracking
fail open, and no test can accidentally write to the real Redis.
"""

import os

os.environ["ENVIRONMENT"] = "test"

# Storage: SQLite for the SQLAlchemy models, no pgvector/pgvector dependency.
os.environ["DATABASE_URL"] = "sqlite:///./test_askai.db"
os.environ["VECTOR_DB_URL"] = "sqlite:///./test_askai.db"
os.environ["DEDUP_STORE_PATH"] = "test_processed_message_ids.json"
os.environ["OCR_CACHE_PATH"] = "test_ocr_cache.json"

# External services are never reachable from the test suite.
os.environ["PINECONE_API_KEY"] = "fake-key-for-ci"
os.environ["PINECONE_EMBEDDING_API_KEY"] = "fake-key-for-ci"
os.environ["GROQ_API_KEY"] = "gsk-fake-key-for-ci"
os.environ["OPENAI_API_KEY"] = "sk-fake-key-for-ci"
os.environ["DEDUP_REDIS_URL"] = "redis://127.0.0.1:6399/0"
os.environ["CELERY_BROKER_URL"] = "redis://127.0.0.1:6399/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://127.0.0.1:6399/1"
os.environ["GMAIL_ACCOUNT_IDS"] = ""

# Retrieval and answer-path switches: on by default in production, pinned here so the
# tests exercise the real behaviour rather than whatever the developer's .env holds.
os.environ["HYBRID_SEARCH_ENABLED"] = "true"
os.environ["RERANK_ENABLED"] = "true"
os.environ["ANSWER_CACHE_ENABLED"] = "true"
os.environ["QUERY_REWRITE_ENABLED"] = "true"
os.environ["USAGE_TRACKING_ENABLED"] = "true"
# Fast, deterministic retries in tests.
os.environ["LLM_MAX_ATTEMPTS"] = "2"
os.environ["LLM_BACKOFF_BASE_SECONDS"] = "0"
os.environ["LLM_PROVIDER_COOLDOWN_SECONDS"] = "0"
os.environ["LEXICAL_DB_PATH"] = "test_lexical_index.db"

# The grievance API is mounted in the same application (see grievance_app/api.py). Its
# settings use the GRIEVANCE_ prefix and its own database, so the two services cannot
# read each other's DATABASE_URL. Pinned here because test modules import `main` early.
os.environ["GRIEVANCE_ENV"] = "test"
os.environ["GRIEVANCE_DATABASE_URL"] = "sqlite://"
os.environ["GRIEVANCE_AUTO_CREATE_TABLES"] = "false"
os.environ["GRIEVANCE_WATCHDOG_ENABLED"] = "false"
os.environ["GRIEVANCE_DEV_LOGIN_ENABLED"] = "true"
os.environ["GRIEVANCE_SECRET_KEY"] = "test-secret-key-for-the-suite-at-least-32-bytes-long"
os.environ["GRIEVANCE_COOKIE_SECURE"] = "false"

os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-the-suite-at-least-32-bytes-long"
os.environ["PII_HASH_SALT"] = "test-salt"
os.environ["LOG_FORMAT"] = "text"
os.environ["LOG_REQUESTS"] = "false"
os.environ["USAGE_TRACKING_ENABLED"] = "true"
os.environ["RETENTION_ENABLED"] = "false"
