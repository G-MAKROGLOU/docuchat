"""Writes the stored chunks for the anchor hit rate: document, page, anchor
and text. The Node script `frontend/scripts/anchor-hit-rate.mjs` reads the file.
  python -m evals.export_anchors"""

import asyncio
import json
import sys
from pathlib import Path

from psycopg.rows import dict_row

from app.config import get_settings
from app.infrastructure.database import build_pool

OUT = Path(__file__).parent / "cache" / "anchors.json"
# No vectors: the export needs only the text fields.
QUERY = """
SELECT c.id::text AS chunk, c.document_id::text AS document, c.drug_name AS drug,
       c.section_number || ' ' || c.section_title AS section, c.page_start AS page,
       c.page_end AS "pageEnd", c.anchor, c.content AS text
FROM chunks c WHERE c.embedding_model = %s ORDER BY c.document_id, c.page_start, c.id
"""


async def _export() -> int:
    settings = get_settings()
    async with build_pool(settings) as pool, pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(QUERY, (settings.embedding_model,))
        rows = await cursor.fetchall()
    OUT.parent.mkdir(exist_ok=True)
    await asyncio.to_thread(OUT.write_text, json.dumps(rows), "utf-8")
    print(f"wrote {len(rows)} chunks to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_export()))
