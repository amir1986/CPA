#!/usr/bin/env bash
set -euo pipefail

# Render cold-starts can have a brief window where DATABASE_URL is set but
# the DB isn't accepting connections yet. Retry alembic with backoff.
echo "[entrypoint] python: $(python -V)"
echo "[entrypoint] running alembic upgrade head"
attempts=0
until alembic upgrade head; do
  attempts=$((attempts + 1))
  if [ "$attempts" -ge 10 ]; then
    echo "[entrypoint] alembic failed after $attempts attempts; giving up"
    exit 1
  fi
  sleep_s=$((attempts * 2))
  echo "[entrypoint] alembic attempt $attempts failed; sleeping ${sleep_s}s"
  sleep "$sleep_s"
done

PORT="${PORT:-8000}"
echo "[entrypoint] starting uvicorn on :${PORT}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" "$@"
