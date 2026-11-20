"""Turn label sections into chunks that keep their section, pages and anchor."""

import bisect
import uuid
from collections.abc import Sequence

from app.domain.entities import Chunk, LabelSection
from app.domain.ports import TextSplitter, TokenCounter

ANCHOR_WORDS = 8


def anchor_of(content: str) -> str:
    return " ".join(content.split()[:ANCHOR_WORDS])


def embedding_input(brand: str, generic: str, section: str, content: str, *, prefix: bool) -> str:
    """section is "<number> <title>", for example "2.1 Recommended Dosage"."""
    if not prefix:
        return content
    drug = f"{brand} ({generic})" if brand else generic
    return f"Drug: {drug}. Section: {section}.\n{content}"


def build_chunks(
    document_id: uuid.UUID,
    drug_name: str,
    sections: Sequence[LabelSection],
    splitter: TextSplitter,
    counter: TokenCounter,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        if not section.lines:
            continue
        # One text per section; remember where each line starts, to map spans back to pages.
        offsets: list[int] = []
        pages: list[int] = []
        parts: list[str] = []
        position = 0
        for line in section.lines:
            offsets.append(position)
            pages.append(line.page)
            parts.append(line.text)
            position += len(line.text) + 1
        text = " ".join(parts)

        def page_at(offset: int, offsets: list[int] = offsets, pages: list[int] = pages) -> int:
            return pages[bisect.bisect_right(offsets, offset) - 1]

        for span in splitter.split(text):
            content = span.text.strip()
            if not content:
                continue
            chunks.append(
                Chunk(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    drug_name=drug_name,
                    section_number=section.number,
                    section_title=section.title,
                    page_start=page_at(span.start),
                    page_end=page_at(span.start + len(span.text) - 1),
                    content=content,
                    anchor=anchor_of(content),
                    token_count=counter.count(content),
                )
            )
    return chunks
