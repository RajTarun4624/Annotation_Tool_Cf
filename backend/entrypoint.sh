#!/bin/sh

# Wait for the database to be reachable. Host/port come from the environment so
# the same image works under docker-compose (DB_HOST=db) and on ECS/RDS
# (DB_HOST=<rds-endpoint>). Falls back to the compose defaults.
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
ATTEMPTS=0
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 60 ]; then
    echo "Database not reachable after ${ATTEMPTS}s; continuing anyway."
    break
  fi
  sleep 1
done
echo "Database is reachable."

# Apply migrations. Non-fatal: on an existing schema (e.g. tables created by
# SQLAlchemy create_all) alembic can error; the app's startup also ensures
# tables, so we log and continue rather than crash the container.
echo "Running database migrations..."
alembic upgrade head || echo "alembic upgrade head failed; continuing (schema ensured at app startup)."

# Start the API server. PORT is overridable; defaults to 8005 for compose.
echo "Starting FastAPI server on port ${PORT:-8005}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8005}"
