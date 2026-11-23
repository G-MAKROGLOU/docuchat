#!/usr/bin/env bash
# Prepares a clone for the stack. Safe to run again. Same behavior as setup.ps1.
# It creates backend/.env, infra/.env and frontend/.env from their .env.example files.
set -u
cd "$(dirname "$0")/.." || exit 1

COMPOSE="docker compose -f infra/docker-compose.yml"

fail() {
  echo ""
  echo "SETUP STOPPED: $1"
  echo "Action: $2"
  exit 1
}

env_value() {
  # Reads KEY ($2) from the file $1 without executing the file.
  grep -E "^$2=" "$1" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

# check_empty FILE NAME...: stops with the empty names and the file that holds them.
check_empty() {
  file=$1
  shift
  missing=""
  for name in "$@"; do
    [ -n "$(env_value "$file" "$name")" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || fail "Required values in $file are empty:$missing" "Edit $file, then run infra/setup.sh again."
}

# 1. Docker and Docker Compose
command -v docker >/dev/null 2>&1 ||
  fail "Docker is not installed." "Install Docker Desktop (Windows, macOS) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 ||
  fail "Docker Compose v2 is not available." "Install or update Docker so that 'docker compose version' works."
docker info >/dev/null 2>&1 ||
  fail "Docker is installed but not running." "Start Docker Desktop or the Docker service, then run infra/setup.sh again."
echo "OK  Docker and Docker Compose are running."

# 2. The .env files. infra and frontend have working defaults; backend needs the OpenRouter key.
for project in infra frontend backend; do
  if [ ! -f "$project/.env" ]; then
    cp "$project/.env.example" "$project/.env"
    echo "OK  Created $project/.env from $project/.env.example."
  fi
done
if [ -z "$(env_value backend/.env OPENROUTER_API_KEY)" ]; then
  echo ""
  echo "Fill in backend/.env:"
  echo "  Required: OPENROUTER_API_KEY (the models have working defaults)"
  echo "  Optional: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (tracing is off when empty)"
  fail "OPENROUTER_API_KEY in backend/.env is empty." "Edit backend/.env, then run infra/setup.sh again."
fi
check_empty backend/.env OPENROUTER_API_KEY OPENROUTER_BASE_URL LLM_CHAT_MODEL LLM_REWRITE_MODEL \
  LLM_GRADE_MODEL LLM_GENERATE_MODEL EMBEDDING_MODEL EMBEDDING_DIMENSIONS STORAGE_BACKEND S3_BUCKET S3_REGION
# The tuning values: every name in the Tuning section of backend/.env.example.
tuning=$(sed -n '/^# --- Tuning/,/^# --- Optional/p' backend/.env.example | sed -n 's/^\([A-Z0-9_]*\)=.*/\1/p')
# shellcheck disable=SC2086  # one name per word
check_empty backend/.env $tuning
check_empty infra/.env POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB S3_ACCESS_KEY S3_SECRET_KEY \
  FRONTEND_PORT BACKEND_PORT DB_PORT STORAGE_PORT
echo "OK  backend/.env and infra/.env have all required values."

# 3. Ports (skipped while this stack runs, because its own containers hold the ports)
if [ -n "$($COMPOSE ps -q 2>/dev/null)" ]; then
  echo "OK  The stack is already running. Port check skipped."
else
  for var in FRONTEND_PORT BACKEND_PORT DB_PORT STORAGE_PORT; do
    port="$(env_value infra/.env "$var")"
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      fail "Port $port is in use." "Stop the program that uses port $port, or set $var to a free port in infra/.env."
    fi
  done
  echo "OK  Ports are free."
fi

# 4. Next step
echo ""
echo "Ready. From the repository root, run: $COMPOSE up"
echo "  App:      http://localhost:$(env_value infra/.env FRONTEND_PORT)"
echo "  API docs: http://localhost:$(env_value infra/.env BACKEND_PORT)/api/v1/docs"
