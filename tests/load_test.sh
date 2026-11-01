#!/usr/bin/env bash
# Load test on a real Postgres, with the app limited to a small server's CPU, then everything is removed again.
#   tests/load_test.sh 300 [cpus]       (default 100 players, 1 CPU)
# Needs: docker, the bingo-dev image, and Python with aiohttp + websockets (set PYTHON). It never touches the real databases.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
N="${1:-100}"; CPUS="${2:-1}"; PORT="${PORT:-5188}"; PYTHON="${PYTHON:-python3}"; SUFFIX=$$
NET="load-net-$SUFFIX"; DB="load-db-$SUFFIX"; APP="load-app-$SUFFIX"; WORK="$(mktemp -d)"
cleanup() { kill "${SP:-0}" 2>/dev/null; docker rm -f "$APP" "$DB" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; rm -rf "$WORK"; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --rm --name "$DB" --network "$NET" -e POSTGRES_PASSWORD=l -e POSTGRES_USER=bingo -e POSTGRES_DB=bingo postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do docker exec "$DB" pg_isready -U bingo -d bingo >/dev/null 2>&1 && break; sleep 1; done
mkdir -p "$WORK/app_copy" && cp -r "$ROOT/app" "$WORK/app_copy/app"
docker run -d --rm --user root --ulimit nofile=65536:65536 --cpus "$CPUS" --memory 1g --name "$APP" --network "$NET" -p "127.0.0.1:$PORT:5000" \
  -e LOAD_DATABASE_URL=postgresql://bingo:l@"$DB":5432/bingo -v "$WORK/app_copy:/work/now" -v "$HERE/local_server.py:/work/run.py:ro" \
  --entrypoint python "${IMAGE:-bingo-dev}" /work/run.py /work/now 5000 >/dev/null || exit 2
for _ in $(seq 1 40); do curl -fsS -o /dev/null "http://127.0.0.1:$PORT/enter" 2>/dev/null && break; sleep 1; done
( while true; do docker stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}}' "$APP" 2>/dev/null >> "$WORK/stats.txt"; sleep 2; done ) & SP=$!
BASE="http://127.0.0.1:$PORT" "$PYTHON" "$HERE/load_test.py" "$N" 2>&1 | grep -vE "Unclosed|client_session"
echo "  most common server errors:"; docker logs "$APP" 2>&1 | grep -E "Error|Exception|error:" | sed -E "s/[0-9]+/N/g" | sort | uniq -c | sort -rn | head -4 | cut -c1-200
echo "  server (CPU limit $CPUS): peak CPU $(awk '{gsub("%","",$1); if($1>m)m=$1} END{print m}' "$WORK/stats.txt")%  peak memory $(awk '{print $2}' "$WORK/stats.txt" | sort -h | tail -1)"
