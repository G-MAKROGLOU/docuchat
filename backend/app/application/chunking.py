"""Turn label sections into chunks that keep their section, pages and anchor."""

import uuid
from collections.abc import Callable, Sequence

from app.application.label_sections import BOXED_WARNING
from app.domain.documents import Document
from app.domain.entities import Chunk, LabelSection
from app.domain.ports import TextSplitter, TokenCounter

ANCHOR_WORDS = 8


def anchor_of(content: str) -> str:
    return " ".join(content.split()[:ANCHOR_WORDS])


def embedding_input(  # noqa: PLR0913  # the parts of one embedding input
    brand: str, generic: str, section: str, content: str, *, prefix: bool, context: str = ""
) -> str:
    """section is "<number> <title>", for example "2.1 Recommended Dosage". context is the
    caption and header row of the table that the chunk continues."""
    if context:
        content = f"{context}\n{content}"
    if not prefix:
        return content
    drug = f"{brand} ({generic})" if brand else generic
    return f"Drug: {drug}. Section: {section}.\n{content}"


def _is_row(line: str) -> bool:
    return " | " in line


def table_context(text: str, start: int) -> str:
    """The caption and header row of the table that a chunk starting at start continues,
    without the lines that the chunk already holds. Empty outside a table."""
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        lines.append((offset, line))
        offset += len(line) + 1
    current = max((i for i, (off, _) in enumerate(lines) if off <= start), default=0)
    if not _is_row(lines[current][1]):
        return ""
    first = current
    while first > 0 and _is_row(lines[first - 1][1]):
        first -= 1
    context = [lines[first]]
    if first > 0 and lines[first - 1][1].lower().startswith("table"):
        context.insert(0, lines[first - 1])
    return "\n".join(line for off, line in context if off < start)


def build_chunks(
    document: Document,
    sections: Sequence[LabelSection],
    splitter: TextSplitter,
    counter: TokenCounter,
    pages_of: Callable[[Sequence[str]], list[tuple[int, int]]],
) -> list[Chunk]:
    """pages_of gives the first and last PDF page of each chunk text, in reading order."""
    drug_name = document.brand_name or document.generic_name
    drafts = [
        (section, span.text.strip(), table_context(section.text, span.start))
        for section in sections
        for span in splitter.split(section.text)
        if span.text.strip()
    ]
    # The first chunk of a section is located with its heading, so its pages start there.
    pages = pages_of(
        [
            f"{_heading(section)}\n{content}"
            if i == 0 or drafts[i - 1][0] is not section
            else content
            for i, (section, content, _) in enumerate(drafts)
        ]
    )
    return [
        Chunk(
            id=uuid.uuid4(),
            document_id=document.id,
            drug_name=drug_name,
            section_number=section.number,
            section_title=section.title,
            page_start=page_start,
            page_end=page_end,
            content=content,
            anchor=anchor_of(content),
            token_count=counter.count(content),
            table_header=header,
        )
        for (section, content, header), (page_start, page_end) in zip(drafts, pages, strict=True)
    ]


def _heading(section: LabelSection) -> str:
    """The heading as the PDF shows it: "2.1 Title", or the title alone for the boxed warning."""
    return section.title if section.number == BOXED_WARNING else f"{section.number} {section.title}"
