#!/usr/bin/env bash
# Run the browser tests against a throwaway copy of the app (never touches the real databases).
#   tests/run_tests.sh                 run everything
# Needs: docker, the bingo-dev image (docker compose -f bingo-compose-dev.yml build), and Python with
# Playwright + Chromium (pip install playwright && playwright install chromium). Set PYTHON to that Python.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(dirname "$HERE")"
PYTHON="${PYTHON:-python3}"; PORT="${PORT:-5104}"; NAME=bingo-test-$$; SETUP_NAME="$NAME-setup"; SETUP_PORT=$((PORT + 1))
WORK="$(mktemp -d)"; trap '[ -n "${SAVE_SERVER_LOG:-}" ] && docker logs "$NAME" > "$SAVE_SERVER_LOG" 2>&1; docker rm -f "$NAME" "$SETUP_NAME" >/dev/null 2>&1; rm -rf "$WORK"' EXIT   # SAVE_SERVER_LOG=file keeps the app's log
mkdir -p "$WORK/app_copy" && cp -r "$ROOT/app" "$WORK/app_copy/app"
docker run -d --rm --user root --name "$NAME" -p "127.0.0.1:$PORT:5000" -v "$WORK/app_copy:/work/now" -v "$HERE/local_server.py:/work/run.py:ro" \
  --entrypoint python "${IMAGE:-bingo-dev}" /work/run.py /work/now 5000 >/dev/null || exit 2
for i in $(seq 1 30); do curl -s -o /dev/null "http://127.0.0.1:$PORT/enter" && break; sleep 1; done
export BASE="http://127.0.0.1:$PORT" CONTAINER="$NAME" DB_FILE="$WORK/app_copy/paper.db"   # DB_FILE: the tests read the database straight from the shared folder
# A second, brand-new copy with no accounts at all, for the first-run setup screen (tests/test_setup.py)
mkdir -p "$WORK/setup_copy" && cp -r "$ROOT/app" "$WORK/setup_copy/app"
docker run -d --rm --user root --name "$SETUP_NAME" -e NO_SEED=1 -p "127.0.0.1:$SETUP_PORT:5000" -v "$WORK/setup_copy:/work/now" -v "$HERE/local_server.py:/work/run.py:ro" \
  --entrypoint python "${IMAGE:-bingo-dev}" /work/run.py /work/now 5000 >/dev/null || exit 2
for i in $(seq 1 30); do curl -s -o /dev/null "http://127.0.0.1:$SETUP_PORT/static/app.css" && break; sleep 1; done
status=0
# The Play Alone checks run at the same time as the main ones (they don't share anything); their output is shown at the end
SOLO_OUT="$WORK/solo.out"; solo_pid=""
if [ "${SKIP_SOLO:-}" != "1" ]; then "$PYTHON" "$HERE/test_solo.py" > "$SOLO_OUT" 2>&1 & solo_pid=$!; fi
if [ "${1:-}" = "--solo-only" ]; then shift; else "$PYTHON" "$HERE/test_app.py" "$@" || status=1; fi
if [ -n "$solo_pid" ]; then wait "$solo_pid" || status=1; cat "$SOLO_OUT"; fi
if [ "${SKIP_SETUP:-}" != "1" ] && [ "${SOLO_ONLY:-}" != "1" ]; then BASE="http://127.0.0.1:$SETUP_PORT" CONTAINER="$SETUP_NAME" "$PYTHON" "$HERE/test_setup.py" || status=1; fi
# Accessibility (axe-core): SKIP_A11Y=1 to leave out
if [ "${SKIP_A11Y:-}" != "1" ] && [ "${SOLO_ONLY:-}" != "1" ]; then BASE="http://127.0.0.1:$PORT" "$PYTHON" "$HERE/test_a11y.py" || status=1; fi
# The player's whole game in other browser engines: BROWSERS="chromium firefox webkit" (WebKit runs in Playwright's Docker image)
for BR in ${BROWSERS:-chromium}; do
  if [ "$BR" = "webkit" ]; then
    docker run --rm --network host -v "$HERE:/tests:ro" -e BASE="http://127.0.0.1:$PORT" -e BROWSER=webkit "${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright/python:v1.64.0-noble}" sh -c "pip install -q playwright==1.64.0 && python /tests/test_browsers.py" || status=1
  else
    BASE="http://127.0.0.1:$PORT" BROWSER="$BR" "$PYTHON" "$HERE/test_browsers.py" || status=1
  fi
done
if [ "${SKIP_PUBLISH:-}" != "1" ] && [ -f "$HERE/test_publish.py" ]; then "$PYTHON" "$HERE/test_publish.py" || status=1; fi
exit $status
