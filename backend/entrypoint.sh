#!/bin/sh

set -e

echo "Waiting for database to be ready..."

: "${DB_HOST:?Need to set DB_HOST}"
: "${DB_PORT:?Need to set DB_PORT}"

timeout=30
counter=0

while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
  counter=$((counter + 1))
  if [ $counter -ge $timeout ]; then
    echo "❌ Database connection timeout after $timeout seconds"
    exit 1
  fi
  echo "⏳ Waiting for database... (${counter}/${timeout}s)"
done

echo "✅ Database is ready!"

# Выполняем миграции только если установлена переменная RUN_MIGRATIONS
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Running database migrations..."
  uv run alembic -c backend/alembic.ini upgrade head
  echo "✅ Migrations completed"
else
  echo "⏩ Skipping migrations (RUN_MIGRATIONS=false)"
fi

echo "Starting application..."
exec uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000