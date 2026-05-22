#!/bin/bash
# migrate-volumes-to-disk.sh
# Migrate Docker named volumes to local ./data/ directory
#
# Usage: bash scripts/migrate-volumes-to-disk.sh
#
# This script:
# 1. Stops running containers
# 2. Copies data from Docker named volumes to ./data/
# 3. Removes old Docker volumes (optional)
#
# After running, use: docker compose up -d --build

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "━━━ EchoMe: Migrate Docker volumes to disk ━━━"
echo ""

# Check if old volumes exist
PG_VOLUME=$(docker volume ls -q | grep -E "pgdata$" | head -1)
REDIS_VOLUME=$(docker volume ls -q | grep -E "redisdata$" | head -1)
EMBED_VOLUME=$(docker volume ls -q | grep -E "embedding-models$" | head -1)

if [ -z "$PG_VOLUME" ] && [ -z "$REDIS_VOLUME" ] && [ -z "$EMBED_VOLUME" ]; then
    echo "No Docker volumes found to migrate."
    echo "If this is a fresh install, just run: docker compose up -d --build"
    exit 0
fi

echo "Found volumes:"
[ -n "$PG_VOLUME" ] && echo "  - PostgreSQL: $PG_VOLUME"
[ -n "$REDIS_VOLUME" ] && echo "  - Redis: $REDIS_VOLUME"
[ -n "$EMBED_VOLUME" ] && echo "  - Embedding models: $EMBED_VOLUME"
echo ""

# Stop containers
echo "[1/4] Stopping containers..."
docker compose down 2>/dev/null || true

# Create target directories
echo "[2/4] Creating ./data/ directories..."
mkdir -p data/postgres data/redis data/embedding-models

# Copy data from volumes
echo "[3/4] Copying data from Docker volumes to ./data/..."

if [ -n "$PG_VOLUME" ]; then
    echo "  Copying PostgreSQL data..."
    docker run --rm \
        -v "${PG_VOLUME}:/source:ro" \
        -v "$(pwd)/data/postgres:/target" \
        alpine sh -c "cp -a /source/. /target/"
    echo "  ✓ PostgreSQL data copied to ./data/postgres/"
fi

if [ -n "$REDIS_VOLUME" ]; then
    echo "  Copying Redis data..."
    docker run --rm \
        -v "${REDIS_VOLUME}:/source:ro" \
        -v "$(pwd)/data/redis:/target" \
        alpine sh -c "cp -a /source/. /target/"
    echo "  ✓ Redis data copied to ./data/redis/"
fi

if [ -n "$EMBED_VOLUME" ]; then
    echo "  Copying embedding models..."
    docker run --rm \
        -v "${EMBED_VOLUME}:/source:ro" \
        -v "$(pwd)/data/embedding-models:/target" \
        alpine sh -c "cp -a /source/. /target/"
    echo "  ✓ Embedding models copied to ./data/embedding-models/"
fi

# Prompt to remove old volumes
echo ""
echo "[4/4] Migration complete!"
echo ""
echo "Old Docker volumes still exist. To remove them (saves disk space):"
echo ""
[ -n "$PG_VOLUME" ] && echo "  docker volume rm $PG_VOLUME"
[ -n "$REDIS_VOLUME" ] && echo "  docker volume rm $REDIS_VOLUME"
[ -n "$EMBED_VOLUME" ] && echo "  docker volume rm $EMBED_VOLUME"
echo ""
echo "━━━ Done! Now run: docker compose up -d --build ━━━"
