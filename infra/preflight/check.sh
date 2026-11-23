#!/bin/sh
# Runs in the preflight service. Prints one message and exits non-zero on the first failure.
# Compose stops earlier, and names the file, when backend/.env is missing.

fail() {
  echo ""
  echo "PREFLIGHT FAILED: $1"
  echo "Run: $2"
  echo ""
  exit 1
}

for file in backend/pyproject.toml backend/Dockerfile frontend/package.json frontend/Dockerfile; do
  [ -f "/workspace/$file" ] ||
    fail "$file is missing. The clone is incomplete." "git status   (then git checkout -- . or clone again)"
done

# check_empty FILE NAME...: fails with the empty names and the file that holds them.
check_empty() {
  file=$1
  shift
  missing=""
  for name in "$@"; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || missing="$missing $name"
  done
  [ -z "$missing" ] ||
    fail "Required values in $file are empty:$missing" "infra/setup.sh   (Windows: infra\\setup.ps1), then fill in $file"
}

check_empty backend/.env OPENROUTER_API_KEY OPENROUTER_BASE_URL LLM_CHAT_MODEL LLM_REWRITE_MODEL \
  LLM_GRADE_MODEL LLM_GENERATE_MODEL EMBEDDING_MODEL EMBEDDING_DIMENSIONS STORAGE_BACKEND S3_BUCKET S3_REGION
check_empty infra/.env POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB S3_ACCESS_KEY S3_SECRET_KEY

case "$EMBEDDING_DIMENSIONS" in
  *[!0-9]*) fail "EMBEDDING_DIMENSIONS must be a whole number." "edit EMBEDDING_DIMENSIONS in backend/.env" ;;
esac

echo "Preflight OK: required files present, required values set."
