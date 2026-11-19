# Project rules

## Architecture

- The browser calls only this app. Route handlers in `src/app/api` call the backend at `BACKEND_URL`.
- `src/lib/stream.ts` mirrors the backend stream contract. See `.claude/rules/stream-contract.md`.

## Configuration

- No secrets in code. Configuration comes from the environment only.

## Dependencies

- Do not add a dependency without approval.

## Documentation

- Do not write README prose. The author writes it.

## Local stack

- The docuchat-backend repo holds `docker-compose.yml`. Run `docker compose up` there.

## After each task

Run lint, types and tests, then report the results:
`npm run lint && npm run typecheck && npm test && npm run format:check`

See `.claude/rules/` for more rules.
