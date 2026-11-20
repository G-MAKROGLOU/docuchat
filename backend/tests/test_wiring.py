import uuid

from app.domain.documents import Document, DocumentStatus
from app.wiring import drug_detector


def document(brand: str, generic: str, status: DocumentStatus) -> Document:
    return Document(
        id=uuid.uuid4(),
        brand_name=brand,
        generic_name=generic,
        manufacturer="Maker",
        source_id=uuid.uuid4().hex,
        storage_key="k",
        sha256="a" * 64,
        size_bytes=1,
        status=status,
    )


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
