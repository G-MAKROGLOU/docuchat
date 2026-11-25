# DocuChat

## Overview

DocuChat answers questions about prescription drug labels. It uses only the label text in its library. Each answer cites the label passages that it uses.

The library holds drug labels from DailyMed (the US National Library of Medicine). The first start loads 50 labels. You can add more labels from the Corpus page. The measurements below use a library of 53 labels.

What DocuChat does:

- It finds the drugs that the question names, and it searches only the labels of these drugs.
- It writes an answer with a citation for each fact. When you click a citation, the PDF viewer opens the label at the cited passage.
- It checks the answer before you see it. A sentence with a number must cite a passage that holds that number.
- It refuses when the labels do not answer the question, or when the question names a drug that is not in the library.
- It asks a question back when a name is not clear. Example: "Ozempic" has a tablet label and an injection label.

DocuChat does not give medical advice. It reports what the label says.

![A cited answer](docs/screenshots/chat-answer.png)

## Architecture

The repository has three deployable parts and one docs folder:

| Folder | Holds |
|---|---|
| `backend/` | FastAPI API, the LangGraph chat graph, the ingest worker, evals |
| `frontend/` | Next.js app with the `@geomak/ui` component library |
| `infra/` | The Compose stack, the setup scripts, preflight, Prometheus and Grafana |
| `docs/` | Diagrams, screenshots, start modes |

Services in `infra/docker-compose.yml`:

| Service | Job |
|---|---|
| `preflight` | Checks the `.env` files before the other services start |
| `db` | ParadeDB (Postgres 18 with `pg_search` for BM25 and `pgvector` for vectors) |
| `storage` | SeaweedFS with the S3 API. It holds the label PDFs and XML files. |
| `cache` | Redis 7.2. It holds question embeddings, model replies, thumbnails and model lists. |
| `backend` | The API. It applies the database migrations at start. |
| `ingest-worker` | Downloads, parses, chunks and embeds the labels |
| `corpus-init` | Runs once. It puts the labels of `backend/corpus/manifest.json` into the label queue. |
| `prometheus`, `grafana` | Metrics and one dashboard |
| `frontend` | The web app. Its proxy route forwards `/api/*` to the backend. |

The browser calls only the frontend. The one exception is the pdf.js worker, which loads from the jsdelivr CDN.

### How an answer is made

The chat graph is in `backend/app/application/chat/graph.py`. Each turn goes through these steps:

1. **guard**: plain code checks the question for size and for known prompt-injection words.
2. **intake**: a model replies to small talk, or writes a search query and names the medicines in the question.
3. **retrieve**: plain code finds the drugs and searches their labels.
4. **clarify**: when a name matches more than one drug or form, the user gets a question back.
5. **grade**: a model keeps the relevant passages. If none is relevant, the graph writes a new query and searches one more time.
6. **generate**: a model writes the answer from the passages, with citations.
7. **validate**: plain code checks the citations and the numbers.
8. **suggest**: a model proposes follow-up questions.

Search is hybrid. A vector search (pgvector, HNSW) and a keyword search (ParadeDB BM25) run on the same labels. Reciprocal rank fusion joins the two result lists. An answer gets at most 8 passages and 3500 tokens. When one search fails or takes more than 5 seconds, the other search continues alone.

Labels are split by their sections from the SPL XML file. The page numbers come from the PDF. Each chunk has about 500 tokens. A chunk inside a table keeps the table caption and the header row.

Diagrams of the system, the backend layers, ingestion, retrieval and the database are in `docs/diagrams/`.

### Backend layers

- `app/domain` has the models and the ports. It imports no framework.
- `app/application` has the services and the chat graph. It uses the ports only. Only `chat/graph.py` imports LangGraph.
- `app/infrastructure` has the adapters: Postgres, S3, Redis, OpenRouter, DailyMed, Langfuse, PDF parsing.
- `app/api` has the FastAPI routes. All routes are under `/api/v1`.
- `app/worker` has the ingest worker and corpus-init. It does not load LangGraph or FastAPI.

