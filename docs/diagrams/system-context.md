# System context

The browser calls only the frontend for pages and `/api/*`. The frontend proxy forwards `/api/*` to the backend. The PDF viewer loads the pdf.js worker from the jsdelivr CDN. The backend and the ingest worker use ParadeDB, SeaweedFS, the shared Redis cache, OpenRouter and DailyMed. Prometheus reads the metrics of the backend and the ingest worker.

```mermaid
flowchart LR
    user(["Browser<br/>pages: chat /, /documents, /corpus,<br/>/settings, /status, /health"])

    subgraph compose["Docker Compose stack (infra/docker-compose.yml)"]
        frontend["frontend<br/>Next.js, port 3000<br/>proxy: src/app/api/[...path]/route.ts"]
        backend["backend<br/>FastAPI, port 8000<br/>routes under /api/v1, /metrics"]
        worker["ingest-worker<br/>python -m app.ingest_worker<br/>one replica, metrics port 9100"]
        init["corpus-init<br/>python -m app.corpus_init<br/>one-shot job"]
        db[("db<br/>ParadeDB 0.26.8, Postgres 18<br/>pgvector + pg_search")]
        storage[("storage<br/>SeaweedFS 4.52 mini<br/>S3 API, port 8333")]
        cache[("cache<br/>Redis 7.2.17<br/>256 MB, allkeys-lru, no disk copy")]
        prom["prometheus v3.16.0"]
        grafana["grafana 13.3.0<br/>DocuChat dashboard"]
    end

    cdn["jsdelivr CDN<br/>pdf.worker.min.mjs"]
    dailymed["DailyMed<br/>label PDF, SPL XML, SPL list"]
    openrouter["OpenRouter<br/>chat models, embeddings, model lists"]
    langfuse["Langfuse<br/>turn traces (optional)"]

    user -->|"HTTP pages and /api/*"| frontend
    user -->|"GET worker script"| cdn
    user -.->|"links on the Health page"| grafana
    frontend -->|"fetch BACKEND_URL/api/*<br/>stream, no buffering"| backend
    backend -->|"psycopg pool, migrations at startup"| db
    backend -->|"boto3, path-style S3"| storage
    backend -->|"question vectors, model replies,<br/>thumbnails, model lists"| cache
    backend -->|"chat roles, embed_query"| openrouter
    backend -->|"SPL list for the Corpus page"| dailymed
    backend -.->|"traces"| langfuse
    worker -->|"ingestion state, documents, chunks"| db
    worker -->|"PDF + label.xml objects"| storage
    worker -->|"update check, label queue"| dailymed
    worker -->|"embed_documents"| openrouter
    init -->|"documents, chunks"| db
    init -->|"PDF + label.xml objects"| storage
    init -->|"manifest download"| dailymed
    init -->|"embed_documents"| openrouter
    prom -->|"scrape backend:8000/metrics"| backend
    prom -->|"scrape ingest-worker:9100"| worker
    grafana -->|"PromQL"| prom
```

The ingest worker and corpus-init get `CACHE_URL` too, but they embed document chunks only, and document vectors do not go through the cache.

Compose: one file, `infra/docker-compose.yml`, development mode only. Start it from the repository root with `docker compose -f infra/docker-compose.yml up`.

```mermaid
flowchart TB
    pre["preflight<br/>busybox, infra/preflight/check.sh<br/>stops on an empty required value"]
    db["db"]
    storage["storage"]
    cache["cache"]
    backend["backend"]
    worker["ingest-worker"]
    init["corpus-init"]
    prom["prometheus"]
    grafana["grafana"]
    frontend["frontend"]

    pre -->|"completed"| db
    pre -->|"completed"| storage
    pre -->|"completed"| cache
    pre -->|"completed"| backend
    pre -->|"completed"| frontend
    db -->|"healthy: pg_isready"| backend
    storage -->|"healthy: /healthz"| backend
    cache -->|"healthy: redis-cli ping"| backend
    backend -->|"healthy: GET /api/v1/health"| worker
    backend -->|"healthy"| init
    backend -->|"healthy"| prom
    backend -->|"healthy"| frontend
    prom -->|"started"| grafana
```

Configuration: one `.env` per project.

| File | Read by | Holds |
|---|---|---|
| `backend/.env` | preflight, backend, ingest-worker, corpus-init | OpenRouter key and models, embedding, `STORAGE_BACKEND`, `S3_BUCKET`, `S3_REGION`, Langfuse, `WEB_CONCURRENCY` |
| `infra/.env` | Compose interpolation | Postgres credentials, S3 keys, Grafana admin password, host ports |
| `frontend/.env` | frontend (optional) | Health page links, polling, `BACKEND_URL` and `CONTRACT_SOURCE` for a run outside Docker |

Compose sets `DATABASE_URL`, `CACHE_URL=redis://cache:6379/0` and the S3 endpoint and keys for the backend services. `infra/setup.sh` and `infra/setup.ps1` create the three files from their examples.

Ports: `backend` and `frontend` publish on all host interfaces. `db`, `storage`, `prometheus` and `grafana` publish on `127.0.0.1` only. `cache` publishes no port. The bind mounts are `backend/` and `frontend/` for hot reload, and `backend/corpus/` at `/corpus` (read-only) for the backend and corpus-init.
