def answer_question(chunks: list[str], question: str) -> dict:
    """
    Simple keyword-based Q&A over a list of text chunks.

    Searches each chunk for any of the question's keywords and returns
    the best matching chunk as the answer.  This is intentionally
    lightweight — full semantic Q&A is handled by the /semantic_ask
    endpoint using vector embeddings.
    """
    if not chunks:
        return {
            "question": question,
            "answer": "No content available.",
            "matched_chunk": None,
        }

    question_lower = question.lower()
    keywords = [w for w in question_lower.split() if len(w) > 2]

    best_chunk = None
    best_score = 0

    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(1 for kw in keywords if kw in chunk_lower)
        if score > best_score:
            best_score = score
            best_chunk = chunk

    if best_chunk and best_score > 0:
        return {
            "question": question,
            "answer": best_chunk,
            "matched_chunk": best_chunk,
            "score": best_score,
        }

    return {
        "question": question,
        "answer": "No relevant content found for your question.",
        "matched_chunk": None,
        "score": 0,
    }