## Getting started

You need:

- Docker with Compose v2.
- An OpenRouter API key.

Step 1. Create the `.env` files. Run this from the repository root:

```sh
infra/setup.sh
```

On Windows, run `infra\setup.ps1`. The script creates `backend/.env`, `infra/.env` and `frontend/.env` from their examples. Then it stops and asks for the API key.

Step 2. Type your key into `OPENROUTER_API_KEY` in `backend/.env`. The other values work for a local run. Run the setup script again. It must show OK for each check.

Step 3. Start the stack:

```sh
docker compose -f infra/docker-compose.yml up
```

On the first start, the worker downloads and ingests the 50 labels of the manifest. In a clean clone test this took 393 s and made 3748 chunks. The Corpus page shows the progress. The embeddings for 53 labels cost about 0.025 USD.

Step 4. Open the app:

| What | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/api/v1/docs |
| Grafana | http://127.0.0.1:3001 |
| Prometheus | http://127.0.0.1:9090 |

The ports are in `infra/.env`.

To remove the stack and all its data:

```sh
docker compose -f infra/docker-compose.yml down -v
```

## Configuration

Each part has its own `.env` file. Each variable is in one file only. The examples are `backend/.env.example`, `infra/.env.example` and `frontend/.env.example`.

| File | Holds |
|---|---|
| `backend/.env` | The OpenRouter key, the models, the embedding model, the storage bucket, Langfuse, `WEB_CONCURRENCY`, and the Tuning section |
| `infra/.env` | The Compose project name, the Postgres and S3 credentials, the Grafana password, the host ports, `DB_SHM_SIZE` |
| `frontend/.env` | The links on the Health page, and the backend URL for a run outside Docker |

Models (OpenRouter model IDs):

| Step | Model |
|---|---|
| intake, rewrite, grade | `anthropic/claude-haiku-5.5` |
| generate | `anthropic/claude-opus-5.5` |
| embeddings | `openai/text-embedding-3-small`, 1536 dimensions |

The Settings page can change the models, the chunk size, the search limits and the answer check while the app runs.

Every tunable number is a required variable in the Tuning section of `backend/.env.example`. There are 76 of them: the database pool, timeouts, cache lifetimes, model limits, search limits, detector thresholds, worker intervals and DailyMed pacing. The code has no default for them. Preflight and the setup scripts stop when one is empty.

`COMPOSE_PROJECT_NAME` must be different for each checkout on one machine. The setup scripts stop when another checkout uses the same name.

