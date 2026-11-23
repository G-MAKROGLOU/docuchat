# docuchat-backend

FastAPI service for document question answering. API routes are under `/api/v1`.

The full system (backend, frontend, database, storage) runs from the repository root: see `infra/docker-compose.yml` and `docs/start-modes.md`.

## Local commands

Run these from the repository root, after `infra/setup.sh` (Windows: `infra\setup.ps1`).

```sh
docker compose -f infra/docker-compose.yml up   # full stack, hot reload for backend/
```

- Health: http://localhost:${BACKEND_PORT}/api/v1/health
- API docs: http://localhost:${BACKEND_PORT}/api/v1/docs

```sh
docker compose -f infra/docker-compose.yml exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app"
docker compose -f infra/docker-compose.yml exec backend python -m app.api.contract          # write contract/
docker compose -f infra/docker-compose.yml exec backend python -m app.api.contract --check  # fail if contract/ is out of date
```
