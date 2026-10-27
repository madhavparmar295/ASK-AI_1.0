# ASK-AI 2.0 API image. The Celery worker and beat run from the same image with a
# different command:
#
#   api     uvicorn main:app --host 0.0.0.0 --port 8000
#   worker  celery -A jobs.celery_app.celery_app worker --loglevel=INFO
#   beat    celery -A jobs.celery_app.celery_app beat --loglevel=INFO
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production

# OCR and PDF tooling required by the ingestion pipeline.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so code changes do not invalidate the pip layer.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Uploaded attachments and the local state files live here; mount a volume in
# production so re-indexing still has the original files.
RUN mkdir -p storage/uploads tokens uploads \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
