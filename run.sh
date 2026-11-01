#!/usr/bin/env bash
# Starts Music Bingo. Run it from this folder:   ./run.sh
# The first time it makes a private ".env" file with a random database password, then starts everything and tells you
# where to go next. Run it again any time to start or update (it keeps your data).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

command -v docker >/dev/null 2>&1 || { echo "Docker is not installed. Get it from https://docs.docker.com/get-docker/ and run this again." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "This needs Docker Compose v2 ('docker compose'). See https://docs.docker.com/compose/install/" >&2; exit 1; }

if [ ! -f .env ] && [ -n "$(docker compose ps -aq db 2>/dev/null)" ]; then
  # The database was already started without ./run.sh (with the built-in password): a new password would lock the app out of it
  echo "Note: the database already exists, so it keeps its current password (no .env is made)."
elif [ ! -f .env ]; then
  umask 077   # only you can read it
  PW="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  printf 'DB_PASSWORD=%s\n' "$PW" > .env
  echo "Made .env with a random database password (keep it private; it is never shared or committed)."
fi
echo "Getting Music Bingo ready (the first start downloads the images, which can take a minute)..."
docker compose pull app >/dev/null 2>&1 || docker compose build app   # no published image yet: build it from this folder
docker compose up -d

printf 'Waiting for it to start'
UP=0
for _ in $(seq 1 60); do   # ask the app from inside its own container: it may have no published port (behind a proxy)
  if docker compose exec -T app curl -fsS http://127.0.0.1:5000/static/app.css >/dev/null 2>&1; then UP=1; break; fi
  printf '.'; sleep 2
done
echo
if [ "$UP" != "1" ]; then
  echo "It did not answer within two minutes. See what it says:  docker compose logs app" >&2
  exit 1
fi

# Where to open it: the port Docker published for the app (none when a reverse proxy is the only way in)
ADDR="$(docker compose port app 5000 2>/dev/null | head -1 | sed 's/^0\.0\.0\.0:/127.0.0.1:/; s/^\[::\]:/127.0.0.1:/')"
[[ "$ADDR" == *:0 || "$ADDR" == ":"* ]] && ADDR=""   # Compose answers ":0" when nothing is published
# Until the first account exists, setup is the page to use (afterwards it sends you to the login page)
NEXT="$(docker compose exec -T app curl -s -o /dev/null -w '%{redirect_url}' http://127.0.0.1:5000/setup 2>/dev/null || true)"
echo
echo "Music Bingo is running."
if [ -n "$ADDR" ]; then echo "  Open:  http://$ADDR"; else echo "  Open it at the public address your reverse proxy serves (see docs/HTTPS.md)."; fi
if [[ "$NEXT" != *"/login"* ]]; then
  echo "  First run: open it and choose your admin username and password."
else
  echo "  It is already set up: log in with your admin account."
fi
echo
echo "Stop it:    docker compose stop        Update it:   ./run.sh"
