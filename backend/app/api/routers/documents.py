import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_document_repository, get_document_store
from app.api.http_range import RangeNotSatisfiableError, parse_range
from app.domain.documents import DocumentRepository
from app.domain.storage import DocumentStore

router = APIRouter(tags=["documents"])


@router.get(
    "/documents/{document_id}/file",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The whole PDF."},
        206: {"content": {"application/pdf": {}}, "description": "One byte range."},
        404: {"description": "Unknown document."},
        416: {"description": "Range not satisfiable."},
    },
)
async def get_document_file(
    document_id: UUID,
    request: Request,
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    store: Annotated[DocumentStore, Depends(get_document_store)],
) -> Response:
    document = await repository.get(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    # Check before the headers go out; a stream cannot change its status later.
    if not await asyncio.to_thread(store.exists, document.storage_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found")

    size = document.size_bytes
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{document.sha256}"',
        "Content-Disposition": f'inline; filename="{document.id}.pdf"',
    }
    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiableError:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**headers, "Content-Range": f"bytes */{size}"},
        )

    if byte_range is None:
        return StreamingResponse(
            store.get_stream(document.storage_key),
            media_type="application/pdf",
            headers={**headers, "Content-Length": str(size)},
        )
    start, end = byte_range
    data = await asyncio.to_thread(store.get_range, document.storage_key, start, end)
    return Response(
        content=data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="application/pdf",
        headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"},
    )
