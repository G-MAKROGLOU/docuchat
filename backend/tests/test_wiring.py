import uuid

from app.domain.documents import Document, DocumentStatus
from app.wiring import drug_detector
from tests.support.factories import make_document


def document(brand: str, generic: str, status: DocumentStatus) -> Document:
    return make_document(brand, generic, source_id=uuid.uuid4().hex, storage_key="k", status=status)


def test_the_catalog_has_ingested_labels_named_by_brand_else_generic() -> None:
    detector = drug_detector(
        [
            document("Lipitor", "atorvastatin", DocumentStatus.INGESTED),
            document("", "terbinafine", DocumentStatus.INGESTED),
            document("Crestor", "rosuvastatin", DocumentStatus.STORED),
        ]
    )

    assert detector.detect("atorvastatin, terbinafine or Crestor?").drugs == (
        "Lipitor",
        "terbinafine",
    )