Langfuse tracing is optional. To turn it on, set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` in `backend/.env`. Each chat turn then sends one trace, with the user question and the answer. Each conversation is one Langfuse session.

## Development

The stack runs in development mode only. The backend and the frontend reload when you change a file.

Backend checks, from the repository root:

```sh
docker compose -f infra/docker-compose.yml exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app && python -m app.api.contract --check"
```

Frontend checks, in `frontend/`:

```sh
npm run lint && npm run format:check && npm run typecheck && npm test && npm run contract:check
```

### API contract

The backend is the source of the contract.

- `python -m app.api.contract` (in the backend container) writes `backend/contract/`.
- `npm run contract:generate` (in `frontend/`) writes `frontend/src/lib/contract/generated.ts`. Do not edit this file.
- CI fails when either file is out of date.
- Contract changes are additive only. A removed or renamed field needs a new API version.

### Database migrations

Only the API applies the migrations, at start. The ingest worker and corpus-init check that the schema is current. If it is not current, they stop with a message, and the worker restarts until the API has applied the migrations.

### CI

GitHub Actions has two workflows. `backend.yml` runs on changes in `backend/`. `frontend.yml` runs on changes in `frontend/` and `backend/contract/`. Each workflow runs the checks above. CI does not build or publish images.

## Testing

Results on 2026-11-24:

- Backend: 580 passed, 4 xfailed. The 4 xfailed tests are reworded prompt-injection attacks that the plain-word guard does not stop.
- Frontend: 131 passed (2026-11-23).

## Evaluation

The evals are in `backend/evals/`. Run them in the backend container. Results go to `backend/evals/results/`.

| Eval | Command | Result |
|---|---|---|
| Retrieval set, 578 generated questions, no LLM calls | `python -m evals.retrieval_set` | recall@8 0.969, MRR 0.93 |
| Golden set, 28 reviewed cases with reference answers | `python -m evals.run --label <name>` | 24 of 28 passed (run 6) |
| Drug detector calibration, 654 cases | `python -m evals.detector_calibration` | 0 wrong drugs, 0 missed one-edit typos, 16 clarify questions |
| Citation highlight on all 3956 chunks | `python -m evals.export_anchors`, then `npm run eval:anchors` in `frontend/` | the viewer finds 80.1% of the passages |

Golden run 6 in detail: an LLM judge scored all answered cases as correct. Citation validity is 1.0 and number grounding is 1.0. The median time is 5.9 s, and the cost is 0.38 USD for the 28 cases. The 4 failures are refusals from the strict number check: three questions about ages, and one Januvia question that passes in some runs.

The retrieval set misses 18 of 578 questions. 16 of these are Ozempic questions that get a clarify question by design. 2 are real misses on drug interaction comparisons.

Load test (2026-11-22): 4 API processes, 2000 synthetic labels (149,920 chunks) and a fake model server gave 21.5 chat turns per second at 200 users, with a p95 of 9.7 s. The load test setup is local only and is not in git.

## Corpus

`backend/corpus/manifest.json` lists 50 labels. All labels use the PLR layout (the label format of 21 CFR 201.57). The set includes boxed warnings, drug class pairs and look-alike names (for example Celebrex and Celexa), so the tests cover hard cases. Details are in `backend/corpus/README.md`.

A product is its active ingredients plus its dosage form. When the library has more than one label for a product, the search uses one preferred label: the brand label first, then the newest label.

## Deployment

The project runs on one machine with Docker Compose, in development mode. There is no production image and no cloud deployment.

## Known limits

- **Strict number check.** The app refuses an answer when a sentence has a number without a citation. This includes ages, for example "10 years". Some questions about children are refused for this reason. The author decided to keep this check strict.
- **Doses in bold lines and dose frequency.** A dose in a bold line counts as a heading and is not checked. The check does not compare the frequency, for example "twice daily" against "once daily".
- **Prompt-injection guard.** The guard looks for known words only. A reworded attack can pass it. The grade step and the answer check still apply after it.
- **Conversations.** A conversation is deleted when the browser reloads the page. There are no user accounts. With authentication, conversations can be kept per user.
- **PDF viewer.** It loads the pdf.js worker from the jsdelivr CDN, so it needs internet access. It finds the cited passage for 80.1% of the chunks. It does not highlight a passage that crosses columns or tables.
- **Large libraries.** The detector thresholds are calibrated on 53 labels. A library of thousands of labels has more look-alike names and needs a new calibration.
- **Long conversations.** The chat history window is 10 messages. A drug that is named only in the first message of a long conversation can drop out (not seen in tests).

## Out of scope

- Authentication and multi-tenancy
- A reranker model
- A LangGraph checkpointer and durable threads
- OCR for scanned PDFs
- Presigned URLs or a CDN for the PDFs
- Self-hosted Langfuse
- Cloud deployment and published container images
- PDF upload. The library takes DailyMed labels only.

## Licenses

These parts have a copyleft or special license:

| Part | License | Where |
|---|---|---|
| PyMuPDF | AGPL-3.0 or a commercial license | backend dependency |
| ParadeDB `pg_search` | AGPL-3.0-or-later | db image |
| Grafana 13.3.0 | AGPL-3.0 | grafana image |
| psycopg, psycopg-pool | LGPL-3.0 | backend dependencies |
| Redis 7.2.17 | BSD-3-Clause. Redis 7.4 and later use other licenses. | cache image |

The other backend and frontend dependencies that were checked are MIT, BSD or Apache-2.0. The licenses of SeaweedFS and Prometheus were not checked.
