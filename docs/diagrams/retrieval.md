# Retrieval

`DrugDetector` finds the drug names in the question. `RetrievalService.retrieve()` runs the vector and BM25 searches in parallel with the same drug filter, fuses them with RRF and selects the context. Today only `search_cli.py` calls this path; no API route uses it yet.

```mermaid
flowchart TD
    q(["question"]) --> det

    subgraph detect["drug_detection.DrugDetector.detect()"]
        det["catalog: one entry per ingested document<br/>keys: brand, generic, generic without salt words"]
        exact["1. exact key match, word bounds, longest key first"]
        fuzzy["2. fuzzy match per remaining word (RapidFuzz ratio)<br/>accept: best >= 85 and second < best - 12<br/>ambiguous: second >= best - 12 (floor 75)<br/>ambiguous word close to one named drug and one other: the other"]
        stem["3. no match but drug stem ending (-pril, -statin, ...)<br/>not_in_corpus"]
        det --> exact --> fuzzy --> stem
    end

    stem --> res["DrugDetection: drugs, fuzzy, ambiguous, not_in_corpus"]
    res --> amb{"ambiguous?"}
    amb -->|"yes (search_cli)"| clarify(["ask to clarify, no search"])
    amb -->|no| retrieve(["retrieve(query, drugs, section_hints, mode=hybrid)"])

    retrieve --> check{"first call:<br/>indexed embedding models<br/>other than EMBEDDING_MODEL?"}
    check -->|yes| mismatch(["EmbeddingModelMismatchError"])
    check -->|no| par

    subgraph par["asyncio.gather, TOP_K = 20 each"]
        vec["Embedder.embed_query(query)<br/>then vector_search<br/>ORDER BY cosine distance to the query vector<br/>HNSW, iterative_scan = strict_order"]
        bm["text_search<br/>content ||| query OR content ### query boost 2<br/>ORDER BY pdb.score(id)"]
    end
    note1["filter when drugs is not empty:<br/>drug_name = ANY(drugs)"] -.-> par

    par --> fuse["fusion.fuse()<br/>score = sum of 1 / (60 + rank) over both lists<br/>+ 0.0003 if section_number in section_hints<br/>sort by score"]
    fuse --> cmp{"2 or more drugs?"}
    cmp -->|yes| rr["round robin: up to 3 top chunks per drug first,<br/>then the rest in fused order"]
    cmp -->|no| order["fused order"]
    rr --> budget
    order --> budget

    budget["select(): take chunks in that order<br/>stop at 8 chunks<br/>skip a chunk that passes 3,500 tokens,<br/>except the first chunk overall and<br/>the first chunk of each compared drug"]
    budget --> out(["RetrievalResult<br/>candidates = fused list<br/>selected = chosen chunks in fused order"])
```

Modes: `vector` runs only the vector search, `bm25` only the BM25 search, `hybrid` both.
