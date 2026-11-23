# System context

The browser calls only the frontend. The frontend proxy forwards `/api/*` to the backend. The backend uses ParadeDB, SeaweedFS and OpenRouter. The corpus command downloads labels from DailyMed.

```mermaid
flowchart LR
    user(["Browser"])

    subgraph compose["Docker Compose stack"]
        frontend["frontend<br/>Next.js, port 3000<br/>proxy: src/app/api/[...path]/route.ts"]
        backend["backend<br/>FastAPI, port 8000<br/>routes under /api/v1"]
        cli["backend commands, run in the backend container<br/>python -m app.corpus_download<br/>python -m app.ingest<br/>python -m app.search_cli"]
        db[("db<br/>ParadeDB 0.26.8, Postgres 18<br/>pgvector + pg_search")]
        storage[("storage<br/>SeaweedFS 4.52 mini<br/>S3 API, port 8333")]
    end

    dailymed["DailyMed<br/>label PDF + SPL XML"]
    openrouter["OpenRouter<br/>embeddings API"]

    user -->|"HTTP /, /documents/{id}, /api/*"| frontend
    frontend -->|"fetch BACKEND_URL/api/*<br/>stream, no buffering"| backend
    backend -->|"psycopg pool, migrations at startup"| db
    backend -->|"boto3, path-style S3"| storage
    cli -->|"documents, chunks"| db
    cli -->|"PDF + label.xml objects"| storage
    cli -->|"HTTPS GET"| dailymed
    cli -->|"embed_documents, embed_query"| openrouter
```

Compose: one file, `docker-compose.yml`.

```mermaid
flowchart TB
    subgraph dev["docker-compose.yml (development)"]
        d_pre["preflight<br/>busybox, preflight/check.sh<br/>stops on empty OPENROUTER_API_KEY"]
        d_svc["db, storage, backend, frontend<br/>build target: dev<br/>bind mounts: backend/, frontend/, corpus/ (read-only)<br/>db and storage ports on 127.0.0.1"]
        d_pre -->|"service_completed_successfully"| d_svc
    end
```

Start order: `db` and `storage` healthy, then `backend` healthy (`GET /api/v1/health`), then `frontend`.
