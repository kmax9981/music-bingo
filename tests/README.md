# Tests

Browser and HTTP checks that run against a **throwaway copy** of the app (its own SQLite database, Spotify
simulated), so they never touch the dev or production databases.

```bash
# one-time setup: Python with Playwright and Chromium
python3 -m venv ~/pwtest && ~/pwtest/bin/pip install playwright && ~/pwtest/bin/playwright install chromium

# run everything (needs docker and the bingo-dev image)
PYTHON=~/pwtest/bin/python tests/run_tests.sh

# also prove a CSS edit changed nothing visually: save a copy of app.css first, then compare after editing
cp app/static/app.css /tmp/app.before.css
PYTHON=~/pwtest/bin/python tests/run_tests.sh --css-baseline /tmp/app.before.css
```

What is covered: the hosted game flow, the `played_track` lock-down and solo ownership, rebuilding the solo
Played Tracks list, game-code cleaning and script-injection escaping, paper cards (print page, QR codes, Make
more, Regenerate all, Continue/End after accepting, out-of-date warning), saved games, the help page and menu,
and every main page loading at desktop and phone width with no script errors.

Not covered: real Spotify playback, the embedded player, and Start Game against Spotify (headless Chrome can't
play Spotify). Try a solo game and a hosted game by hand after changes to those areas.

## Other test scripts

- `tests/test_browsers.py`: the player's whole game (join, live admit, play, claim, win) in Chromium, Firefox and WebKit
  (Safari's engine). `BROWSERS="chromium firefox webkit" tests/run_tests.sh`; WebKit runs in Playwright's Docker image.
- `tests/test_a11y.py`: accessibility (axe-core) on the main pages in both themes; needs `pip install axe-playwright-python`.
- `tests/load_test.sh N [cpus]`: N phones in one game on a real Postgres, with the app limited to a small server's CPU; needs
  `pip install aiohttp websockets`.
