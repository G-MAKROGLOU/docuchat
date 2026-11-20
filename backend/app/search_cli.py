"""Print the ranked chunks for questions. Usage: python -m app.search_cli [QUESTION ...]"""

import argparse
import asyncio
import sys

from app.application.drug_detection import DrugDetector, DrugEntry
from app.application.retrieval import RetrievalService, SearchMode
from app.config import get_settings
from app.domain.documents import DocumentStatus
from app.infrastructure.chunk_search import PostgresChunkSearch
from app.infrastructure.document_repository import PostgresDocumentRepository
from app.infrastructure.models import ModelFactory
from app.infrastructure.name_similarity import RapidFuzzSimilarity

SAMPLE_QUESTIONS = [
    "What is the recommended starting dose of Lipitor?",
    "Compare the bleeding risk of Eliquis and Xarelto.",
    "Can Celebrex cause a heart attack or stroke?",
    "What should a patient know about infections while taking Xeljanz?",
    "Is lipitr safe during pregnancy?",
]


async def run(questions: list[str], mode: SearchMode) -> None:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    documents = await PostgresDocumentRepository(database_url).list_all()
    detector = DrugDetector(
        [
            DrugEntry(
                name=d.brand_name or d.generic_name, brand=d.brand_name, generic=d.generic_name
            )
            for d in documents
            if d.status is DocumentStatus.INGESTED
        ],
        RapidFuzzSimilarity(),
    )
    service = RetrievalService(
        PostgresChunkSearch(database_url),
        ModelFactory(settings).embedder(),
        settings.embedding_model,
    )
    for question in questions:
        detection = detector.detect(question)
        print(f"\nQ: {question}")
        print(
            f"   drugs={list(detection.drugs)} fuzzy={list(detection.fuzzy)} "
            f"ambiguous={list(detection.ambiguous)} not_in_corpus={list(detection.not_in_corpus)}"
        )
        if detection.ambiguous:
            print("   -> clarify: more than one close drug name")
            continue
        result = await service.retrieve(question, drugs=detection.drugs, mode=mode)
        tokens = sum(f.chunk.token_count for f in result.selected)
        print(
            f"   mode={result.mode} filter={list(result.drugs) or 'none'} "
            f"candidates={len(result.candidates)} selected={len(result.selected)} tokens={tokens}"
        )
        for f in result.selected:
            c = f.chunk
            pages = f"p{c.page_start}" + (f"-{c.page_end}" if c.page_end != c.page_start else "")
            print(
                f"   {f.score:.4f} v={f.vector_rank or '-':>2} b={f.bm25_rank or '-':>2} "
                f"{c.drug_name} | {c.section_number} {c.section_title[:38]} | {pages} | "
                f"{c.content[:70]}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[m.value for m in SearchMode], default="hybrid")
    parser.add_argument("questions", nargs="*")
    args = parser.parse_args(argv)
    asyncio.run(run(args.questions or SAMPLE_QUESTIONS, SearchMode(args.mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
