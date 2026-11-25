# Facts for the README

Source material for `README.md`. Each fact names its evidence: a file or a command. Values are as of 2026-11-24.

## Run it

- Prerequisites: Docker with Compose v2, and an OpenRouter API key.
- `infra/setup.sh` (Windows: `infra\setup.ps1`) checks Docker and creates `backend/.env`, `infra/.env` and `frontend/.env` from their examples. Only `OPENROUTER_API_KEY` in `backend/.env` must be typed; the other values work for a local run.
- `COMPOSE_PROJECT_NAME` in `infra/.env` names the stack. The setup scripts stop when a stack with that name runs from another checkout. `DB_SHM_SIZE` (1g) sets the shared memory of the database.
- Start from the repository root: `docker compose -f infra/docker-compose.yml up`. Reset: `docker compose -f infra/docker-compose.yml down -v`. Details: `docs/start-modes.md`.
- On the first start, `corpus-init` puts the labels of `backend/corpus/manifest.json` into the label queue and asks the ingest worker for a pass. The worker downloads them from DailyMed and ingests them; the Corpus page shows the queue. The manifest has 50 labels: in a clean clone test the worker ingested them in 393 s (3748 chunks). A forced re-ingest of the 53-label dev library: 3956 chunks, about 1.23 M tokens, about 0.025 USD of embeddings, about 80 s.
- URLs (ports in `infra/.env`): app `http://localhost:3000`, API docs `http://localhost:8000/api/v1/docs`, Grafana `http://127.0.0.1:3001`, Prometheus `http://127.0.0.1:9090`.
- Langfuse tracing is optional: set the three `LANGFUSE_*` values in `backend/.env`.
- Every tunable number is a required variable in the Tuning section of `backend/.env.example` (76 values: database pool, timeouts, cache lifetimes, model limits, chat and search limits, detector thresholds, worker intervals, DailyMed pacing). Preflight and the setup scripts read the names from that section and stop on an empty value. Only fixed rules stay in code: the API request limits, the 17 top-level label sections of the regulation, HTTP status codes, retry doubling, the advisory lock key.

## What is in the box

- Services (`infra/docker-compose.yml`): preflight, db (ParadeDB: Postgres 18 with `pg_search` BM25 and `pgvector`), storage (SeaweedFS, S3 API), cache (Redis 7.2), backend (FastAPI, LangGraph), ingest-worker (`python -m app.worker`), corpus-init (`python -m app.worker.corpus_init`, one-shot), prometheus, grafana, frontend (Next.js, `@geomak/ui`).
- Only the API applies the database migrations (`app/bootstrap.py`). The worker and corpus-init check the schema and exit 1 when it is not current; the worker restarts (`restart: on-failure`).
- The worker does not import LangGraph, FastAPI or the chat code (`backend/tests/test_worker_imports.py`). Only `app/application/chat/graph.py` imports LangGraph (`backend/tests/application/chat/test_graph_boundary.py`).
- Pages: chat, documents (with the PDF viewer and citation highlight), corpus (DailyMed search and label queue), settings (chunking, search, models, answer checking), status, health.
- Diagrams: `docs/diagrams/`. Screenshots (1440x900): `docs/screenshots/` (chat answer, cited passage in the PDF viewer, clarify question, documents, corpus, settings, status, health).

## How an answer is made

- Graph (`backend/app/application/chat/graph.py`): guard (plain-code prompt-injection check), intake (the chat model replies, or writes the search query and names the medicines), retrieve, clarify, grade (LLM grader, one retry), generate, validate, suggest.
- Drug detection: exact names, then fuzzy names (rapidfuzz, thresholds calibrated on the library). A product is its ingredients plus its dosage form; several labels of one product use one preferred label (brand first, then newest). One name with several forms asks which form ("Ozempic": tablet or injection). A named medicine outside the library is refused with the library list (small libraries only).
- Search: hybrid. pgvector HNSW (cosine) and ParadeDB BM25 (content and section titles), both filtered by label inside the index, fused with RRF, plus section hints from the question topic; at most 8 excerpts and 3500 tokens. A failed or slow search leg (5 s) leaves the other leg.
- Chunks: sections from the SPL XML, pages from the PDF, about 500 tokens with 50 overlap, one section per chunk; a chunk inside a table keeps the table caption and header row as context.
- Answer check: each sentence with a figure needs a citation; a dose needs the same number and unit in an excerpt that its sentence cites; the user sees only the checked answer.
- Shared cache (Redis): question embeddings, model replies of the intake and rewrite roles, PDF thumbnails, model lists.

## Measured (evals and tests)

