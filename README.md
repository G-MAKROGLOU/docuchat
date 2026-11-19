# docuchat-frontend

Next.js chat interface for document question answering. A proxy route forwards `/api/*` to the backend at `BACKEND_URL`.

The full system (backend, frontend, database) runs from the umbrella repository: [docuchat](https://github.com/G-MAKROGLOU/docuchat).

## Local commands

```sh
cp .env.example .env      # set BACKEND_URL to a running backend
npm ci
npm run dev               # http://localhost:3000
```

```sh
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
npm run contract:generate                     # types from CONTRACT_SOURCE or contract/
npm run contract:generate -- <url-or-file>    # types from a given schema, updates contract/
npm run contract:check                        # fail if generated files differ from the committed ones
```
