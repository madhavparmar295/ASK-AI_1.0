import json
import os
import uuid

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "../storage/uploads")
DATASET_FILE = os.path.join(UPLOAD_DIR, "dataset.json")


def build_dataset(filename: str, chunks: list[str]) -> None:

    if os.path.exists(DATASET_FILE):
        with open(DATASET_FILE, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    else:
        dataset = []

    for index, chunk in enumerate(chunks):
        dataset.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "document": filename,
                "chunk_index": index,
                "text": chunk,
            }
        )

    with open(DATASET_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
