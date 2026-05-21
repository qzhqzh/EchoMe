#!/bin/bash
# EchoMe Hub startup script
# Runs migrations then starts the app

set -e

echo "=== EchoMe Hub Starting ==="
echo "Running database migrations..."
alembic upgrade head

echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${ECHOME_PORT:-20000}" "$@"
