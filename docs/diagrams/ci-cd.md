# CI/CD

Three GitHub Actions workflows in `.github/workflows/`. `backend` and `frontend` are path-filtered. `integration` runs on every push to `main` and every pull request.

```mermaid
flowchart TB
    push(["push to main"])
    pr(["pull_request"])

    subgraph be["backend.yml (paths: backend/**, the workflow file)"]
        be_check["check<br/>services: SeaweedFS 4.52, ParadeDB 0.26.8-pg18<br/>uv sync --locked<br/>ruff check, ruff format --check, mypy,<br/>pytest -rs, bandit, app.api.contract --check"]
    end

    subgraph fe["frontend.yml (paths: frontend/**, backend/contract/**, the workflow file)"]
        fe_check["check<br/>Node 24.22.3, npm ci<br/>lint, format:check, typecheck, test,<br/>contract:check, build"]
    end

    subgraph it["integration.yml (no path filter)"]
        it_smoke["smoke<br/>.env from .env.example with placeholder values<br/>docker compose up -d --build --wait<br/>GET :8000/api/v1/health, status ok<br/>GET :3000/api/v1/health through the proxy<br/>docker compose down -v"]
    end

    push --> be_check
    pr --> be_check
    push --> fe_check
    pr --> fe_check
    push --> it_smoke
    pr --> it_smoke
```

All jobs run on `ubuntu-24.04` with `permissions: contents: read`.
