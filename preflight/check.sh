#!/bin/sh
# Runs in the preflight service. Prints one message and exits non-zero on the first failure.
# An empty OPENROUTER_API_KEY is caught earlier, by Compose interpolation.

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

missing=""
for name in OPENROUTER_BASE_URL LLM_REWRITE_MODEL LLM_GRADE_MODEL LLM_GENERATE_MODEL \
  EMBEDDING_MODEL EMBEDDING_DIMENSIONS POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB \
  STORAGE_BACKEND S3_BUCKET S3_REGION S3_ACCESS_KEY S3_SECRET_KEY; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || missing="$missing $name"
done
[ -z "$missing" ] || fail "Required values in .env are empty:$missing" "./setup.sh   (Windows: .\\setup.ps1), then fill in .env"

case "$EMBEDDING_DIMENSIONS" in
  *[!0-9]*) fail "EMBEDDING_DIMENSIONS must be a whole number." "edit EMBEDDING_DIMENSIONS in .env" ;;
esac

echo "Preflight OK: required files present, required values set."
