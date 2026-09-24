def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks.

    - chunk_size: how many characters each chunk contains
    - overlap: how many characters from the end of one chunk
               are repeated at the start of the next chunk

    Example with chunk_size=500, overlap=50:
        Chunk 1 -> characters [0:500]
        Chunk 2 -> characters [450:950]   (steps back 50 to preserve context)
        Chunk 3 -> characters [900:1400]
        ... and so on until the text runs out.
    """
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        # Move start forward, but step back by 'overlap' to preserve context
        start += chunk_size - overlap

    return chunks

def chunk_record(record: dict, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    """
    Takes a record dictionary containing 'text' and returns a list of 
    record dictionaries where 'text' is replaced by a chunk of the original text.
    """
    text = record.get("text", "")
    text_chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    
    chunked_records = []
    for chunk in text_chunks:
        new_record = record.copy()
        new_record["text"] = chunk
        chunked_records.append(new_record)
        
    return chunked_records
