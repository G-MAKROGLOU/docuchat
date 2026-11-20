"""Rebuild retrieval_fixture.json with live embeddings (needs the OpenRouter key).

Usage: python -m tests.fixtures.build_retrieval_fixture
"""

import asyncio
import json
from pathlib import Path

from app.application.chunking import embedding_input
from app.config import get_settings
from app.infrastructure.models import ModelFactory

OUTPUT = Path(__file__).with_name("retrieval_fixture.json")

# Fictional drugs, so the fixture never collides with corpus rows in a shared test database.
CHUNKS = [
    ("Fixtorvan", "fixtorvastatin", "2.2", "Recommended Dosage in Adults",
     "The recommended starting dose of FIXTORVAN is 10 mg or 20 mg once daily. The dose "
     "range is 10 mg to 80 mg once daily."),
    ("Fixtorvan", "fixtorvastatin", "5.1", "Myopathy and Rhabdomyolysis",
     "FIXTORVAN may cause myopathy and rhabdomyolysis. Acute kidney injury secondary to "
     "myoglobinuria has occurred. Risk factors include age 65 years or greater, uncontrolled "
     "hypothyroidism and renal impairment."),
    ("Fixtorvan", "fixtorvastatin", "4", "CONTRAINDICATIONS",
     "Acute liver failure or decompensated cirrhosis. Hypersensitivity to fixtorvastatin."),
    ("Fixtorvan", "fixtorvastatin", "16", "HOW SUPPLIED/STORAGE AND HANDLING",
     "Store at 20 to 25 degrees C (68 to 77 degrees F). Keep the bottle tightly closed."),
    ("Fixaban", "fixapixaban", "2.1", "Recommended Dose",
     "The recommended dose of FIXABAN is 5 mg taken orally twice daily."),
    ("Fixaban", "fixapixaban", "2.2", "Dose Adjustments",
     "In patients with at least two of the following characteristics: age 80 years or older, "
     "body weight 60 kg or less, or serum creatinine 1.5 mg/dL or greater, the recommended "
     "dose of FIXABAN is 2.5 mg twice daily."),
    ("Fixaban", "fixapixaban", "BW", "WARNING: PREMATURE DISCONTINUATION",
     "Premature discontinuation of any oral anticoagulant, including FIXABAN, increases the "
     "risk of thrombotic events."),
    ("Fixaban", "fixapixaban", "8.2", "Lactation",
     "Women should be advised not to breastfeed during treatment with FIXABAN."),
]  # fmt: skip
QUERIES = {
    "exact_dose": "2.5 mg twice daily",
    "paraphrase": "Can this cholesterol pill damage my muscles?",
}


async def main() -> None:
    embedder = ModelFactory(get_settings()).embedder()
    inputs = [
        embedding_input(brand, generic, f"{number} {title}", content, prefix=True)
        for brand, generic, number, title, content in CHUNKS
    ]
    chunk_vectors = await embedder.embed_documents(inputs)
    query_vectors = {name: await embedder.embed_query(q) for name, q in QUERIES.items()}
    OUTPUT.write_text(
        json.dumps(
            {
                "model": get_settings().embedding_model,
                "chunks": [
                    {
                        "drug_name": brand,
                        "section_number": number,
                        "section_title": title,
                        "content": content,
                        "embedding": [round(v, 6) for v in vector],
                    }
                    for (brand, _, number, title, content), vector in zip(
                        CHUNKS, chunk_vectors, strict=True
                    )
                ],
                "queries": {
                    name: {"text": QUERIES[name], "embedding": [round(v, 6) for v in vector]}
                    for name, vector in query_vectors.items()
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
