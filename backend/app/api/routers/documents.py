import asyncio
import itertools
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_app_settings,
    get_cache,
    get_document_repository,
    get_document_store,
    get_page_renderer,
)
from app.api.http_range import RangeNotSatisfiableError, parse_range
from app.api.schemas.documents import DocumentListResponse, DocumentSummary
from app.application.thumbnails import thumbnail_png
from app.config import Settings
from app.domain.documents import Document, DocumentRepository, PageRenderer
from app.domain.ports import Cache
from app.domain.storage import DocumentStore, ObjectNotFoundError

router = APIRouter(tags=["documents"])


@router.get("/documents")
async def list_documents(
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    q: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DocumentListResponse:
    result = await repository.search(q.strip(), limit=page_size, offset=(page - 1) * page_size)
    return DocumentListResponse(
        items=[
            DocumentSummary(
                id=d.id,
                brand_name=d.brand_name,
                generic_name=d.generic_name,
                page_count=d.page_count,
                status=d.status,
                ingested_at=d.ingested_at,
                failure_reason=d.failure_reason,
            )
            for d in result.items
        ],
        total=result.total,
        page=page,
        page_size=page_size,
    )


def _content_disposition(document: Document, download: bool) -> str:
    if not download:
        return f'inline; filename="{document.id}.pdf"'
    # ASCII fallback first; RFC 6266 clients use the UTF-8 title.
    title = quote(f"{document.brand_name.strip() or document.generic_name}.pdf", safe="")
    return f"attachment; filename=\"{document.id}.pdf\"; filename*=UTF-8''{title}"


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    tags = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
    return "*" in tags or etag in tags


@router.get(
    "/documents/{document_id}/thumbnail",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "Page 1 as a PNG."},
        304: {"description": "The cached thumbnail is current."},
        404: {"description": "Unknown document."},
    },
)
async def get_document_thumbnail(  # noqa: PLR0913  # four injected ports and the settings
    document_id: UUID,
    request: Request,
    *,
    settings: Annotated[Settings, Depends(get_app_settings)],
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    store: Annotated[DocumentStore, Depends(get_document_store)],
    renderer: Annotated[PageRenderer, Depends(get_page_renderer)],
    cache: Annotated[Cache, Depends(get_cache)],
) -> Response:
    document = await repository.get(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    # The width is in the tag, so a new width does not revalidate to an old image.
    width = settings.thumbnail_width
    etag = f'"{document.sha256}-w{width}"'
    headers = {
        "ETag": etag,
        "Cache-Control": f"public, max-age={settings.thumbnail_max_age_seconds}",
    }
    if _etag_matches(request.headers.get("if-none-match"), headers["ETag"]):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    def render() -> bytes:
        pdf = b"".join(store.get_stream(document.storage_key))
        return renderer.render_first_page(pdf, width)

    try:
        png = await thumbnail_png(
            cache,
            f"{document.storage_key}:{etag}",
            render,
            slots=request.app.state.thumbnail_slots,
            ttl_seconds=settings.thumbnail_ttl_seconds,
        )
    except ObjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found") from exc
    return Response(content=png, media_type="image/png", headers=headers)


FILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "The whole PDF."},
    206: {"content": {"application/pdf": {}}, "description": "One byte range."},
    404: {"description": "Unknown document."},
    416: {"description": "Range not satisfiable."},
}


@router.get(
    "/documents/{document_id}/file",
    response_class=StreamingResponse,
    responses=FILE_RESPONSES,
)
async def get_document_file(
    document_id: UUID,
    request: Request,
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    store: Annotated[DocumentStore, Depends(get_document_store)],
    download: bool = False,
) -> Response:
    document = await repository.get(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    size = document.size_bytes
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{document.sha256}"',
        "Content-Disposition": _content_disposition(document, download),
    }
    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiableError:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**headers, "Content-Range": f"bytes */{size}"},
        )

    if byte_range is None:
        # Read the first chunk before the headers go out; a stream cannot change its status later.
        stream = store.get_stream(document.storage_key)
        try:
            first = await asyncio.to_thread(next, stream, b"")
        except ObjectNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found") from exc
        return StreamingResponse(
            itertools.chain([first], stream),
            media_type="application/pdf",
            headers={**headers, "Content-Length": str(size)},
        )
    start, end = byte_range
    try:
        data = await asyncio.to_thread(store.get_range, document.storage_key, start, end)
    except ObjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found") from exc
    return Response(
        content=data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="application/pdf",
        headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"},
    )


@router.get(
    "/documents/{document_id}/file/{filename}",
    response_class=StreamingResponse,
    responses=FILE_RESPONSES,
)
async def get_named_document_file(
    document_id: UUID,
    filename: str,
    request: Request,
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> Response:
    """The same PDF. The PDF viewer saves a download under the last path segment."""
    return await get_document_file(document_id, request, repository, store)
