# Start modes

Run `./setup.sh` (Windows: `.\setup.ps1`) once before the first start in either mode.

## 1. Build from the submodules (development)

```sh
docker compose up
```

Services: preflight, db, backend, frontend. Hot reload for `backend/` and `frontend/`.

## 2. Published images (no local build)

```sh
docker login ghcr.io          # token with read:packages; the images are private
docker compose -f compose.images.yml up -d
```

Image tags come from `BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` in `.env` (a commit hash or `latest`). This mode needs no submodules.

## URLs

- App: `http://localhost:${FRONTEND_PORT}` (default 3000)
- API docs: `http://localhost:${BACKEND_PORT}/api/v1/docs` (default 8000)
