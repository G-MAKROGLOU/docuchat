"""Builders for domain objects. Each keyword has the value most tests need."""

import uuid

import pymupdf

from app.application.chat import SourceRef
from app.domain.documents import Document, DocumentStatus
from app.domain.entities import Chunk
from app.domain.runtime_settings import RuntimeSettings
from app.domain.storage import document_key

RUNTIME_DEFAULTS = RuntimeSettings(
    chunk_tokens=500,
    overlap_tokens=50,
    top_k=20,
    embedding_model="m/embed",
    chat_model="a/chat",
    rewrite_model="a/rewrite",
    grade_model="a/grade",
    generate_model="a/generate",
    reasoning_effort="low",
    grader_mode="llm",
)


def label_of(drug: str) -> uuid.UUID:
    """The test label (document ID) of a drug name: the same name gives the same label."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"label:{drug}")


def make_chunk(
    content: str,
    *,
    drug: str = "Lipitor",
    section: str = "2",
    title: str = "Title",
    page_start: int = 4,
    page_end: int | None = None,
    tokens: int = 10,
    anchor: str | None = None,
    chunk_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    embedding: tuple[float, ...] | None = None,
    embedding_model: str | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id or uuid.uuid4(),
        document_id=document_id or label_of(drug),
        drug_name=drug,
        section_number=section,
        section_title=title,
        page_start=page_start,
        page_end=page_start if page_end is None else page_end,
        content=content,
        anchor=content if anchor is None else anchor,
        token_count=tokens,
        embedding=embedding,
        embedding_model=embedding_model,
    )


def make_document(
    brand: str = "Brand",
    generic: str = "generic",
    *,
    document_id: uuid.UUID | None = None,
    manufacturer: str = "Maker",
    source_id: str = "set-1",
    sha: str = "a" * 64,
    storage_key: str | None = None,
    size_bytes: int = 1,
    status: DocumentStatus = DocumentStatus.STORED,
    page_count: int | None = None,
) -> Document:
    doc_id = document_id or uuid.uuid4()
    return Document(
        id=doc_id,
        brand_name=brand,
        generic_name=generic,
        manufacturer=manufacturer,
        source_id=source_id,
        storage_key=document_key(doc_id, sha) if storage_key is None else storage_key,
        sha256=sha,
        size_bytes=size_bytes,
        status=status,
        page_count=page_count,
    )


def make_pdf(
    *items: tuple[float, float, str, str], pages: int = 1, size: tuple[int, int] | None = None
) -> bytes:
    """items: (x, y, text, font) on page 1; font "helv" is regular, "hebo" is bold."""
    doc = pymupdf.open()
    for _ in range(pages):
        if size is None:
            doc.new_page()
        else:
            doc.new_page(width=size[0], height=size[1])
    for x, y, text, font in items:
        doc[0].insert_text((x, y), text, fontname=font, fontsize=11)
    data: bytes = doc.tobytes()
    return data


def sources_of(*texts: str) -> list[SourceRef]:
    return [SourceRef(f"S{i}", make_chunk(t)) for i, t in enumerate(texts, start=1)]
