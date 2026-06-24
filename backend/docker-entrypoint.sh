#!/bin/sh
# Vor dem Start optional die DB-Migrationen fahren (nur der Web-Container setzt RUN_MIGRATIONS=1,
# damit Worker/Web nicht gleichzeitig migrieren). Wartet kurz auf die DB.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head ..."
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if alembic upgrade head; then
      break
    fi
    echo "[entrypoint] DB noch nicht bereit, neuer Versuch in 3s ($i/10) ..."
    sleep 3
  done
fi

exec "$@"
