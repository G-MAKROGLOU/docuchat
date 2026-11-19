#!/bin/sh
# Fails when the frontend types were not generated from the stream schema of the pinned backend commit.
# The frontend CI already checks that its generated types match its committed schema copy.
set -eu
cd "$(dirname "$0")/.."

backend_schema=backend/contract/stream-events.schema.json
frontend_schema=frontend/contract/stream-events.schema.json
backend_commit=$(git -C backend rev-parse --short HEAD)
frontend_commit=$(git -C frontend rev-parse --short HEAD)

if ! cmp -s "$backend_schema" "$frontend_schema"; then
  echo "CONTRACT MISMATCH: frontend@$frontend_commit was generated from a different stream schema than backend@$backend_commit."
  diff -u "$backend_schema" "$frontend_schema" || true
  echo "Action: in frontend/, run: npm run contract:generate -- ../$backend_schema"
  echo "        commit and push in the frontend, then move the frontend pointer in this repository."
  exit 1
fi
echo "Contract OK: frontend@$frontend_commit matches the stream schema of backend@$backend_commit."
