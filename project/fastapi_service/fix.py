import os
from dotenv import load_dotenv
load_dotenv()

from services.postgres import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("UPDATE documents SET pinecone_indexed = FALSE WHERE content = '' AND attachment_path IS NOT NULL")
        print(f"Reset {cur.rowcount} documents.")
