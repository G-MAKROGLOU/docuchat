# Start modes

Run `infra/setup.sh` (Windows: `infra\setup.ps1`) once before the first start. It creates the three `.env` files from their examples. Only `backend/.env` needs a value from you: `OPENROUTER_API_KEY`.

## Configuration

Each project has its own `.env`. Each variable is in one file only.

| File | Holds |
|---|---|
| `backend/.env` | OpenRouter key and URL, models, embedding, storage bucket and region, Langfuse, `WEB_CONCURRENCY` |
| `infra/.env` | Postgres credentials, object store keys, Grafana admin password, host ports. Compose reads it for the `${...}` values in `infra/docker-compose.yml` and passes the database URL and the object store keys to the backend. |
| `frontend/.env` | Links on the Health page, hot reload polling, and `BACKEND_URL` and `CONTRACT_SOURCE` for a run outside Docker |

## Start

The repository has one Compose file, `infra/docker-compose.yml`. It builds the dev targets of `backend/` and `frontend/`. Run it from the repository root:

```sh
docker compose -f infra/docker-compose.yml up
```

Services: preflight, db, storage, cache, backend, ingest-worker, corpus-init (runs once), prometheus, grafana, frontend. Hot reload for `backend/` and `frontend/`.

## URLs

The ports are in `infra/.env`.

- App: `http://localhost:${FRONTEND_PORT}`
- API docs: `http://localhost:${BACKEND_PORT}/api/v1/docs`
- Grafana: `http://localhost:${GRAFANA_PORT}`
- Prometheus: `http://127.0.0.1:${PROMETHEUS_PORT}`

## Reset

This removes the stack and its volumes. It works also when the `.env` files do not exist.

```sh
docker compose -f infra/docker-compose.yml down -v
```
