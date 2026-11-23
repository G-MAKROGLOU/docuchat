# CI/CD

Two GitHub Actions workflows in `.github/workflows/`. Both are path-filtered and run on a push to `main` and on a pull request.

```mermaid
flowchart TB
    push(["push to main"])
    pr(["pull_request"])

    subgraph be["backend.yml (paths: backend/**, the workflow file)"]
        be_check["check<br/>services: SeaweedFS 4.52, ParadeDB 0.26.8-pg18, Redis 7.2.17<br/>uv sync --locked<br/>ruff check, ruff format --check, mypy,<br/>pytest -rs, bandit, app.api.contract --check"]
    end

    subgraph fe["frontend.yml (paths: frontend/**, backend/contract/**, the workflow file)"]
        fe_check["check<br/>Node 24.22.3, npm ci<br/>lint, format:check, typecheck, test,<br/>contract:check, build"]
    end

    push --> be_check
    pr --> be_check
    push --> fe_check
    pr --> fe_check
```

All jobs run on `ubuntu-24.04` with `permissions: contents: read`.
