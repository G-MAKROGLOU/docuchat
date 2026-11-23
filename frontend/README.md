# docuchat-frontend

Next.js chat interface for document question answering. A proxy route forwards `/api/*` to the backend at `BACKEND_URL`.

The full system (backend, frontend, database, storage) runs from the repository root: see `infra/docker-compose.yml` and `docs/start-modes.md`.

## Local commands

```sh
cp .env.example .env      # infra/setup.sh also creates it; BACKEND_URL points to a running backend
npm ci
npm run dev               # http://localhost:3000
```

```sh
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
npm run contract:generate                     # types from CONTRACT_SOURCE or contract/
npm run contract:generate -- <url-or-file>    # types from a given schema, updates contract/
npm run contract:check                        # fail if generated files differ from the committed ones
```
