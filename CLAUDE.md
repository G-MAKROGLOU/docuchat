# Project rules

## Architecture
- `app/domain` imports nothing from `application`, `infrastructure` or `api`. It has no framework imports.
- `app/application` depends on domain interfaces (ports) only.
- Only `app/infrastructure` imports provider SDKs.
- All model and embedding access goes through the factory in `infrastructure`. No provider class in graph nodes or services.
- Each graph node is a pure function of state plus injected ports. Each node has a unit test.

## Configuration
- No secrets in code. Configuration comes from the environment only, through `app/config.py`.

## Tests
- Write the test first for chunking, retrieval and graph nodes.

## Dependencies
- Do not add a dependency without approval.

## Documentation
- Do not write README prose. The author writes it.

## Local stack
- `docker-compose.yml` starts db, backend and frontend. The frontend builds from the docuchat-frontend clone at `FRONTEND_PATH`.

## After each task
Run lint, types and tests, then report the results:
`docker compose exec backend sh -c "ruff check . && ruff format --check . && mypy && pytest && bandit -c pyproject.toml -r app"`

See `.claude/rules/` for more rules.
