#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${REPO_ROOT}/.env.docker" ]]; then
  echo "ERROR: ${REPO_ROOT}/.env.docker not found." >&2
  echo "Copy .env.docker.example to .env.docker and adjust the values." >&2
  exit 1
fi

cd "${REPO_ROOT}/docker"
docker compose up -d

echo
echo "Services starting. Status: cd docker && docker compose ps"
echo
echo "Postgres:  postgresql+asyncpg://netbuddy:<password>@localhost:5432/netbuddy"
echo "Redis:     redis://localhost:6379/0"
echo "Adminer:   http://localhost:8080  (System: PostgreSQL, Server: postgres)"
