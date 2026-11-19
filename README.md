# docuchat-backend

FastAPI service for document question answering. API routes are under `/api/v1`.

The full system (backend, frontend, database) runs from the umbrella repository: [docuchat](https://github.com/G-MAKROGLOU/docuchat).

## Local commands

```sh
cp .env.example .env                       # then fill in the required values
docker compose -f compose.dev.yml up       # backend and db, hot reload
```

- Health: http://localhost:8000/api/v1/health
- API docs: http://localhost:8000/api/v1/docs

```sh
docker compose -f compose.dev.yml exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app"
docker compose -f compose.dev.yml exec backend python -m app.api.contract          # write contract/
docker compose -f compose.dev.yml exec backend python -m app.api.contract --check  # fail if contract/ is out of date
```
