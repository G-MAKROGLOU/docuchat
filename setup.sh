#!/usr/bin/env bash
# Prepares a clone for `docker compose up`. Safe to run again. Same behavior as setup.ps1.
set -u
cd "$(dirname "$0")" || exit 1

fail() {
  echo ""
  echo "SETUP STOPPED: $1"
  echo "Action: $2"
  exit 1
}

env_value() {
  # Reads KEY from .env without executing the file.
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

# 1. Docker and Docker Compose
command -v docker >/dev/null 2>&1 ||
  fail "Docker is not installed." "Install Docker Desktop (Windows, macOS) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 ||
  fail "Docker Compose v2 is not available." "Install or update Docker so that 'docker compose version' works."
docker info >/dev/null 2>&1 ||
  fail "Docker is installed but not running." "Start Docker Desktop or the Docker service, then run ./setup.sh again."
echo "OK  Docker and Docker Compose are running."

# 2. Submodules
if [ ! -f backend/pyproject.toml ] || [ ! -f frontend/package.json ]; then
  echo "..  Submodule folders are empty. Running: git submodule update --init --recursive"
  if ! git submodule update --init --recursive; then
    fail "git could not fetch the backend and frontend repositories. Probable cause: your GitHub account has no read access to the private repositories docuchat-backend and docuchat-frontend, or git has no credentials for github.com." \
      "Ask the owner for read access, sign in to GitHub in git, then run: git submodule update --init --recursive"
  fi
fi
echo "OK  backend/ and frontend/ are checked out."

# 3. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "Created .env from .env.example. Fill in these values:"
  echo "  Required: OPENROUTER_API_KEY, LLM_REWRITE_MODEL, LLM_GRADE_MODEL, LLM_GENERATE_MODEL,"
  echo "            EMBEDDING_MODEL, EMBEDDING_DIMENSIONS"
  echo "  Optional: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (tracing is off when empty)"
  fail "Values in .env are not filled in yet." "Edit .env, then run ./setup.sh again."
fi
missing=""
for name in OPENROUTER_API_KEY OPENROUTER_BASE_URL LLM_REWRITE_MODEL LLM_GRADE_MODEL LLM_GENERATE_MODEL \
  EMBEDDING_MODEL EMBEDDING_DIMENSIONS POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  [ -n "$(env_value "$name")" ] || missing="$missing $name"
done
[ -z "$missing" ] || fail "Required values in .env are empty:$missing" "Edit .env, then run ./setup.sh again."
echo "OK  .env has all required values."

# 4. Ports (skipped while this stack runs, because its own containers hold the ports)
if [ -n "$(docker compose ps -q 2>/dev/null)" ]; then
  echo "OK  The stack is already running. Port check skipped."
else
  for pair in FRONTEND_PORT:3000 BACKEND_PORT:8000 DB_PORT:5432; do
    var="${pair%%:*}"
    port="$(env_value "$var")"
    port="${port:-${pair##*:}}"
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      fail "Port $port is in use." "Stop the program that uses port $port, or set $var to a free port in .env."
    fi
  done
  echo "OK  Ports are free."
fi

# 5. Next step
frontend_port="$(env_value FRONTEND_PORT)"
backend_port="$(env_value BACKEND_PORT)"
echo ""
echo "Ready. Run: docker compose up"
echo "  App:      http://localhost:${frontend_port:-3000}"
echo "  API docs: http://localhost:${backend_port:-8000}/api/v1/docs"
