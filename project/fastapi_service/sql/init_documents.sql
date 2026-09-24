-- Document-level store for ASK-AI.
-- Requires PostgreSQL 16+ with the pgvector extension.
--
-- Stage 1 retrieval: cosine distance over 384-d embeddings using HNSW.
-- Full document text is kept here so the top-2 hits can be chunked later
-- and sent to Pinecone as 1024-d vectors.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    filename TEXT,
    source TEXT,
    source_type TEXT NOT NULL DEFAULT 'document_upload',
    access_level TEXT NOT NULL DEFAULT 'public',
    sender TEXT,
    subject TEXT,
    date TEXT,
    uploaded_at TIMESTAMPTZ,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    pinecone_indexed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS documents_access_level_idx
    ON documents (access_level);
