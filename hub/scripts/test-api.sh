#!/bin/bash
# Quick API verification script
# Run after: docker compose up -d
# Usage: ./hub/scripts/test-api.sh [TOKEN]

TOKEN="${1:-changeme}"
BASE="http://localhost:8000"

echo "=== EchoMe Hub API Test ==="
echo ""

# 1. Health check
echo "1. Health check..."
curl -s "$BASE/health" | python3 -m json.tool
echo ""

# 2. Create a memory
echo "2. Creating test memory..."
RESPONSE=$(curl -s -X POST "$BASE/api/v1/memories" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "PR must include ticket number",
    "content": "All PR titles must start with [JIRA-XXX] ticket number. Extract from branch name if possible.",
    "type": "workflow",
    "layer": "L0",
    "priority": 9,
    "tags": ["git", "pr", "ticket"],
    "scope": {"global": true, "projects": [], "exclude_projects": []},
    "source": "manual"
  }')
echo "$RESPONSE" | python3 -m json.tool
MEMORY_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)
echo "  Created memory ID: $MEMORY_ID"
echo ""

# 3. List memories
echo "3. Listing memories..."
curl -s "$BASE/api/v1/memories" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
echo ""

# 4. Search
echo "4. Searching for 'PR rules'..."
curl -s -X POST "$BASE/api/v1/memories/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "PR rules", "top_k": 3}' | python3 -m json.tool
echo ""

# 5. Render for Claude
echo "5. Rendering for Claude Code..."
curl -s -X POST "$BASE/api/v1/sync/render" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target": "claude"}' | python3 -m json.tool
echo ""

echo "=== All tests passed! ==="
echo ""
echo "Next steps:"
echo "  1. Install CLI:  cd cli && pip install -e ."
echo "  2. Init vault:   echome init --hub-url $BASE --token $TOKEN"
echo "  3. Sync rules:   echome sync"
