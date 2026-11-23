import asyncio
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.dependencies import (
    get_app_settings,
    get_document_repository,
    get_label_catalog,
    get_label_queue_repository,
)
from app.api.schemas.labels import (
    AddLabelRequest,
    CatalogLabelResponse,
    QueueEntryResponse,
    QueueResponse,
)
from app.application.label_queue import (
    LabelKnownError,
    LabelNotFoundError,
    add_label,
)
from app.config import Settings
from app.domain.documents import DocumentRepository
from app.domain.label_queue import LabelCatalog, LabelQueueRepository, QueueEntry

router = APIRouter(tags=["labels"])

CATALOG_ERRORS = (OSError, ValueError, KeyError)
UNAVAILABLE = "DailyMed could not be reached."


def _entry(entry: QueueEntry) -> QueueEntryResponse:
    return QueueEntryResponse(
        set_id=entry.set_id,
        title=entry.title,
        status=entry.status.value,
        failure_reason=entry.failure_reason,
        created_at=entry.created_at,
    )


@router.get("/labels")
async def list_labels(
    queue: Annotated[LabelQueueRepository, Depends(get_label_queue_repository)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
) -> QueueResponse:
    listing = await queue.list_page(page, page_size)
    return QueueResponse(
        items=[_entry(entry) for entry in listing.entries],
        total=listing.total,
        queued_total=listing.queued_total,
        added_total=listing.added_total,
        failed_total=listing.failed_total,
        labels_per_pass=settings.label_queue_batch,
    )


@router.get("/labels/search")
async def search_labels(
    catalog: Annotated[LabelCatalog, Depends(get_label_catalog)],
    queue: Annotated[LabelQueueRepository, Depends(get_label_queue_repository)],
    documents: Annotated[DocumentRepository, Depends(get_document_repository)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> list[CatalogLabelResponse]:
    """Labels that DailyMed has for the name, without those in the corpus or in the queue."""
    # DailyMed is asked for more than are shown, because the known labels are left out.
    try:
        found = await asyncio.to_thread(catalog.search, q, settings.label_fetch_limit)
    except CATALOG_ERRORS:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from None
    set_ids = [label.set_id for label in found]
    taken = await queue.known(set_ids) | await documents.known_source_ids(set_ids)
    new = [label for label in found if label.set_id not in taken]
    return [CatalogLabelResponse(**asdict(label)) for label in new[: settings.label_search_limit]]


@router.post(
    "/labels",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "The catalogue does not know this set ID."},
        502: {"description": "DailyMed could not be reached."},
        409: {"description": "The label is in the corpus or in the queue."},
    },
)
async def queue_label(
    body: AddLabelRequest,
    catalog: Annotated[LabelCatalog, Depends(get_label_catalog)],
    queue: Annotated[LabelQueueRepository, Depends(get_label_queue_repository)],
    documents: Annotated[DocumentRepository, Depends(get_document_repository)],
) -> CatalogLabelResponse:
    try:
        label = await add_label(catalog, queue, documents, body.set_id)
    except CATALOG_ERRORS:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from None
    except LabelNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "DailyMed does not know this set ID."
        ) from None
    except LabelKnownError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The label is already in the corpus or queue."
        ) from None
    return CatalogLabelResponse(**asdict(label))


@router.delete(
    "/labels/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "No queued or failed entry with this set ID."}},
)
async def remove_label(
    set_id: str,
    queue: Annotated[LabelQueueRepository, Depends(get_label_queue_repository)],
) -> Response:
    if not await queue.remove(set_id.strip().lower()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No queued or failed entry.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
