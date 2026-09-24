from services.doc_embeddings import embed_document
from services.postgres import upsert_document


def ingest_record(record: dict) -> None:
    """Store document metadata + 384-d embedding in PostgreSQL.

    Chunks are not sent to Pinecone here. They are created from the top-2
    documents at query time and upserted then.
    """
    embedding = embed_document(record.get("text") or "")
    upsert_document(record, embedding)
