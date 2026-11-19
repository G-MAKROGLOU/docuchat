# Project rules

This umbrella repository is for the reviewer. It holds the backend and the frontend as git submodules in `backend/` and `frontend/`. The backend and the frontend are independent deployable units with their own CI and images.

## Architecture (backend)
- `backend/app/domain` imports nothing from `application`, `infrastructure` or `api`. It has no framework imports.
- `backend/app/application` depends on domain interfaces (ports) only.
- Only `backend/app/infrastructure` imports provider SDKs.
- All model and embedding access goes through the factory in `infrastructure`. No provider class in graph nodes or services.
- Each graph node is a pure function of state plus injected ports. Each node has a unit test.

## Architecture (frontend)
- The browser calls only the frontend. The proxy route `frontend/src/app/api/[...path]/route.ts` forwards `/api/*` to `BACKEND_URL`.

## API contract
- All API routes are under `/api/v1`.
- Contract changes are additive only. A removed or renamed field requires a new version (`/api/v2`).
- The backend is the source of truth. After a schema change, run `python -m app.api.contract` in the backend and commit `backend/contract/`.
- Then run `npm run contract:generate -- <backend schema URL or file>` in the frontend and commit `contract/` and `src/lib/contract/`.
- Do not edit `frontend/src/lib/contract/stream-events.ts`. It is generated.

## Submodules
- After each push in the backend or frontend repository, make a commit in this umbrella that moves the submodule pointer.
- State the pointer status in each task report: the umbrella commit and the backend and frontend commits it points to, and whether each is pushed.

## Configuration
- No secrets in code. Configuration comes from the environment only.

## Tests
- Write the test first for chunking, retrieval and graph nodes.

## Dependencies
- Do not add a dependency without approval.

## Documentation
- Do not write README prose. The author writes it.

## After each task
Run lint, types and tests in the repository you changed, then report the results:
- Backend: `docker compose exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app && python -m app.api.contract --check"`
- Frontend: `npm run lint && npm run format:check && npm run typecheck && npm test && npm run contract:check`
- Umbrella: `sh scripts/check-contract.sh`

See `.claude/rules/` for more rules.