- Generated retrieval set, no LLM calls (`python -m evals.retrieval_set`, in the backend container): 578 questions from the 53 labels, recall@8 0.969, MRR 0.93. 16 misses are Ozempic clarify questions (by design), 2 are real misses (interaction comparisons).
- Golden set, 28 reviewed cases with reference answers (`python -m evals.run --label <name>`; `backend/evals/golden_set.jsonl`): run 6 (`backend/evals/results/2026-11-24T115620Z-golden-run-6.json`) passed 24 of 28; LLM judge correct 1.0; citation validity 1.0; numeric grounding 1.0; p50 5.9 s; 0.38 USD for the run. All 4 failures are refusals from the strict number check: the 3 age cases and `januvia-side-effects`, which passes in some runs.
- Ablation on the older 20-question set (`backend/evals/results/2026-11-23-ablation.md`): all configurations 18 to 20 of 20; the set is too easy to rank them; grader off or rule only cost about 1.8 times more (all excerpts go to the answer model).
- Drug detector calibration (`python -m evals.detector_calibration`): 0 wrong drugs, 0 missed one-edit typos, 16 clarify questions on 654 cases.
- Load (2026-11-22, local load test setup, not in git): 4 API processes, 2000 synthetic labels (149,920 chunks), fake model server: 21.5 turns per second at 200 users, p95 9.7 s.
- Detector at 10,000 names: 6.3 ms median per question.
- Tests: backend 580 passed, 4 xfailed (known limits of the plain-word injection guard); frontend 131.
- Citation highlight: the viewer finds the cited passage on its page for 80.1% of all 3956 chunks (3151 by the passage start, 18 by the anchor; 88 of the 787 misses are on another page of the chunk); full run, 74 s (`python -m evals.export_anchors` in the backend container, then `npm run eval:anchors` in `frontend/`).

## Known limits and behaviours

- Strict number check: an answer is refused when a sentence has a figure without a citation, including ages ("10 years"). Some pediatric questions are refused for that (3 to 4 of 20 answer questions per golden run). Author decision: keep it strict.
- A dose in a bold line counts as a heading and is not checked; the dose frequency is not checked ("twice daily" against "once daily").
- "(%)" table cells: a figure with "%" is accepted when the cited table labels its unit "(%)".
- The prompt-injection guard is plain words; reworded attacks can pass it (4 known xfail cases); the answer check and the grader stay as later layers.
- Conversations live until a browser reload (the page deletes the conversation); there are no user accounts. With authentication and users, conversations can be kept per user.
- The pdf.js worker loads from the jsdelivr CDN, so the PDF viewer needs internet access.
- Detector thresholds are calibrated on 53 labels; a library of thousands has more look-alike names and needs a new calibration.
- Follow-ups depend on the intake model to name the drug; measured: 24 of 25 follow-up turns kept the right drug. The history window is 10 messages.

## Out of scope

Authentication and multi-tenancy, a reranker model, a LangGraph checkpointer and durable threads, OCR for scanned PDFs, presigned URLs or a CDN for the PDFs, self-hosted Langfuse, deployment to a cloud environment, PDF highlight for matches that cross columns or tables. Also not done: PDF upload (the library is DailyMed labels only), published container images.

## Licenses of the parts with a copyleft or special license

| Part | License | Where | Verified |
|---|---|---|---|
| PyMuPDF 2.1 | AGPL-3.0 or a commercial license | backend dependency | package metadata |
| ParadeDB `pg_search` | AGPL-3.0-or-later | db image | `/usr/share/doc/postgresql-18-pg-search/copyright` |
| Grafana 13.3.0 | AGPL-3.0 | grafana image | `/usr/share/grafana/LICENSE` |
| psycopg 3.3.9, psycopg-pool 3.3.3 | LGPL-3.0 | backend dependencies | package metadata |
| Redis 7.2.17 | BSD-3-Clause (7.4 and later: RSALv2 or SSPLv1; 8: also AGPLv3) | cache image | `COPYING` at the git tags |
| pgvector | PostgreSQL License | db image | `/usr/share/doc/postgresql-18-pgvector/copyright` |

The other backend dependencies (FastAPI, LangGraph, LangChain, redis-py, rapidfuzz, tiktoken, langfuse, pydantic-settings, httpx, uvicorn, boto3, prometheus-client) and the frontend dependencies checked (`@geomak/ui`, Next.js, pdfjs-dist) are MIT, BSD or Apache-2.0 by their package metadata. SeaweedFS and Prometheus: not verified here.

## Open decisions (author)

- A reranker (the data does not ask for one now: 2 real retrieval misses in 578 generated questions).
- A LangGraph checkpointer (out of scope).
- Langfuse access for the reviewer.
