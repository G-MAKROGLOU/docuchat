# Retrieval

The `retrieve` node of the chat graph (`app/application/chat/graph.py`) runs this path for each search. `DrugDetector` maps the search query to products and their preferred labels. `RetrievalService.retrieve()` searches only those labels (document IDs), in both legs. It fuses the two lists with RRF and selects the context.

## Chat turn graph

`build_chat_graph()` in `chat/graph.py` (LangGraph). `ChatService.ask()` runs it with the last 10 history messages and a 120 s deadline per turn. The nodes send stream events; the API sends them as SSE.

```mermaid
flowchart TD
    start(["START"]) --> guard["guard<br/>plain code: empty, too long,<br/>prompt injection"]
    guard -->|"problem: refusal out_of_scope"| stop(["END"])
    guard --> intake["intake (CHAT role, cached)<br/>JSON: action, reply, medicines, query"]
    intake -->|"action reply"| reply["reply<br/>token + final"]
    intake -->|"search with a query"| retrieve
    intake -->|"search, no usable query"| rewrite["rewrite (REWRITE role, cached)<br/>first: query from the question<br/>retry: query plus grade feedback"]
    reply --> suggest
    rewrite --> retrieve["retrieve<br/>detect drugs, search the labels"]
    retrieve -->|"refusal drug_not_in_corpus<br/>or no_relevant_context"| stop
    retrieve -->|"ambiguous drug"| clarify["clarify<br/>clarify + token + final"]
    retrieve -->|"sources"| grade["grade<br/>rule_check, then the LLM grader (GRADE role)<br/>verdict sufficient, partial or insufficient"]
    clarify --> stop
    grade -->|"weak, first attempt: retry"| rewrite
    grade -->|"nothing relevant on the retry:<br/>refusal no_relevant_context"| stop
    grade -->|"sources event"| generate["generate (GENERATE role)<br/>collects the answer, sends no tokens"]
    generate --> validate["validate<br/>citations, uncited figures,<br/>cited dose check on excerpt_text, links"]
    validate -->|"refusal no_valid_citation<br/>or no_relevant_context"| stop
    validate -->|"checked answer: one token + final"| suggest["suggest (CHAT role, cached)<br/>suggestions event, a failure is ignored"]
    suggest --> stop
```

Stream event types: `status`, `sources`, `token`, `final`, `clarify`, `refusal`, `suggestions`, `error`. The rewrite node runs only when the intake gives no usable query (missing, or longer than 500 characters), or on the one retry after a weak grade. A retry merges the relevant excerpts of both searches. The grader mode (`off`, `rule`, `llm`) is a runtime setting; `llm` is the default.

## Drug detection and the search decision

```mermaid
flowchart TD
    q(["search query<br/>from intake, or from rewrite on a retry"]) --> src

    src["VersionedCache: one DrugDetector per library version<br/>rebuilt at most every 30 s"] --> det

    subgraph detect["DrugDetector.detect()"]
        det["catalog: one entry per ingested label<br/>brand labels first, then the newest<br/>product = active ingredients + dosage form group<br/>first label of a product = its preferred label"]
        exact["1. exact name key match, one pattern, longest key first<br/>name with several products: a form word picks one,<br/>else the products wait for a clarify question"]
        tail["2. per remaining word: tail of a longer library name<br/>(7 letters or more) gives not_in_corpus"]
        fuzzy["3. RapidFuzz best(), floor 70<br/>accept: best >= 80 and second < best - 12<br/>ambiguous: second >= best - 12<br/>close to one named drug and one other: the other"]
        stem["4. no match but a drug stem ending<br/>(-pril, -statin, ...) gives not_in_corpus"]
        det --> exact --> tail --> fuzzy --> stem
    end

    stem --> res["DrugDetection: drugs, fuzzy, ambiguous (at most 5),<br/>not_in_corpus, labels (preferred label of each drug)"]
    res --> retry{"retry with labels<br/>from the first search?"}
    retry -->|yes| keep["labels = detected labels,<br/>else the first search's labels"]
    retry -->|no| amb{"ambiguous?"}
    amb -->|yes| clarify(["clarify node: 'Name (form)' candidates, no search"])
    amb -->|no| outside{"no label, and not_in_corpus<br/>or an intake medicine with no match?"}
    outside -->|yes| refuse(["refusal drug_not_in_corpus<br/>library list only up to 100 names"])
    outside -->|no| hints["section_hints(query, comparing = 2 or more labels)"]
    keep --> hints
    hints --> call(["retrieve(query, labels, section_hints, mode=hybrid)<br/>no label: no filter"])
```

## Hybrid search, fusion and selection

```mermaid
flowchart TD
    call(["retrieve(query, labels, section_hints, mode)"]) --> emb

    emb["embedding leg: CachedEmbedder.embed_query(query)<br/>Redis key: model, dimensions, SHA-256 of the query<br/>miss: OpenRouter, then stored for 30 days"]
    emb --> groups["groups: one per label when 2 or more labels,<br/>else one group with all labels"]

    subgraph per["per group, asyncio.gather, TOP_K = 20 each (runtime setting)"]
        vec["vector leg: ORDER BY cosine distance to the query vector<br/>WHERE document_id = ANY(labels)<br/>AND embedding_model = current model<br/>HNSW, iterative_scan = strict_order"]
        bm["BM25 leg: content ||| query<br/>OR content ### query boost 2<br/>OR section_title ||| query boost 0.5<br/>document_id = ANY(labels) inside the index<br/>ORDER BY pdb.score(id)"]
    end
    groups --> per

    note1["each leg, the embedding too: 5 s timeout<br/>a failed or slow leg gives no rows and goes into degraded<br/>no embedding: BM25 only<br/>no search leg answered: the first error fails the turn"] -.-> per

    per --> inter["interleave the groups per leg:<br/>first of each group, then the second, ..."]
    inter --> fuse["fusion.fuse()<br/>score = sum of 1 / (60 + rank) over both lists<br/>hinted sections act as a third ranked list:<br/>+ 1 / (60 + rank among the hinted chunks)<br/>sort by score"]
    fuse --> cmp{"2 or more labels?"}
    cmp -->|yes| rr["round robin: up to 3 top chunks per label first,<br/>then the rest in fused order"]
    cmp -->|no| order["fused order"]
    rr --> budget
    order --> budget

    budget["select(): take chunks in that order<br/>stop at 8 chunks<br/>skip a chunk that passes 3,500 tokens,<br/>except the first chunk overall and<br/>the first chunk of each compared label"]
    budget --> out(["RetrievalResult<br/>candidates = fused list<br/>selected = chosen chunks in fused order<br/>degraded = failed legs"])
```

Modes: `vector` runs only the vector leg, `bm25` only the BM25 leg, `hybrid` both. The chat uses `hybrid`. The eval runner sets the other modes.

Section hints come from `topics.py`: question words map to label sections, for example "breastfeed" to 8.2 and "dose" to 2. A comparison without a topic gets sections 1, 2, 4, 5 and 6.

The model reads each selected chunk as `excerpt_text(chunk)`: the stored `table_header` (table caption and header row), then the chunk text.
