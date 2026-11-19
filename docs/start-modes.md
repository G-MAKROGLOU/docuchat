# Start modes

Run `./setup.sh` (Windows: `.\setup.ps1`) once before the first start in either mode.

## 1. Build from backend/ and frontend/ (development)

```sh
docker compose up
```

Services: preflight, db, backend, frontend. Hot reload for `backend/` and `frontend/`.

## 2. Published images (no local build)

```sh
docker login ghcr.io          # token with read:packages; the images are private
docker compose -f compose.images.yml up -d
```

Image tags come from `BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` in `.env` (a commit hash or `latest`). This mode builds nothing.

## URLs

- App: `http://localhost:${FRONTEND_PORT}`
- API docs: `http://localhost:${BACKEND_PORT}/api/v1/docs`

## Reset without a prepared .env

Compose stops every command while `OPENROUTER_API_KEY` is empty. To remove the stack and its volume anyway:

```sh
OPENROUTER_API_KEY=unused docker compose down -v
```

```powershell
$env:OPENROUTER_API_KEY = 'unused'; docker compose down -v
```
