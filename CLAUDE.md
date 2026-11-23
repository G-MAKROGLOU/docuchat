# Project rules

One private monorepo. `backend/` and `frontend/` are independent deployable units with path-filtered pipelines. `infra/` holds the Compose stack, setup scripts, preflight and monitoring. `docs/` supports them. Each of `backend/`, `frontend/` and `infra/` has its own `.env`.

## How to work
- Before you use LangChain, LangGraph, ParadeDB (pg_search, pgvector), SeaweedFS, assistant-ui, Next.js, Langfuse, FastMCP or the OpenRouter API, read the current official documentation. Do not rely on memory. Pin exact versions. LangChain and LangGraph: 1.x APIs only.
- Write the test first for: chunking, fusion, drug detection, routing functions, citation parsing, validation rules.
- Small commits, Conventional Commits, one concern each.
- No new dependency without approval from the author.
- Do not write README.md or DECISIONS.md prose. The author writes them. Record facts (what was built, measured values, problems, choices) in `docs/agent-log.md` with a date.
- No client or company name in code, comments, commits or file names.
- After each task, run lint, type check and tests, then report: what changed, the check output, open points, and items marked VERIFIED or ASSUMED.
- Stop and ask when a done check fails two times, or when the task does not cover a decision.

## Architecture (backend)
- `app/domain` imports nothing from `application`, `infrastructure` or `api`. It has no framework imports.
- `app/application` depends on domain interfaces (ports) only.
- Only `app/infrastructure` imports provider SDKs (OpenRouter, S3, Langfuse, PDF parsing).
- All model and embedding access goes through one factory in `app/infrastructure`. No provider class in graph nodes or services.
- Each graph node is a pure function of state plus injected ports. Each node has a unit test.

## Architecture (frontend)
- The browser calls only the frontend. The proxy route `frontend/src/app/api/[...path]/route.ts` forwards `/api/*` to `BACKEND_URL` and streams SSE without buffering.

## API contract
- All API routes are under `/api/v1`. Contract changes are additive only. A removed or renamed field requires a new version.
- The backend is the source of truth: `python -m app.api.contract` writes `backend/contract/`.
- `npm run contract:generate` in `frontend/` writes `src/lib/contract/generated.ts`. Do not edit that file.
- CI fails on a diff in either place.

## Configuration
- No secrets in code. Configuration comes from the environment only.

## Checks after each task
- Backend (from the repository root): `docker compose -f infra/docker-compose.yml exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app && python -m app.api.contract --check"`
- Frontend (in `frontend/`): `npm run lint && npm run format:check && npm run typecheck && npm test && npm run contract:check`

See `.claude/rules/` for more rules.
