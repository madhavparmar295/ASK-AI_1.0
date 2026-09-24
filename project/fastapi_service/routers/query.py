from fastapi import APIRouter
from schemas.query import QueryRequest, QueryResponse, SourceChunk
from services.access_control import resolve_user_tag
from services.rag import generate_answer
from services.retrieval import retrieve_chunks

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/ask", response_model=QueryResponse)
async def ask_question(request: QueryRequest):
    domain = request.user_email.split("@")[-1]
    user_tag = resolve_user_tag(domain)

    matches = retrieve_chunks(request.question, user_tag=user_tag)
    context_chunks = [
        {
            "text": match["metadata"]["text"],
            "score": match["score"],
            "doc_id": match["metadata"]["doc_id"],
            "access_level": match["metadata"]["access_level"],
            "sender": match["metadata"].get("sender", ""),
            "subject": match["metadata"].get("subject", ""),
            "date": match["metadata"].get("date", ""),
            "source_type": match["metadata"].get("source_type", "unknown"),
        }
        for match in matches
    ]

    answer = generate_answer(request.question, context_chunks)

    sources = [
        SourceChunk(
            text=match["metadata"]["text"],
            score=match["score"],
            doc_id=match["metadata"]["doc_id"],
            access_level=match["metadata"]["access_level"],
            sender=match["metadata"].get("sender"),
            subject=match["metadata"].get("subject"),
            date=match["metadata"].get("date"),
            source=match["metadata"].get("source"),
            source_type=match["metadata"].get("source_type"),
        )
        for match in matches
    ]

    return QueryResponse(question=request.question, answer=answer, sources=sources)
