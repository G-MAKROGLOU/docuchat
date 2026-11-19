#!/bin/sh
# Runs in the preflight service. Required .env values are checked earlier, by Compose
# interpolation in the preflight environment. Prints one message and exits non-zero on failure.

fail() {
  echo ""
  echo "PREFLIGHT FAILED: $1"
  echo "Run: $2"
  echo ""
  exit 1
}

for file in backend/pyproject.toml backend/Dockerfile frontend/package.json frontend/Dockerfile; do
  [ -f "/workspace/$file" ] ||
    fail "$file is missing. The submodules are not checked out." \
      "git submodule update --init --recursive   (or ./setup.sh, Windows: .\\setup.ps1)"
done

case "$EMBEDDING_DIMENSIONS" in
  *[!0-9]*) fail "EMBEDDING_DIMENSIONS must be a whole number." "edit EMBEDDING_DIMENSIONS in .env" ;;
esac

echo "Preflight OK: submodules present, required values set."
