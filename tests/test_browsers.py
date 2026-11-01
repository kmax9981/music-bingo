#!/usr/bin/env python3
"""The player's whole game in a real browser engine: join, get admitted, play, claim, win. Run it in Chromium, Firefox and
WebKit (Safari's engine):  BROWSER=firefox python tests/test_browsers.py   (tests/run_tests.sh does this with BROWSERS=...).
Needs only BASE (the throwaway server); it does not touch the database directly, so it also runs inside Playwright's Docker image."""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_spotify

BASE = os.environ.get("BASE", "http://127.0.0.1:5104").rstrip("/")
BROWSER = os.environ.get("BROWSER", "chromium")
results = []
# the test server's fake playlist: song n has the id "t<n>" (see local_server.py)
import ast
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_server.py"), encoding="utf-8").read()
SONGS = ast.literal_eval(re.search(r"^SONGS = (\[.*?\])\n", _src, re.S | re.M).group(1))


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"PASS  [{BROWSER}] " + name if ok else f"FAIL  [{BROWSER}] " + name + (f"  [{detail}]" if detail else ""))


def main():
    problems = []
    with sync_playwright() as pw:
        b = getattr(pw, BROWSER).launch()
        hctx = b.new_context(viewport={"width": 1280, "height": 900}); hp = hctx.new_page(); fake_spotify.install(hp, [])
        pctx = b.new_context(viewport={"width": 390, "height": 780}, has_touch=True, is_mobile=(BROWSER != "firefox")); pp = pctx.new_page()
        for pg, who in ((hp, "host"), (pp, "player")):
            pg.on("pageerror", lambda e, who=who: None if "debugger eval code" in (getattr(e, "stack", "") or "") else problems.append(f"{who} page error: {str(e)[:120]} @ {(getattr(e, 'stack', '') or '').strip().splitlines()[:2]}"))
            pg.on("console", lambda m, who=who: problems.append(f"{who} console error: {m.text[:90]} @ {m.location.get('url', '').split('/', 3)[-1][:50]}:{m.location.get('lineNumber')}") if m.type == "error" and "sdk.scdn" not in m.text and "Failed to load resource" not in m.text
                         and "apply a stylesheet because" not in m.text else None)   # WebKit reports el.style.display = ... as a style-src-attr violation but still applies it: checked below

        # does this engine have the CSS the themes rely on?
        frames = []
        pp.on("websocket", lambda ws: (frames.append("OPEN " + ws.url.split("/ws/")[-1]), ws.on("framereceived", lambda f: frames.append(str(f)[:110])), ws.on("close", lambda *_: frames.append("CLOSED"))))
        feat = hp.evaluate("({mix: CSS.supports('color', 'color-mix(in srgb, red 50%, blue)'), has: CSS.supports('selector(:has(*))'), aspect: CSS.supports('aspect-ratio', '1'), grid: CSS.supports('display', 'grid'), dvh: CSS.supports('height', '100dvh')})")
        check("the browser supports the CSS the app uses (color-mix, :has, aspect-ratio, grid)", feat["mix"] and feat["has"] and feat["aspect"] and feat["grid"], str(feat))

        hp.goto(BASE + "/login?next=/host"); hp.fill("input[name=username]", "h"); hp.fill("input[name=password]", "pw"); hp.click("button[type=submit]"); hp.wait_for_load_state("networkidle")
        check("the host logs in", "/login" not in hp.url, hp.url)
        paper_hidden = hp.evaluate("() => ['paperOptions', 'savedBlock', 'eventPicked'].map(id => getComputedStyle(document.getElementById(id)).display)")
        check("panels that should start hidden on the dashboard are hidden (the scripts' style changes do apply)", paper_hidden == ["none", "none", "none"], str(paper_hidden))
        hp.check("#paperToggle"); hp.wait_for_timeout(200)
        check("ticking Paper cards shows its options", hp.evaluate("getComputedStyle(document.getElementById('paperOptions')).display") != "none"); hp.uncheck("#paperToggle")
        hp.fill("input[name=game_name]", "Browser night"); hp.fill("input[name=playlist_id_or_url]", "PLAYLIST75AAAAAAAAAAAA"); hp.click("#createBtn"); hp.wait_for_load_state("networkidle")
        code = hp.url.split("/host/game/")[1].split("/")[0]
        check("the host creates a game", len(code) == 5, hp.url)

        pp.goto(f"{BASE}/game/{code}"); pp.fill("input[name=name]", "Pat"); pp.click("button[type=submit]"); pp.wait_for_load_state("networkidle")
        check("a player joins from a phone-sized screen and waits to be admitted", "/player/" in pp.url and pp.locator("#cardGrid .sq").count() in (0, 25) and "admitted" in pp.content().lower(), pp.url)
        hp.goto(f"{BASE}/host/game/{code}"); hp.wait_for_timeout(1000)
        check("the host sees the player in the list (live socket)", "Pat" in hp.locator("#playersList").inner_text())
        hp.click("#admitBtn")
        try:
            pp.wait_for_selector("#cardGrid .sq", timeout=8000)
        except Exception:
            pass
        check("admitting the player gives them their card at once, without reloading (WebSocket)", pp.locator("#cardGrid .sq").count() == 25, f"{pp.locator('#cardGrid .sq').count()} squares")
        check("the card has B I N G O above its five columns", pp.locator("#cardGrid .cardLetter").all_inner_texts() == list("BINGO"))
        check("the free square in the middle is already marked", "marked" in (pp.locator('#cardGrid .sq[data-pos="12"]').get_attribute("class") or ""))
        geo = pp.evaluate("(() => { const r = e => e.getBoundingClientRect(); const g = r(document.getElementById('cardGrid')); return {w: Math.round(g.width), vw: innerWidth, scroll: document.documentElement.scrollWidth}; })()")
        check("the card fits the phone screen with no sideways scrolling", geo["scroll"] <= geo["vw"] + 1 and geo["w"] <= geo["vw"], str(geo))

        hp.evaluate(f"fetch('/host/game/{code}/start', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{device_id: 'dev-1'}})}})"); hp.wait_for_timeout(1500)
        titles = {i: pp.locator(f'#cardGrid .sq[data-pos="{i}"] .sqText').inner_text().strip() for i in range(25) if i != 12}
        sq = pp.locator('#cardGrid .sq[data-pos="0"]'); sq.click(); pp.wait_for_timeout(300)
        check("tapping a square marks it, and tapping again unmarks it", "marked" in (sq.get_attribute("class") or "")); sq.click(); pp.wait_for_timeout(300)
        check("...", "marked" not in (sq.get_attribute("class") or ""))

        # the host's player plays the four songs of the middle row; the player marks them and calls bingo
        row = [10, 11, 13, 14]
        track_resp = []
        for n, pos in enumerate(row):
            track_resp.append(hp.evaluate("([t, i]) => fetch('/host/game/" + code + "/track_update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: t, track_id: i, artist: 'Band', position_ms: 15000, paused: false})}).then(r => r.text())", [titles[pos], 't' + str(SONGS.index(titles[pos]))]))
            hp.wait_for_timeout(500)
        hp.wait_for_timeout(800)
        try:
            pp.wait_for_function("document.getElementById('npTitle') && document.getElementById('npTitle').textContent.trim().length > 1", timeout=15000)
        except Exception:
            pass
        np_title = pp.locator("#npTitle").inner_text().strip()
        np_dbg = pp.evaluate("() => { const e = id => document.getElementById(id); return {title: e('npTitle') && e('npTitle').textContent, artist: e('npArtist') && e('npArtist').textContent, cd: e('npCountdown') && [e('npCountdown').hidden, e('npCountdown').textContent], box: (document.getElementById('nowPlaying') || {}).className}; }") if np_title != titles[row[-1]] else ""
        check("the song now playing is shown on the player's phone (WebSocket, after the reveal delay)", np_title == titles[row[-1]], f"{np_title!r} vs {titles[row[-1]]!r} {np_dbg} frames={frames[-8:]} track_resp={track_resp}")
        for pos in row:
            pp.locator(f'#cardGrid .sq[data-pos="{pos}"]').click(); pp.wait_for_timeout(150)
        pp.click("#bingoBtn"); pp.wait_for_timeout(1500)
        hp.goto(f"{BASE}/host/game/{code}"); hp.wait_for_timeout(1500)
        claim = hp.locator("#claimsList .claimRow")
        check("the bingo claim reaches the host with the player's name and a valid auto-check", claim.count() == 1 and "Pat" in claim.first.inner_text() and "valid" in claim.first.inner_text().lower(), claim.first.inner_text()[:120] if claim.count() else "no claim")
        acc = hp.locator("#claimsList .claimActions button", has_text=re.compile("accept", re.I)); acc_n = acc.count(); acc.first.click(); hp.wait_for_timeout(1500)
        try:
            pp.wait_for_selector("#bingoOverlay:not(.hidden)", timeout=8000)
        except Exception:
            pass
        check("accepting the claim shows the winner screen on the player's phone", pp.locator("#bingoOverlay").is_visible() and pp.locator("#fireworksCanvas").count() == 1, f"overlay not shown (accept buttons: {acc_n}; overlay class: {pp.locator('#bingoOverlay').get_attribute('class')}; claims text: {hp.locator('#claimsList').inner_text()[:100]!r})")
        pp.screenshot(path=os.environ.get("SHOT", f"/tmp/browser-{BROWSER}.png")) if os.environ.get("SHOT") else None
        check("no JavaScript errors in the engine", not problems, "; ".join(problems[:3]))
        b.close()
    print(f"\n{sum(results)}/{len(results)} {BROWSER} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
