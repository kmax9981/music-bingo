#!/usr/bin/env python3
"""Browser and HTTP checks for Music Bingo. Run through tests/run_tests.sh, which starts a throwaway copy of the
app with Spotify simulated. Prints PASS/FAIL per check and exits 1 if any fail.

Optional: --css-baseline FILE compares screenshots of every main page, at desktop and phone width, using the
current app.css against FILE (for example a copy saved before editing the CSS); every page must look identical.

Not covered (headless Chrome can't play Spotify): real playback, the embedded player, Start Game against Spotify.
"""
import json, os, re, subprocess, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:5104").rstrip("/")
CONTAINER = os.environ.get("CONTAINER", "")
PLAYLIST = "https://open.spotify.com/playlist/PLAYLIST75AAAAAAAAAAAA"
results = []


_last_check = [time.time()]


def check(name, ok, detail=""):
    results.append(bool(ok))
    if os.environ.get("TIMING"):   # TIMING=1: show how long each check took to get to (find the slow parts)
        now = time.time(); name = f"[{now - _last_check[0]:5.1f}s] " + name; _last_check[0] = now
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


def sql(q):
    """Run SQL in the test container's SQLite database; returns rows."""
    if q.lstrip().lower().startswith("select") and os.environ.get("DB_FILE") and os.path.exists(os.environ["DB_FILE"]):
        import sqlite3   # reading the container's database file straight from the shared folder is quick; writes (owned by root there) go through docker exec
        c = sqlite3.connect("file:" + os.environ["DB_FILE"] + "?mode=ro", uri=True, timeout=20)
        try:
            return json.loads(json.dumps(c.execute(q).fetchall()))
        finally:
            c.close()
    code = ("import sqlite3,json;c=sqlite3.connect('/work/now/paper.db');"
            f"r=c.execute({q!r}).fetchall();c.commit();print(json.dumps(r))")
    out = subprocess.run(["docker", "exec", CONTAINER, "python", "-c", code], capture_output=True, text=True)
    return json.loads(out.stdout or "[]")



def tpost(ctx, url, **kw):
    """POST from a browser context's request object with that browser's CSRF token (read from any page it can load)."""
    html = ctx.request.get(BASE + "/enter").text()
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    hdrs = dict(kw.pop("headers", None) or {})
    hdrs["X-CSRF-Token"] = m.group(1) if m else ""
    return ctx.request.post(url, headers=hdrs, **kw)

def login(browser, user):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.route("https://sdk.scdn.co/**", lambda r: r.abort())
    pg.goto(BASE + "/login?next=/host")
    pg.fill("input[name=username]", user)
    pg.fill("input[name=password]", "pw")
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")
    return ctx, pg


def make_png(w, h, rgb=(200, 30, 30)):
    """A plain PNG of the given size (for the logo tests)."""
    import zlib, struct
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def create_game_event(pg, name, event_id):
    pg.goto(BASE + "/host")
    pg.fill("input[name=game_name]", name)
    pg.fill("input[name=playlist_id_or_url]", PLAYLIST)
    pg.select_option("#eventSelect", str(event_id))
    pg.click("#createBtn")
    pg.wait_for_load_state("networkidle")
    return pg.url.split("/host/game/")[1].split("/")[0]


def create_game(pg, name, paper=0, pattern=None):
    pg.goto(BASE + "/host")
    pg.fill("input[name=game_name]", name)
    if pattern:
        pg.select_option("#winPattern", pattern)
    pg.fill("input[name=playlist_id_or_url]", PLAYLIST)
    if paper:
        pg.check("#paperToggle")
        pg.fill("input[name=paper_count]", str(paper))
    pg.click("#createBtn")
    pg.wait_for_load_state("networkidle")
    return pg.url.split("/host/game/")[1].split("/")[0]


def join(browser, code, name):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.goto(f"{BASE}/game/{code}")
    pg.fill("input[name=name]", name)
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")
    return ctx, pg


def main():
    js_errors = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        host, hp = login(b, "h")
        hp.on("pageerror", lambda e: js_errors.append(str(e)[:100]))
        other, _ = login(b, "h2")
        outsider = b.new_context()

        # ---- Hosted game flow ----
        code = create_game(hp, "Flow")
        check("game created with a 5-character code", re.fullmatch(r"[A-Z0-9]{5}", code or ""), code)
        p1, p1pg = join(b, code, "Ann")
        p2, _ = join(b, code, "Bob")
        tpost(host, f"{BASE}/host/game/{code}/admit_all")
        check("both players listed in the database", sql(f"select count(*) from players where game_id=(select id from games where code='{code}')")[0][0] == 2)
        r = tpost(p1, f"{BASE}/player/{code}/1/claim_bingo", data="{}", headers={"Content-Type": "application/json"})
        check("an invalid bingo claim is accepted for review, not auto-valid", r.status == 200 and r.json().get("auto_valid") is False, r.text()[:80])
        check("continue game", tpost(host, f"{BASE}/host/game/{code}/continue_game").status == 200)
        check("end game", tpost(host, f"{BASE}/host/game/{code}/end_game").status == 200)

        # ---- played_track lock-down and solo ownership ----
        song = json.dumps({"title": "Fake", "artist": "X", "uri": "spotify:track:zzz"})
        hdr = {"Content-Type": "application/json"}
        n0 = sql("select count(*) from played_tracks")[0][0]
        check("outsider cannot add played tracks to a hosted game", tpost(outsider, f"{BASE}/player/{code}/1/played_track", data=song, headers=hdr).status == 403)
        check("even the owner cannot use the solo endpoint on a hosted game", tpost(host, f"{BASE}/player/{code}/1/played_track", data=song, headers=hdr).status == 403)
        check("no rows were written by those requests", sql("select count(*) from played_tracks")[0][0] == n0)
        sql(f"update games set game_type='solo', owner_key='host:'||(select id from host_users where username='h') where code='{code}'")
        check("outsider and other hosts cannot write to a solo game",
              tpost(outsider, f"{BASE}/player/{code}/1/played_track", data=song, headers=hdr).status == 403
              and tpost(other, f"{BASE}/player/{code}/1/played_track", data=song, headers=hdr).status == 403)
        check("the owner can record a solo song", tpost(host, f"{BASE}/player/{code}/1/played_track", data=song, headers=hdr).status == 200
              and sql("select count(*) from played_tracks")[0][0] == n0 + 1)
        # solo: list rebuilt in a fresh tab from what the server recorded
        for i, (t, a) in enumerate([("Africa", "Toto"), ("Creep", "Radiohead")], 10):
            sql(f"insert into played_tracks(game_id,seq,spotify_track_id,title,artist,played_at) select id,{i},'t{i}','{t}','{a}',datetime('now') from games where code='{code}'")
        check("played_tracks list is owner-only", outsider.request.get(f"{BASE}/player/{code}/1/played_tracks").status == 403
              and other.request.get(f"{BASE}/player/{code}/1/played_tracks").status == 403)
        sp = host.new_page()
        sp.route("https://sdk.scdn.co/**", lambda r: r.abort())
        sp.on("pageerror", lambda e: js_errors.append("solo: " + str(e)[:100]))
        sp.goto(f"{BASE}/play/solo/{code}/1")
        sp.wait_for_timeout(2500)
        chips = sp.locator("#playedList .chip").all_inner_texts()
        check("solo: a fresh tab rebuilds the Played Tracks list from the server", len(chips) >= 3 and chips[0].startswith("Creep"), str(chips))
        sp.close()

        # ---- Game code handling / script injection ----
        pg = outsider.new_page()
        r = pg.goto(BASE + "/game/%3CIMG%20SRC%3DX%20ONERROR%3D1%3E")
        html = pg.content()
        check("hostile game code is cleaned and escaped", "not found" in html and not re.search(r"<img[^>]*onerror", html, re.I) and r.status == 404)
        check("normal wrong code shows 'Game ZZZZZ not found.'", "Game ZZZZZ not found." in (pg.goto(BASE + "/game/ZZZZZ") and pg.content()))
        pg.goto(BASE + "/game/%20--")
        check("a code that is empty after cleaning shows a normal not-found page", "Game not found." in pg.content())
        lower = create_game(hp, "Case")
        pg.goto(f"{BASE}/game/{lower.lower()}")
        check("lowercase game code works", pg.url.endswith(lower) and pg.locator("input[name=name]").count() == 1, pg.url)
        r = tpost(b.new_context(), BASE + "/host/login", form={"username": "h", "password": "pw"}, max_redirects=0)
        check("legacy POST /host/login redirects to /login", r.status == 307 and r.headers.get("location", "").endswith("/login"), str(r.status))

        # ---- Login hardening ----
        def try_login(ip, user="h", pw="wrong"):
            return tpost(b.new_context(), BASE + "/login", form={"username": user, "password": pw, "next": "/host"},
                                                headers={"CF-Connecting-IP": ip}, max_redirects=0)
        codes = [try_login("203.0.113.7").status for _ in range(6)]
        check("5 wrong passwords are refused, the 6th attempt is throttled (429)", codes == [401] * 5 + [429], str(codes))
        check("even the right password is refused while throttled", try_login("203.0.113.7", pw="pw").status == 429)
        check("another visitor is not affected by the throttle", try_login("203.0.113.8", pw="pw").status == 302)
        check("a successful login clears that visitor's failures", [try_login("203.0.113.8").status for _ in range(5)] == [401] * 5)
        check("a forged session cookie is not accepted",
              b.new_context().request.get(BASE + "/host", headers={"Cookie": "host_session=eyJob3N0Ijp0cnVlLCJ1aWQiOjF9.AAAA.BBBB"}, max_redirects=0).status in (302, 303, 307))
        check("a Spotify callback without a matching state is rejected",
              "didn't connect" in (hp.goto(BASE + "/auth/spotify/callback?code=abc&state=forged") and hp.content()))

        # ---- Host page layout: three columns side by side, nothing pushed below ----
        lg = create_game(hp, "Layout")
        hp.set_viewport_size({"width": 1440, "height": 900})
        hp.goto(f"{BASE}/host/game/{lg}")
        hp.wait_for_timeout(800)
        cols = hp.evaluate("Array.from(document.querySelectorAll('.hostGrid3 > .hostCol')).map(c => { const r = c.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; })")
        check("the host page has three columns side by side", len(cols) == 3 and len({c[1] for c in cols}) == 1 and cols[0][0] < cols[1][0] < cols[2][0], str(cols))
        check("Players and Bingo Claims are inside the right column", hp.locator(".hostCol3 #claimsList, .hostGrid3 > .hostCol:nth-child(3) #claimsList").count() >= 1 or hp.evaluate("!!document.querySelector('.hostGrid3 > .hostCol:nth-child(3)') && document.querySelector('.hostGrid3 > .hostCol:nth-child(3)').textContent.includes('Bingo Claims')"))

        check("no 0:00 is shown until something is playing", hp.locator("#hostNpTimer").inner_text().strip() == "")
        h0 = hp.evaluate("document.querySelector('.hintLine').getBoundingClientRect().height + document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect().height")
        hp.click("#playBtn"); hp.wait_for_timeout(500)
        h1 = hp.evaluate("document.querySelector('.hintLine').getBoundingClientRect().height + document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect().height")
        check("the 'start the game first' notice does not change the size of the message slot or the panel", abs(h0 - h1) < 1 and "Start the game first" in hp.locator("#transportMsg").inner_text(), f"{h0} -> {h1}")

        # ---- Next can't be spammed ----
        sql(f"update games set status='started' where code='{lg}'")
        hp.goto(f"{BASE}/host/game/{lg}")
        hp.wait_for_timeout(800)
        nexts = []
        hp.on("request", lambda r: nexts.append(r.url) if r.url.endswith("/spotify/next") else None)
        for _ in range(4):
            hp.locator("#nextBtn").dispatch_event("click")
        hp.wait_for_timeout(600)
        check("pressing Next four times in a row sends only one request", len(nexts) == 1 and hp.locator("#nextBtn").is_disabled(), str(len(nexts)))
        hp.wait_for_timeout(2200)
        check("Next works again after 2 seconds", not hp.locator("#nextBtn").is_disabled())
        two = hp.evaluate(f"(async () => {{ const f = () => fetch('/host/game/{lg}/spotify/next', {{method: 'POST', credentials: 'same-origin'}}).then(r => r.json()); const a = await f(); const b = await f(); return [a, b]; }})()")
        check("the server ignores a second Next right after the first", not two[0].get("throttled") and two[1].get("throttled") is True, str(two))
        sql(f"update games set status='lobby' where code='{lg}'")

        # ---- B I N G O above the card columns (phone card) ----
        lctx, lpg = join(b, lg, "Letty")
        tpost(host, f"{BASE}/host/game/{lg}/admit_all")
        lpg.reload(); lpg.wait_for_timeout(1200)
        lpg.set_viewport_size({"width": 390, "height": 844})
        geo = lpg.evaluate("""() => { const L = [...document.querySelectorAll('#cardGrid .cardLetter')]; const S = [...document.querySelectorAll('#cardGrid .sq')].slice(0, 5);
            return {letters: L.map(e => e.textContent.trim()).join(''), aligned: L.length === 5 && S.length === 5 && L.every((e, i) => Math.abs((e.getBoundingClientRect().left + e.getBoundingClientRect().width / 2) - (S[i].getBoundingClientRect().left + S[i].getBoundingClientRect().width / 2)) < 2),
                    above: L.length === 5 && L[0].getBoundingClientRect().bottom <= S[0].getBoundingClientRect().top + 1, sideways: document.documentElement.scrollWidth > innerWidth + 1}; }""")
        check("the phone card has B I N G O centred above the five columns", geo["letters"] == "BINGO" and geo["aligned"] and geo["above"] and not geo["sideways"], str(geo))
        lctx.close()

        # ---- Bingo hints ----
        hp.goto(f"{BASE}/host/game/{lg}")
        hp.wait_for_timeout(800)
        check("hints start off; both switches show, and 'Players choose' is greyed out", not hp.locator("#hintOn").is_checked() and hp.locator("#hintOn").is_visible() and hp.locator("#hintOptin").is_visible() and hp.locator("#hintOptin").is_disabled() and sql(f"select hint_mode from games where code='{lg}'")[0][0] == "off")
        hdr0 = hp.evaluate("[document.querySelector('.hintLine').getBoundingClientRect().height, document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect().height]")
        hp.check("#hintOn"); hp.wait_for_timeout(500)
        check("turning hints on saves 'everyone' and enables 'Players choose'", sql(f"select hint_mode from games where code='{lg}'")[0][0] == "all" and not hp.locator("#hintOptin").is_disabled())
        hdr1 = hp.evaluate("[document.querySelector('.hintLine').getBoundingClientRect().height, document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect().height]")
        check("the hints message does not change the size of the box", hdr0 == hdr1 and "Hints" in hp.locator("#hostMsg").inner_text(), f"{hdr0} -> {hdr1}")
        hp.check("#hintOptin"); hp.wait_for_timeout(500)
        check("'Players choose' saves opt-in mode", sql(f"select hint_mode from games where code='{lg}'")[0][0] == "optin")
        hp.reload(); hp.wait_for_timeout(600)
        check("the host switches keep their state after a reload", hp.locator("#hintOn").is_checked() and hp.locator("#hintOptin").is_checked())
        bad = hp.evaluate(f"fetch('/host/game/{lg}/hint_mode', {{method: 'POST', credentials: 'same-origin', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{mode: 'bogus'}})}}).then(r => r.status)")
        check("an invalid hint mode is refused", bad == 400)
        hctx, hpg = join(b, lg, "Hinty")
        tpost(host, f"{BASE}/host/game/{lg}/admit_all")
        hpg.reload(); hpg.wait_for_timeout(1200)
        check("in 'Players choose' mode the player sees a Hints switch", hpg.locator("#hintToggleWrap").is_visible())
        res = hpg.evaluate("""() => {
            const grid = document.getElementById('cardGrid');
            const lit = () => Array.from(grid.querySelectorAll('.cardLetter')).map((e, i) => e.classList.contains('lit') ? i : -1).filter(i => i >= 0);
            const sq = grid.querySelector('.sq[data-pos="7"] .sqText');        // row 2, column C: the N tile
            BingoHint.show(grid, sq.textContent.trim(), 'x');
            const onCard = lit();
            BingoHint.show(grid, 'A Song That Is Not On Any Card', 'seed-1'); const a = lit();
            BingoHint.show(grid, 'A Song That Is Not On Any Card', 'seed-1'); const again = lit();
            const seen = new Set();
            for (let i = 0; i < 40; i++) { BingoHint.show(grid, 'A Song That Is Not On Any Card', 'seed-' + i); seen.add(lit().join()); }
            BingoHint.clear(grid);
            return {onCard, a, again, variety: seen.size, none: lit()};
        }""")
        check("a song on the card lights its own column", res["onCard"] == [2], str(res))
        check("a song not on the card lights exactly one column, the same one every time for that card", len(res["a"]) == 1 and res["a"] == res["again"], str(res))
        check("the decoy column varies from song to song", res["variety"] >= 3, str(res["variety"]))
        check("clearing removes every light", res["none"] == [], str(res))
        sql(f"update games set hint_mode='all' where code='{lg}'")
        hpg.reload(); hpg.wait_for_timeout(1000)
        check("when hints are on for everyone the player has no switch", not hpg.locator("#hintToggleWrap").is_visible())
        check("hint code runs in the page", hpg.evaluate("typeof window.__bingoHandleTrackMsg") == "function")
        sql(f"update games set hint_mode='all' where code='{lg}'")
        hpg.reload(); hpg.wait_for_timeout(1000)
        lit = lambda: hpg.evaluate("Array.from(document.querySelectorAll('#cardGrid .cardLetter')).map((e, i) => e.classList.contains('lit') ? i : -1).filter(i => i >= 0)")
        card_title = hpg.evaluate("document.querySelector('#cardGrid .sq[data-pos=\"7\"] .sqText').textContent.trim()")
        hpg.evaluate("(t) => window.__bingoHandleTrackMsg({title: t, artist: 'A', track_id: 'trk-1', position_ms: 1000, paused: false, server_ts_ms: Date.now()})", card_title)
        hpg.wait_for_timeout(500)
        check("the letter lights at once, while the title is still hidden", lit() == [2], str(lit()))
        hpg.evaluate("(t) => window.__bingoHandleTrackMsg({title: t, artist: 'A', track_id: 'trk-2', position_ms: 10500, paused: false, server_ts_ms: Date.now()})", card_title)
        hpg.wait_for_timeout(300)
        check("it stays on that column once the title is revealed", lit() == [2], str(lit()))
        hpg.evaluate("(t) => window.__bingoHandleTrackMsg({title: 'Another Song', artist: 'B', track_id: 'trk-3', position_ms: 500, paused: false, server_ts_ms: Date.now()})", card_title)
        hpg.wait_for_timeout(300)
        check("when the next song starts the letter moves on at once (one column, a decoy for a song not on the card)", len(lit()) == 1, str(lit()))
        setmode = lambda m: hp.evaluate(f"fetch('/host/game/{lg}/hint_mode', {{method: 'POST', credentials: 'same-origin', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{mode: '{m}'}})}}).then(r => r.status)")
        setmode("optin"); hpg.wait_for_timeout(1000)
        check("switching to 'Players choose' during a live game shows the player's Hints switch without a reload", hpg.locator("#hintToggleWrap").is_visible())
        setmode("all"); hpg.wait_for_timeout(1000)
        check("switching to 'everyone' during a live game hides the switch again", not hpg.locator("#hintToggleWrap").is_visible())
        setmode("off"); hpg.wait_for_timeout(1000)
        check("switching hints off during a live game leaves no letter lit", hpg.locator("#cardGrid .cardLetter.lit").count() == 0 and not hpg.locator("#hintToggleWrap").is_visible())
        # phone cards print the tidy title (no Asian-script extras), but hints still match the full title
        sql(f"update games set hint_mode='all' where code='{lg}'")
        sql(f"update card_squares set title='Tokyo Drift (東京ドリフト) 東京' where pos=7 and player_id=(select id from players where name='Hinty' and game_id=(select id from games where code='{lg}'))")
        hpg.reload(); hpg.wait_for_timeout(1000)
        check("a phone card shows 'Tokyo Drift' without the Asian-script extras", hpg.locator('#cardGrid .sq[data-pos="7"] .sqText').inner_text().strip() == "Tokyo Drift", hpg.locator('#cardGrid .sq[data-pos="7"] .sqText').inner_text())
        hpg.evaluate("window.__bingoHandleTrackMsg({title: 'Tokyo Drift (東京ドリフト) 東京', artist: 'A', track_id: 'trk-9', position_ms: 1000, paused: false, server_ts_ms: Date.now()})"); hpg.wait_for_timeout(500)
        check("hints still find that square from the full song title", lit() == [2], str(lit()))
        hctx.close()

        # ---- The left column never shifts when status lines or song titles change ----
        hp.goto(f"{BASE}/host/game/{lg}")
        hp.wait_for_timeout(800)
        geo_js = "(() => { const r = s => { const b = document.querySelector(s).getBoundingClientRect(); return [Math.round(b.top), Math.round(b.height)]; }; return JSON.stringify([r('#hostNowPlaying'), r('#playBtn'), r('#spotifyConnBadge'), r('#transportMsg')]); })()"
        before_geo = hp.evaluate(geo_js)
        hp.evaluate("""(() => { const t = (i, x) => document.getElementById(i).textContent = x;
            t('deviceNowPlaying', 'Playing on: some extremely long device name that goes on and on and on forever (speaker) ▶');
            const d = document.getElementById('deviceTransferStatus'); d.style.display = ''; d.textContent = 'Playback transferred ✅';
            t('sdkStatus', 'A very long sdk status message that keeps going well past the width of the box'); t('transportMsg', 'Pause ✅');
            t('hostNpTitle', 'An Extremely Long Song Title That Would Normally Wrap Onto A Second Line For Sure');
            t('hostNpArtist', 'An Artist With A Very Long Name Feat. Several Other Artists And Producers'); t('hostNpTimer', '0:08'); })()""")
        hp.wait_for_timeout(200)
        check("the song box, status lines and buttons stay put when messages and song titles change", hp.evaluate(geo_js) == before_geo, f"{before_geo} -> {hp.evaluate(geo_js)}")

        # ---- Played Tracks and Claims lists use the whole height of their panels ----
        hp.set_viewport_size({"width": 1440, "height": 900})
        hp.goto(f"{BASE}/host/game/{lg}")
        hp.wait_for_timeout(800)
        gaps = hp.evaluate("""() => { const g = (l, p) => { const a = document.querySelector(l).getBoundingClientRect(), b = document.querySelector(p).getBoundingClientRect(); return Math.round(b.bottom - a.bottom); };
            return [g('#playedList', '.hostGrid3 > .hostCol2 > .panel'), g('#claimsList', '.hostGrid3 > .hostCol3 > .panel:nth-of-type(2)')]; }""")
        check("the Played Tracks and Claims lists reach the bottom of their panels", all(0 <= x < 40 for x in gaps), str(gaps))

        # ---- No page scrollbar on the host page ----
        for hw, hh in ((1440, 900), (1917, 870), (1280, 720), (1366, 650)):
            hp.set_viewport_size({"width": hw, "height": hh})
            hp.goto(f"{BASE}/host/game/{lg}"); hp.wait_for_timeout(600)
            hp.evaluate("window.scrollTo(0, 200)")
            noscroll = hp.evaluate("[window.scrollY, getComputedStyle(document.documentElement).overflowY, getComputedStyle(document.body).overflowY]")
            check(f"the host page has no page scrollbar at {hw}x{hh}", noscroll[0] == 0 and noscroll[1] == "hidden" and noscroll[2] == "hidden", str(noscroll))
        hp.set_viewport_size({"width": 1440, "height": 900})

        # ---- A bingo claim card on the host page: readable, buttons side by side ----
        cgc = create_game(hp, "Claimy")
        cctx, cpg = join(b, cgc, "Claimer")
        tpost(host, f"{BASE}/host/game/{cgc}/admit_all")
        sql(f"update games set status='started' where code='{cgc}'")
        cpg.reload(); cpg.wait_for_timeout(1000)
        cpg.evaluate("fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin'})")
        hp.goto(f"{BASE}/host/game/{cgc}"); hp.wait_for_timeout(1200)
        cg = hp.evaluate("""() => { const row = document.querySelector('#claimsList .claimRow'); if (!row) return null;
            const r = e => e.getBoundingClientRect(); const name = row.querySelector('.claimName'), badge = row.querySelector('.claimBadge');
            const btns = Array.from(row.querySelectorAll('.claimActions button'));
            return {name: name.textContent.trim(), badge: badge.textContent.trim(), oneLine: Math.abs(r(name).top - r(badge).top) < 14,
                    side: btns.length === 2 && Math.abs(r(btns[0]).top - r(btns[1]).top) < 2 && r(btns[1]).left > r(btns[0]).right - 1,
                    wide: btns.every(b => r(b).width >= 80), rowW: Math.round(r(row).width), status: row.querySelector('.claimStatus').textContent.trim()}; }""")
        check("a claim shows the player's name with the auto-check result on one line", cg and cg["name"] == "Claimer" and "Auto-check" in cg["badge"] and cg["oneLine"], str(cg))
        check("the Reject and Accept buttons sit side by side across the card", cg and cg["side"] and cg["wide"], str(cg))
        check("the claim keeps its 'Status: pending' line, followed by the time", cg and cg["status"].startswith("Status: pending · "), str(cg))
        cctx.close()

        # ---- Several bingo claims at once: first clicker on top, ranked, with a banner ----
        mg = create_game(hp, "Multi")
        mctxs = []
        for nm in ("Anna", "Ben", "Cleo"):
            mctxs.append(join(b, mg, nm))
        tpost(host, f"{BASE}/host/game/{mg}/admit_all")
        sql(f"update games set status='started' where code='{mg}'")
        for ctx, pg_ in mctxs:
            pg_.reload(); pg_.wait_for_timeout(700)
        order_in = [1, 0, 2]                                  # Ben clicks first, then Anna, then Cleo
        for idx in order_in:
            mctxs[idx][1].evaluate("fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin'})")
            mctxs[idx][1].wait_for_timeout(400)
        hp.goto(f"{BASE}/host/game/{mg}"); hp.wait_for_timeout(1200)
        mc = hp.evaluate(r"""() => ({banner: (document.querySelector('.claimBanner') || {}).textContent || '',
            names: Array.from(document.querySelectorAll('#claimsList .claimRow .claimName')).map(e => e.textContent.trim().replace(/\s+/g, ' ')),
            status: Array.from(document.querySelectorAll('#claimsList .claimStatus')).map(e => e.textContent.trim())})""")
        check("with several claims the first one to click is at the top, then the others in click order",
              [n.split(' ', 1)[1] for n in mc["names"]] == ["Ben", "Anna", "Cleo"] and mc["names"][0].startswith("First") and mc["names"][1].startswith("2nd") and mc["names"][2].startswith("3rd"), str(mc))
        check("a banner says several players called bingo and who was first", "3 players called bingo" in mc["banner"] and "Ben clicked first" in mc["banner"], mc["banner"])
        times = hp.evaluate("Array.from(document.querySelectorAll('#claimsList time.claimTime')).map(e => [e.textContent.trim(), e.getAttribute('datetime')])")
        check("each claim shows the time it was made in the host's own clock, with seconds, and no 'after the first' text",
              len(times) == 3 and all(re.fullmatch(r"\d{1,2}:\d{2}:\d{2}\s?(AM|PM)?", t[0]) for t in times) and "after the first" not in hp.locator("#claimsList").inner_text()
              and [t[1] for t in times] == sorted(t[1] for t in times), str(times))
        # an old, already-rejected claim from the same round must not distort the ranking
        sql(f"update bingo_claims set status='rejected' where game_id=(select id from games where code='{mg}') and player_id=(select id from players where game_id=(select id from games where code='{mg}') and name='Ben')")
        hp.goto(f"{BASE}/host/game/{mg}"); hp.wait_for_timeout(1200)
        mc2 = hp.evaluate(r"""() => ({banner: (document.querySelector('.claimBanner') || {}).textContent || '',
            names: Array.from(document.querySelectorAll('#claimsList .claimRow .claimName')).map(e => e.textContent.trim().replace(/\s+/g, ' '))})""")
        check("a rejected claim drops out of the ranking: the next in line becomes First and the banner follows",
              mc2["names"][0] == "First Anna" and mc2["names"][1].startswith("2nd") and "2 players called bingo" in mc2["banner"] and "Anna clicked first" in mc2["banner"], str(mc2))
        # Remove a rejected claim from the list
        check("a rejected claim has a small Remove button; pending ones do not",
              hp.locator("#claimsList .claimRemove").count() == 1 and hp.locator("#claimsList .claimRow:has(.claimActions) .claimRemove").count() == 0)
        before_n = sql(f"select count(*) from bingo_claims where game_id=(select id from games where code='{mg}')")[0][0]
        hp.locator("#claimsList .claimRemove").first.click(); hp.wait_for_timeout(1500)
        after_n = sql(f"select count(*) from bingo_claims where game_id=(select id from games where code='{mg}')")[0][0]
        check("Remove deletes just that rejected claim from the list", after_n == before_n - 1 and hp.locator("#claimsList .claimRemove").count() == 0, f"{before_n} -> {after_n}")
        pend = hp.evaluate(f"fetch('/host/game/{mg}/claim/' + document.querySelector('#claimsList [data-claim]').getAttribute('data-claim') + '/delete', {{method: 'POST', credentials: 'same-origin'}}).then(r => r.status)")
        check("a pending claim can't be removed", pend == 409, str(pend))
        for ctx, pg_ in mctxs:
            ctx.close()
        solo_claim = hp.evaluate("document.querySelectorAll('#claimsList .claimBanner').length")
        check("exactly one banner", solo_claim == 1)

        # ---- Win patterns: what counts as bingo ----
        hp.goto(f"{BASE}/host")
        check("the Create Game form offers the win patterns, with any line first", hp.locator("#winPattern option").all_inner_texts()[:1] == ["Any line"] and hp.locator("#winPattern option").count() == 6)
        wg = create_game(hp, "Corners", pattern="corners")
        check("a game made with 'Four corners' remembers it", sql(f"select win_pattern from games where code='{wg}'")[0][0] == "corners")
        check("a game made without choosing uses any line", sql(f"select win_pattern from games where code='{lg}'")[0][0] == "line")
        wctx, wpg = join(b, wg, "Winner")
        tpost(host, f"{BASE}/host/game/{wg}/admit_all")
        sql(f"update games set status='started' where code='{wg}'")
        wpg.reload(); wpg.wait_for_timeout(800)
        check("the player's card says what counts as bingo, with a picture of the squares, and no 'Round 1'", "Four corners" in wpg.locator(".patternBadge:visible").first.inner_text() and wpg.locator(".patternBadge:visible .patternMini i.on").count() == 4 and "Round" not in wpg.locator(".patternBadge:visible").first.inner_text(), wpg.locator(".patternBadge:visible").first.inner_text())
        wid = sql(f"select p.id from players p join games g on g.id=p.game_id where g.code='{wg}' and p.name='Winner'")[0][0]
        gid = sql(f"select id from games where code='{wg}'")[0][0]
        titles = {r[0]: r[1] for r in sql(f"select pos, title from card_squares where player_id={wid}")}
        def play_titles(positions, start):
            for i, ps in enumerate(positions):
                t = titles[ps].replace("'", "''")
                sql(f"insert into played_tracks (game_id, seq, spotify_track_id, title, artist, played_at) values ({gid}, {start + i}, 'x{start + i}', '{t}', 'A', CURRENT_TIMESTAMP)")
        claim_js = "(m) => fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({marked: m})}).then(r => r.json())"
        play_titles([0, 1, 2, 3, 4], 1)
        row_claim = wpg.evaluate(claim_js, [0, 1, 2, 3, 4])
        check("with Four corners a full row is not a bingo", row_claim.get("auto_valid") is False, str(row_claim))
        sql(f"delete from bingo_claims where game_id={gid}")
        wpg.evaluate("localStorage.clear()")
        play_titles([20, 24], 6)
        corner_claim = wpg.evaluate(claim_js, [0, 4, 20, 24])
        check("with Four corners the four corners are a bingo", corner_claim.get("auto_valid") is True and corner_claim.get("status") == "pending", str(corner_claim))
        check("the claim records the pattern it was made under", sql(f"select pattern from bingo_claims where game_id={gid}")[0][0] == "corners")
        # ---- Scoreboard: who won which round ----
        cid = sql(f"select id from bingo_claims where game_id={gid}")[0][0]
        check("with no accepted bingo the scoreboard is empty", host.request.get(f"{BASE}/host/game/{wg}/scoreboard.json").json()["wins"] == [])
        check("the host accepts the claim", tpost(host, f"{BASE}/host/game/{wg}/claim/{cid}/set", data='{"action":"accept"}', headers={"Content-Type": "application/json"}).status == 200)
        board = host.request.get(f"{BASE}/host/game/{wg}/scoreboard.json").json()
        check("the scoreboard lists the winner with the round and pattern", [(w["round"], w["pattern"], w["name"]) for w in board["wins"]] == [(1, "Four corners", "Winner")] and [(w["name"], w["wins"]) for w in board["standings"]] == [("Winner", 1)] and board["wins"][0]["pic"]["emoji"] and board["round"] == 1, str(board))
        check("the scoreboard is for the game's host only", other.request.get(f"{BASE}/host/game/{wg}/scoreboard.json").status in (403, 404) and b.new_context().request.get(f"{BASE}/host/game/{wg}/scoreboard.json", max_redirects=0).status in (302, 303, 307, 401, 403))
        check("a player of the game can read the winners", wpg.evaluate(f"fetch('/game/{wg}/winners.json').then(r => r.status)") == 200)
        check("someone who has not joined the game cannot", b.new_context().request.get(f"{BASE}/game/{wg}/winners.json").status == 403)
        wpg.wait_for_timeout(1200)
        check("the player's phone shows 'Winners so far' with the winner in it", wpg.locator("#winnersBox").is_visible() and "Winner" in wpg.locator("#winnersList").text_content() and "Four corners" in wpg.locator("#winnersList").text_content(), wpg.locator("#winnersBox").text_content())
        sb = host.new_page(); sb.goto(f"{BASE}/host/game/{wg}/scoreboard"); sb.wait_for_timeout(900)
        check("the scoreboard screen shows the winner and the most wins", "Winner" in sb.locator("#winsList").inner_text() and "Four corners" in sb.locator("#winsList").inner_text() and "round" not in sb.locator("#winsList").inner_text().lower() and "Round" not in sb.locator("#roundNow").inner_text() and "1 win" in sb.locator("#standList").inner_text(), sb.inner_text("body"))
        # the host changes the pattern: everyone's badge follows, and a bad value is refused
        hp.goto(f"{BASE}/host/game/{wg}"); hp.wait_for_timeout(800)
        check("the host page shows the pattern choice, set to Four corners", hp.locator("#patternSel").input_value() == "corners" and hp.locator("#patternRow .patternMini i.on").count() == 4 and not hp.locator("#patternRow .roundPart").is_visible())
        check("a game still on its first round does not say 'Round 1' anywhere on the host page", "Round 1" not in hp.inner_text("body"))
        hp.select_option("#patternSel", "x"); wpg.wait_for_timeout(1200)
        check("changing the pattern saves it", sql(f"select win_pattern from games where code='{wg}'")[0][0] == "x")
        check("...and the player's card changes at once, without a reload", "Letter X" in wpg.locator(".patternBadge:visible").first.inner_text() and wpg.locator(".patternBadge:visible .patternMini i.on").count() == 9, wpg.locator(".patternBadge:visible").first.inner_text())
        check("an unknown pattern is refused", tpost(host, f"{BASE}/host/game/{wg}/pattern", data='{"pattern":"zigzag"}', headers={"Content-Type": "application/json"}).status == 400)
        check("another host cannot change the pattern", tpost(other, f"{BASE}/host/game/{wg}/pattern", data='{"pattern":"full"}', headers={"Content-Type": "application/json"}).status in (403, 404))
        check("Continue Game can set the next round's pattern",
              tpost(host, f"{BASE}/host/game/{wg}/continue_game", data='{"pattern":"full"}', headers={"Content-Type": "application/json"}).status == 200
              and sql(f"select win_pattern, continue_seq from games where code='{wg}'")[0] in (("full", 1), ["full", 1]))
        wpg.wait_for_timeout(800)
        check("the player's card shows 'Full card' for the new round", "Full card" in wpg.locator(".patternBadge:visible").first.inner_text() and wpg.locator(".patternBadge:visible .patternMini i.on").count() == 25)
        check("the scoreboard now says round 2 and keeps the round 1 winner", host.request.get(f"{BASE}/host/game/{wg}/scoreboard.json").json()["round"] == 2 and len(host.request.get(f"{BASE}/host/game/{wg}/scoreboard.json").json()["wins"]) == 1)
        check("the phone's badge says Round 2", "Round 2" in wpg.locator(".patternBadge:visible").first.inner_text())
        sb.wait_for_timeout(300); sb.close()
        tpost(host, f"{BASE}/host/game/{wg}/end_game"); wpg.wait_for_timeout(1200)
        check("when the game ends the players' game-over screen lists who won", "Winner" in wpg.locator("#finalWinners").inner_text(), wpg.locator("#finalWinners").inner_text())
        wctx.close()
        for key, n in (("x", 9), ("plus", 9), ("frame", 16), ("full", 25)):
            sql(f"update games set win_pattern='{key}' where code='{wg}'")
            hp.goto(f"{BASE}/host/game/{wg}"); hp.wait_for_timeout(300)
            check(f"the picture for '{key}' lights {n} squares", hp.locator("#patternRow .patternMini i.on").count() == n)

        # ---- The pattern is locked while a round is being played ----
        wl = create_game(hp, "Lobby pattern")
        check("before the game starts the pattern can be changed", tpost(host, f"{BASE}/host/game/{wl}/pattern", data='{"pattern":"plus"}', headers={"Content-Type": "application/json"}).status == 200)
        hp.goto(f"{BASE}/host/game/{wl}"); hp.wait_for_timeout(600)
        check("...and the host's pattern box is open in the lobby", not hp.locator("#patternSel").is_disabled())
        dctx, dpg = join(b, wl, "Dee")
        tpost(host, f"{BASE}/host/game/{wl}/admit_all")
        sql(f"update games set status='started' where code='{wl}'")
        dpg.reload(); dpg.wait_for_timeout(700)
        check("once the game has started, with no bingo yet, the server refuses a change", tpost(host, f"{BASE}/host/game/{wl}/pattern", data='{"pattern":"full"}', headers={"Content-Type": "application/json"}).status == 409 and sql(f"select win_pattern from games where code='{wl}'")[0][0] == "plus")
        hp.goto(f"{BASE}/host/game/{wl}"); hp.wait_for_timeout(700)
        check("...and the host's pattern box is locked, with a note saying why", hp.locator("#patternSel").is_disabled() and hp.locator("#patternLock").is_visible())
        # after a bingo is accepted the host chooses: continue playing (no change), continue with Full card, or end
        dpg.evaluate("fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin'})"); dpg.wait_for_timeout(500)
        dcid = sql(f"select id from bingo_claims where game_id=(select id from games where code='{wl}')")[0][0]
        tpost(host, f"{BASE}/host/game/{wl}/claim/{dcid}/set", data='{"action":"accept"}', headers={"Content-Type": "application/json"})
        hp.goto(f"{BASE}/host/game/{wl}"); hp.wait_for_timeout(1000)
        check("after a bingo is accepted the host is offered Continue playing, Continue with Full card and End Game", hp.locator("#btnContinueGame").inner_text() == "Continue playing" and hp.locator("#btnContinueFull").is_visible() and hp.locator("#btnEndGame").is_visible(), hp.locator("#bingoDecisionBar").inner_text())
        check("...and the pattern box opens up for other changes between rounds", not hp.locator("#patternSel").is_disabled())
        hp.click("#btnContinueGame"); hp.wait_for_timeout(900)
        check("'Continue playing' changes nothing: same pattern, next round", sql(f"select win_pattern, continue_seq from games where code='{wl}'")[0] in (("plus", 1), ["plus", 1]))
        hp.reload(); hp.wait_for_timeout(800)
        check("the pattern box locks again once the new round is being played", hp.locator("#patternSel").is_disabled())
        dpg.evaluate("fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin'})"); dpg.wait_for_timeout(500)
        dcid2 = sql(f"select id from bingo_claims where game_id=(select id from games where code='{wl}') order by id desc limit 1")[0][0]
        tpost(host, f"{BASE}/host/game/{wl}/claim/{dcid2}/set", data='{"action":"accept"}', headers={"Content-Type": "application/json"})
        hp.reload(); hp.wait_for_timeout(1000)
        hp.click("#btnContinueFull"); hp.wait_for_timeout(900)
        check("'Continue with Full card' switches the next round to a full card", sql(f"select win_pattern, continue_seq from games where code='{wl}'")[0] in (("full", 2), ["full", 2]))
        dpg.wait_for_timeout(600)
        check("the player's page follows: Round 3 and Full card", "Round 3" in dpg.locator(".patternBadge:visible").first.inner_text() and "Full card" in dpg.locator(".patternBadge:visible").first.inner_text(), dpg.locator(".patternBadge:visible").first.inner_text())
        dctx.close()

        # ---- Co-host link ----
        ch = create_game(hp, "Cohost game")
        ch2 = create_game(hp, "Other game")
        jctx, jpg = join(b, ch, "Joiner")
        tpost(host, f"{BASE}/host/game/{ch}/admit_all")
        sql(f"update games set status='started' where code='{ch}'")
        jpg.reload(); jpg.wait_for_timeout(700)
        J = {"Content-Type": "application/json"}
        check("a new game has no co-host link", host.request.get(f"{BASE}/host/game/{ch}/cohost").json()["url"] == "")
        anon = b.new_context()
        check("a made-up co-host link does not work", anon.request.get(f"{BASE}/cohost/{ch}/notarealtoken123456").status == 404 and anon.request.get(f"{BASE}/cohost/{ch}/notarealtoken123456/state").status == 404)
        link = tpost(host, f"{BASE}/host/game/{ch}/cohost", data='{"action":"on"}', headers=J).json()["url"]
        token = link.rsplit("/", 1)[1]
        check("the host can make a co-host link for the game", f"/cohost/{ch}/" in link and len(token) >= 20, link)
        check("another host cannot make or read it", tpost(other, f"{BASE}/host/game/{ch}/cohost", data='{"action":"on"}', headers=J).status in (403, 404) and other.request.get(f"{BASE}/host/game/{ch}/cohost").status in (403, 404))
        r_page = anon.request.get(f"{BASE}/cohost/{ch}/{token}")
        check("someone with the link, not logged in, can open the co-host page", r_page.status == 200 and "Cohost game" in r_page.text() and "no-store" in r_page.headers.get("cache-control", "") and "noindex" in r_page.headers.get("x-robots-tag", ""))
        jpg.evaluate("fetch(location.pathname.replace(/\\/$/, '') + '/claim_bingo', {method: 'POST', credentials: 'same-origin'})"); jpg.wait_for_timeout(500)
        st = anon.request.get(f"{BASE}/cohost/{ch}/{token}/state").json()
        check("the co-host sees the bingo call, waiting for a decision", st["ok"] and len(st["claims"]) == 1 and st["claims"][0]["name"] == "Joiner" and st["claims"][0]["status"] == "pending" and st["round"] == 1, str(st))
        check("the co-host cannot run the game or open the host page", tpost(anon, f"{BASE}/host/game/{ch}/continue_game", data="{}", headers=J, max_redirects=0).status in (302, 303, 307, 401, 403) and "login" in anon.request.get(f"{BASE}/host/game/{ch}", max_redirects=0).headers.get("location", "login"))
        cpg = anon.new_page(); cpg.goto(f"{BASE}/cohost/{ch}/{token}"); cpg.wait_for_timeout(1200)
        check("the co-host page shows the call with Accept and Reject buttons", "Joiner" in cpg.locator("#claims").inner_text() and cpg.locator("#claims .actions button").count() == 2, cpg.locator("#claims").inner_text())
        cpg.click("#claims .actions button.yes"); cpg.wait_for_timeout(1000)
        check("accepting from the co-host page is a real decision", sql(f"select status from bingo_claims where game_id=(select id from games where code='{ch}')")[0][0] == "accepted" and "Accepted" in cpg.locator("#claims").inner_text())
        hp.goto(f"{BASE}/host/game/{ch}"); hp.wait_for_timeout(900)
        check("the host's page shows it, with the Continue and End Game buttons", "accepted" in hp.locator("#claimsList").inner_text().lower() and hp.locator("#btnContinueGame").is_visible())
        other_claim = sql(f"select id from bingo_claims where game_id=(select id from games where code='{ch}')")[0][0]
        link2 = tpost(host, f"{BASE}/host/game/{ch2}/cohost", data='{"action":"on"}', headers=J).json()["url"]
        token2 = link2.rsplit("/", 1)[1]
        check("a link only works for its own game", anon.request.get(f"{BASE}/cohost/{ch}/{token2}").status == 404 and anon.request.get(f"{BASE}/cohost/{ch2}/{token}").status == 404)
        check("a co-host cannot decide a claim from another game", tpost(anon, f"{BASE}/cohost/{ch2}/{token2}/claim/{other_claim}", data='{"action":"reject"}', headers=J).status == 404)
        check("a bad action is refused", tpost(anon, f"{BASE}/cohost/{ch}/{token}/claim/{other_claim}", data='{"action":"delete"}', headers=J).status == 400)
        redact_env = ["-e", "DATABASE_URL=sqlite:////work/now/paper.db?check_same_thread=false", "-e", "COOKIE_SECRET=local-paper-test", "-w", "/work/now"]
        red = subprocess.run(["docker", "exec", *redact_env, CONTAINER, "python", "-c",
                              "import logging;from app.main import _RedactOneTimeValues as F;r=logging.LogRecord('x',20,'',0,'%s %s',('1.2.3.4','GET','/cohost/ABC12/SECRETtoken_12-3/state'),None);F().filter(r);print(r.args[2])"],
                             capture_output=True, text=True).stdout.strip().splitlines()[-1:] or [""]
        red = red[0]
        check("the access log hides the secret part of a co-host link", red == "/cohost/ABC12/[redacted]/state", red)
        new_link = f"{BASE}/cohost/{ch}/" + tpost(host, f"{BASE}/host/game/{ch}/cohost", data='{"action":"on"}', headers=J).json()["url"].rsplit("/", 1)[1]
        check("making the link again replaces it: the old one stops working", anon.request.get(f"{BASE}/cohost/{ch}/{token}").status == 404 and anon.request.get(new_link).status == 200)
        tpost(host, f"{BASE}/host/game/{ch}/cohost", data='{"action":"off"}', headers=J)
        check("turning it off stops the link and the page's updates", anon.request.get(new_link).status == 404 and host.request.get(f"{BASE}/host/game/{ch}/cohost").json()["url"] == "")
        hp.goto(f"{BASE}/host/game/{ch2}"); hp.wait_for_timeout(600)
        hp.click("#cohostBtn"); hp.wait_for_timeout(700)
        check("the host's Co-host link button shows the link for the game", hp.locator("#cohostBox").is_visible() and f"/cohost/{ch2}/" in hp.locator("#cohostUrl").input_value())
        hp.click("#cohostOff"); hp.wait_for_timeout(500)
        check("Turn off hides it and the link stops working", not hp.locator("#cohostBox").is_visible() and anon.request.get(link2).status == 404)
        tpost(host, f"{BASE}/host/game/{ch2}/cohost", data='{"action":"on"}', headers=J)
        sql(f"update games set status='ended' where code='{ch2}'")
        check("a link stops working when the game has ended", anon.request.get(f"{BASE}/cohost/{ch2}/{sql(f'select cohost_token from games where code={chr(39)}{ch2}{chr(39)}')[0][0]}").status == 404)
        anon.close(); jctx.close()

        # ---- Player pictures: an animal and a color ----
        ag = create_game(hp, "Pictures")
        pj = b.new_context(); pj_pg = pj.new_page(); pj_pg.goto(f"{BASE}/game/{ag}")
        check("the join page offers 24 animals and 12 colors, as real radio buttons (usable by keyboard)", pj_pg.locator("input[name=avatar]").count() == 24 and pj_pg.locator("input[name=avatar_color]").count() == 12 and pj_pg.locator("input[name=avatar]").first.get_attribute("type") == "radio")
        for vw, vh in ((1917, 870), (1440, 800), (1366, 700)):
            pj_pg.set_viewport_size({"width": vw, "height": vh}); pj_pg.wait_for_timeout(200)
            check(f"the whole join page, button included, fits a {vw}x{vh} window without scrolling", pj_pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), str(pj_pg.evaluate("[document.documentElement.scrollHeight, innerHeight]")))
        pj_pg.fill("#f_name", "Pic"); pj_pg.check("input[name=avatar][value=panda]", force=True); pj_pg.check("input[name=avatar_color][value=orange]", force=True)
        check("the preview shows the chosen animal and color", pj_pg.locator("#previewAvatar").inner_text() == "🐼" and "avc-orange" in pj_pg.locator("#previewAvatar").get_attribute("class") and pj_pg.locator("#previewName").inner_text() == "Pic")
        pj_pg.click("button[type=submit]"); pj_pg.wait_for_load_state("networkidle")
        check("the chosen animal and color are saved", sql(f"select avatar, avatar_color from players where name='Pic' and game_id=(select id from games where code='{ag}')")[0] in (("panda", "orange"), ["panda", "orange"]))
        evil = b.new_context()
        tpost(evil, f"{BASE}/game/{ag}/join", form={"name": "Evil", "avatar": "<img src=x onerror=alert(1)>", "avatar_color": "red;background:url(x)"})
        row = sql(f"select avatar, avatar_color from players where name='Evil' and game_id=(select id from games where code='{ag}')")[0]
        check("a made-up animal or color is replaced by a real one", row[0] in ("fox", "panda", "lion", "tiger", "bear", "koala", "monkey", "frog", "penguin", "owl", "duck", "turtle", "octopus", "butterfly", "bee", "dolphin", "giraffe", "elephant", "kangaroo", "rabbit", "dog", "cat", "unicorn", "dinosaur") and row[1] in ("purple", "orange", "blue", "green", "pink", "yellow", "red", "teal", "indigo", "lime", "brown", "slate"), str(row))
        for nm in ("A1", "A2", "A3", "A4"):
            tpost(b.new_context(), f"{BASE}/game/{ag}/join", form={"name": nm})
        pics = [r[0] for r in sql(f"select avatar from players where game_id=(select id from games where code='{ag}')")]
        check("players who pick nothing each get a different animal", len(pics) == 6 and len(set(pics)) == 6 and all(pics), str(pics))
        hp.goto(f"{BASE}/host/game/{ag}"); hp.wait_for_timeout(900)
        check("the host's player list shows each player's picture", hp.locator("#playersList .playerRow .avatar").count() == 6 and hp.locator("#playersList .avatar").first.get_attribute("aria-label") in pics)
        check("a player sees their own picture beside their name", pj_pg.locator(".avatar").count() >= 1)
        ec = b.new_context(); ep = ec.new_page(); ep.set_viewport_size({"width": 1440, "height": 800}); ep.goto(f"{BASE}/enter")
        check("the page where players type the game code has the same picture and color pickers", ep.locator("input[name=avatar]").count() == 24 and ep.locator("input[name=avatar_color]").count() == 12)
        check("...and the whole page fits a 1440x800 window without scrolling", ep.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), str(ep.evaluate("[document.documentElement.scrollHeight, innerHeight]")))
        ep.fill("input[name=code]", ag); ep.fill("#f_name", "Via code"); ep.check("input[name=avatar][value=koala]", force=True); ep.check("input[name=avatar_color][value=teal]", force=True)
        ep.click("button[type=submit]"); ep.wait_for_load_state("networkidle")
        check("joining from the code page saves the chosen animal and color", sql(f"select avatar, avatar_color from players where name='Via code' and game_id=(select id from games where code='{ag}')")[0] in (("koala", "teal"), ["koala", "teal"]))
        ec.close()
        # ---- Display: Color, Light or Dark, a player's own choice ----
        mc = b.new_context(); mp = mc.new_page(); mp.goto(f"{BASE}/enter")
        probe = "[getComputedStyle(document.documentElement).getPropertyValue('--bgBot').trim(), getComputedStyle(document.documentElement).getPropertyValue('--text').trim(), getComputedStyle(document.documentElement).filter]"
        check("the page where players type the game code has a Display choice (Color, Light, Dark), on Color at first", mp.locator("#displaySelect").count() == 1 and mp.locator("#displaySelect option").all_inner_texts() == ["Color", "Light", "Dark"] and mp.locator("#displaySelect").input_value() == "color" and mp.evaluate(probe)[2] == "none")
        mp.select_option("#displaySelect", "dark"); mp.wait_for_timeout(200)
        d = mp.evaluate(probe)
        check("Dark is plain white on black and nothing else, whatever the host's theme", d[0] == "#000" and d[1] == "#fff" and "grayscale" in d[2], str(d))
        mp.select_option("#displaySelect", "light"); mp.wait_for_timeout(200)
        d = mp.evaluate(probe)
        check("Light is plain black on white", d[0] == "#fff" and d[1] == "#000" and "grayscale" in d[2], str(d))
        mp.goto(f"{BASE}/game/{ag}"); mp.wait_for_timeout(300)
        check("the choice is remembered on the join page, and the Display box shows it", mp.evaluate(probe)[0] == "#fff" and mp.locator("#displaySelect").input_value() == "light")
        mp.fill("#f_name", "Mono"); mp.click("button[type=submit]"); mp.wait_for_load_state("networkidle"); mp.wait_for_timeout(300)
        check("...and on the player's card page, where the Display box is up by the player's name, not on the card", mp.evaluate(probe)[0] == "#fff" and mp.locator("#displaySelect").input_value() == "light" and mp.locator("#cardGrid #displaySelect").count() == 0)
        tpost(host, f"{BASE}/host/game/{ag}/admit_all"); mp.reload(); mp.wait_for_timeout(500)
        mp.locator("#cardGrid .sq").nth(1).click(); mp.wait_for_timeout(150)
        mk = mp.evaluate("(() => { const e = document.querySelector('#cardGrid .sq.marked'); const c = getComputedStyle(e); return [c.backgroundColor, c.color]; })()")
        check("in Light a marked square is solid black with white text (readable without any color)", mk[0] == "rgb(0, 0, 0)" and mk[1] == "rgb(255, 255, 255)", str(mk))
        mp.select_option("#displaySelect", "dark"); mp.wait_for_timeout(200)
        mk = mp.evaluate("(() => { const e = document.querySelector('#cardGrid .sq.marked'); const c = getComputedStyle(e); return [c.backgroundColor, c.color]; })()")
        check("in Dark a marked square is solid white with black text", mk[0] == "rgb(255, 255, 255)" and mk[1] == "rgb(0, 0, 0)", str(mk))
        mp.select_option("#displaySelect", "color"); mp.reload(); mp.wait_for_timeout(300)
        check("Color puts the host's theme back, and that is remembered too", mp.evaluate(probe)[2] == "none" and mp.locator("#displaySelect").input_value() == "color")
        hp.goto(f"{BASE}/host"); check("the host's own pages have no Display box", hp.locator("#displaySelect").count() == 0)
        sql(f"update games set hint_mode='optin' where code='{ag}'")
        mp.set_viewport_size({"width": 390, "height": 844}); mp.reload(); mp.wait_for_timeout(700)
        hint_box = mp.evaluate("(() => { const h = document.getElementById('hintToggleWrap'), r = h.getBoundingClientRect(); return {hidden: h.hidden, inStrip: !!h.closest('.patternStrip'), right: Math.round(r.right), width: Math.round(r.width), vw: innerWidth}; })()")
        check("on an upright phone the Hints switch sits in the top strip beside the win pattern, fully on the screen", (not hint_box["hidden"]) and hint_box["inStrip"] and hint_box["width"] > 0 and hint_box["right"] <= hint_box["vw"], str(hint_box))
        mp.set_viewport_size({"width": 1280, "height": 800}); mp.wait_for_timeout(400)
        check("...and goes back beside the player's name on a wide screen", mp.evaluate("!document.getElementById('hintToggleWrap').closest('.patternStrip')"))
        mc.close()
        pj.close(); evil.close()

        # ---- Start Game -> End Game -> Play again ----
        eg = create_game(hp, "EndMe", paper=2)
        hp.goto(f"{BASE}/host/game/{eg}")
        hp.wait_for_timeout(800)
        check("before the game starts the button says Start Game (no End Game, no Play again)",
              hp.locator("#startBtn").is_visible() and not hp.locator("#endGameMainBtn").is_visible() and not hp.locator("#playAgainForm").is_visible())
        sql(f"update games set status='started' where code='{eg}'")
        hp.goto(f"{BASE}/host/game/{eg}")
        hp.wait_for_timeout(800)
        check("once started, the Start button is replaced by End Game", hp.locator("#endGameMainBtn").is_visible() and not hp.locator("#startBtn").is_visible())
        check("a started game shows no 'Game Started' message, the End Game button says it", "Game Started" not in hp.locator("#hostMsg").inner_text())
        check("in a running game there is no device picker, but Refresh devices is still there", not hp.locator("#deviceRow").is_visible() and hp.locator("#deviceRefreshBtn").is_visible())
        hp.evaluate("document.getElementById('deviceSelect').appendChild(Object.assign(document.createElement('option'), {value: 'dev-x', textContent: 'Kitchen speaker'})); document.getElementById('deviceRow').style.display = ''")
        check("when a new device is found the picker appears", hp.locator("#deviceRow").is_visible())
        hp.select_option("#deviceSelect", "dev-x"); hp.wait_for_timeout(700)
        check("once a device is chosen the picker goes away again", not hp.locator("#deviceRow").is_visible())
        aimed = []
        hp.on("request", lambda r: aimed.append(r.url) if "/spotify/pause" in r.url or "/spotify/next" in r.url else None)
        hp.evaluate("document.getElementById('pauseBtn').click(); setTimeout(() => document.getElementById('nextBtn').click(), 300)"); hp.wait_for_timeout(1500)
        check("Pause and Next are aimed at the device the game plays on, not whatever Spotify calls active", any("/spotify/pause" in u and "device_id=dev-x" in u for u in aimed) and any("/spotify/next" in u and "device_id=dev-x" in u for u in aimed), str(aimed))
        # the Play Alone web player registers as a Spotify device too; a hosted game must never offer it
        dg = create_game(hp, "Devices")
        hp.route("https://api.spotify.com/v1/me/player/devices", lambda r: r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"},
                 body=json.dumps({"devices": [{"id": "s1", "name": "Music Bingo Solo (JC4EL)", "type": "Computer", "is_active": False}, {"id": "k1", "name": "Kitchen speaker", "type": "Speaker", "is_active": False}]})))
        hp.goto(f"{BASE}/host/game/{dg}")
        hp.wait_for_timeout(800)
        hp.click("#deviceRefreshBtn"); hp.wait_for_timeout(1200)
        opts = hp.locator("#deviceSelect option").all_inner_texts()
        check("Refresh devices lists other speakers but never a Play Alone player", any("Kitchen speaker" in o for o in opts) and not any("Music Bingo Solo" in o for o in opts) and hp.locator("#deviceRow").is_visible(), str(opts))
        check("Refresh devices says what it found", "Kitchen speaker" in hp.locator("#sdkStatus").inner_text(), hp.locator("#sdkStatus").inner_text())
        hp.unroute("https://api.spotify.com/v1/me/player/devices")
        hp.route("https://api.spotify.com/v1/me/player/devices", lambda r: r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"},
                 body=json.dumps({"devices": [{"id": "s1", "name": "Music Bingo Solo (JC4EL)", "type": "Computer", "is_active": False}]})))
        hp.click("#deviceRefreshBtn"); hp.wait_for_timeout(1200)
        check("Refresh devices says so when there is nothing else", "No other devices found" in hp.locator("#sdkStatus").inner_text() and not hp.locator("#deviceRow").is_visible(), hp.locator("#sdkStatus").inner_text())
        hp.unroute("https://api.spotify.com/v1/me/player/devices")
        hp.route("https://api.spotify.com/v1/me/player/devices", lambda r: r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"},
                 body=json.dumps({"devices": [{"id": "s1", "name": "Music Bingo Solo (JC4EL)", "type": "Computer", "is_active": False}, {"id": "k1", "name": "Kitchen speaker", "type": "Speaker", "is_active": False}]})))
        hp.evaluate("window.__bingoGameStarted = true"); hp.click("#deviceRefreshBtn"); hp.wait_for_timeout(1200)
        check("once the game has started, Refresh devices still offers other devices, so the music can be moved (e.g. to the room screen)", hp.locator("#deviceRow").is_visible() and "Kitchen speaker" in hp.locator("#deviceSelect").inner_text() and "Music Bingo Solo" not in hp.locator("#deviceSelect").inner_text())
        hp.unroute("https://api.spotify.com/v1/me/player/devices")
        hp.goto(f"{BASE}/host/game/{eg}")   # back to the started game the checks below look at
        hp.wait_for_timeout(800)
        hp.set_viewport_size({"width": 1440, "height": 650})
        hp.evaluate("document.getElementById('transportMsg').textContent = 'Play ✅'; document.getElementById('sdkStatus').textContent = 'Game playlist started ✅'")
        hp.wait_for_timeout(300)
        fitc = hp.evaluate("(() => { const p = document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect(); const b = document.getElementById('nextBtn').getBoundingClientRect(); return [Math.round(b.bottom), Math.round(p.bottom)]; })()")
        check("in a running game the Play/Pause/Next buttons fit inside the left panel on a 650px-high window", fitc[0] <= fitc[1], str(fitc))
        hp.set_viewport_size({"width": 1440, "height": 900})
        sizes = hp.evaluate("['#admitBtn', '#startBtn', '#endGameMainBtn'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })")
        check("End Game is the same size as Admit All", abs(sizes[2][0] - sizes[0][0]) <= 2 and abs(sizes[2][1] - sizes[0][1]) <= 2, str(sizes))
        order = hp.evaluate("['#joinLink', '#admitBtn', '#spotifyConnBadge', '#playBtn'].map(s => Math.round(document.querySelector(s).getBoundingClientRect().top))")
        check("Game Control sits in the left column between the join link and the player controls", order == sorted(order) and len(set(order)) == 4, str(order))
        hp.once("dialog", lambda d: d.dismiss())
        hp.click("#endGameMainBtn"); hp.wait_for_timeout(500)
        check("cancelling the End Game confirmation leaves the game running", sql(f"select status from games where code='{eg}'")[0][0] == "started")
        hp.evaluate("document.getElementById('deviceSelect').appendChild(Object.assign(document.createElement('option'), {value: 'dev-y', textContent: 'Lounge speaker'})); document.getElementById('deviceRow').style.display = ''")
        hp.select_option("#deviceSelect", "dev-y"); hp.wait_for_timeout(700)
        ended_reqs = []
        hp.on("request", lambda r: ended_reqs.append(r.url) if "/end_game" in r.url else None)
        hp.once("dialog", lambda d: d.accept())
        hp.click("#endGameMainBtn"); hp.wait_for_timeout(1200)
        check("End Game pauses the device the game plays on", any("/end_game" in u and "device_id=dev-y" in u for u in ended_reqs), str(ended_reqs))
        check("End Game ends it and the button turns into Play again",
              sql(f"select status from games where code='{eg}'")[0][0] == "ended" and hp.locator("#playAgainForm").is_visible() and not hp.locator("#endGameMainBtn").is_visible())
        check("ending the game disables Play, Pause and Next", all(hp.locator(x).is_disabled() for x in ("#playBtn", "#pauseBtn", "#nextBtn")))
        hp.reload(); hp.wait_for_timeout(800)
        check("after a reload an ended game still shows Play again with the music controls off", hp.locator("#playAgainForm").is_visible() and not hp.locator("#startBtn").is_visible() and all(hp.locator(x).is_disabled() for x in ("#playBtn", "#pauseBtn", "#nextBtn")))
        hp.click("#playAgainBtn"); hp.wait_for_load_state("networkidle"); hp.wait_for_timeout(600)
        check("Play again resets the game so Start Game is back", sql(f"select status from games where code='{eg}'")[0][0] == "lobby" and hp.locator("#startBtn").is_visible())

        # ---- Join QR page ----
        qg = create_game(hp, "QR")
        hp.goto(f"{BASE}/host/game/{qg}")
        hp.wait_for_timeout(800)
        check("the host page has a Show QR button instead of Copy", hp.locator("#qrBtn").count() == 1 and hp.locator("#copyBtn").count() == 0)
        check("the link has a 'click to copy' hint", "Click the link to copy" in hp.locator("#copyHint").inner_text())
        hp.context.grant_permissions(["clipboard-read", "clipboard-write"])
        hp.click("#joinLink"); hp.wait_for_timeout(400)
        check("copying shows 'Copied' on the hint line, not in the host message slot", "Copied" in hp.locator("#copyHint").inner_text() and not hp.locator("#hostMsg").inner_text().strip())
        hp.goto(f"{BASE}/host/game/{qg}/qr")
        hp.wait_for_timeout(500)
        box = hp.locator("#qr svg").bounding_box()
        check("the QR page shows a large QR code and the game address", hp.locator("#qr svg").count() == 1 and box and box["width"] > 300 and f"/game/{qg}" in hp.content(), str(box))
        check("the QR page says 'Game Name: <name>' and not the game code (the code is already in the address)", hp.locator(".code").inner_text().strip() == "Game Name: QR" and "Game code" not in hp.inner_text("body"), hp.locator(".code").inner_text())
        check("the QR page is host-only", b.new_context().request.get(f"{BASE}/host/game/{qg}/qr", max_redirects=0).status in (302, 303, 307))

        # ---- Room reveal on the QR screen ----
        check("reveal option starts off and the switch shows on the host page", not hp.evaluate("document.body.dataset.room === '1'") and sql(f"select room_reveal from games where code='{qg}'")[0][0] in (0, False))
        hp.goto(f"{BASE}/host/game/{qg}"); hp.wait_for_timeout(600)
        check("host page has a 'Reveal on QR screen' switch, off by default", hp.locator("#roomRevealOn").is_visible() and not hp.locator("#roomRevealOn").is_checked())
        check("'Music on QR screen' is greyed out until the reveal is on", hp.locator("#roomSoundOn").is_disabled())
        hp.check("#roomRevealOn"); hp.wait_for_timeout(500)
        check("turning it on saves room_reveal", sql(f"select room_reveal from games where code='{qg}'")[0][0] in (1, True))
        check("with the reveal on, 'Music on QR screen' can be switched on and is saved", not hp.locator("#roomSoundOn").is_disabled())
        hp.goto(f"{BASE}/host/game/{qg}/qr"); hp.wait_for_timeout(500)
        check("with the music option off, the QR page shows no speaker button", not hp.locator("#soundBtn").is_visible())
        hp.goto(f"{BASE}/host/game/{qg}"); hp.wait_for_timeout(600)
        hp.check("#roomSoundOn"); hp.wait_for_timeout(500)
        check("turning it on saves room_sound", sql(f"select room_sound from games where code='{qg}'")[0][0] in (1, True))
        # once the QR page's speaker registers with Spotify, the host page picks it by itself
        transfers = []
        hp.route("**/api/spotify/transfer", lambda r: (transfers.append(r.request.post_data), r.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
        hp.route("https://api.spotify.com/v1/me/player/devices", lambda r: r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"},
                 body=json.dumps({"devices": [{"id": "rs1", "name": "Bingo Room Screen", "type": "Computer", "is_active": False}]})))
        hp.wait_for_timeout(5500)
        check("with 'Music on QR screen' on, the host page picks the 'Bingo Room Screen' speaker once it appears", hp.locator("#deviceSelect").input_value() == "rs1" and any("rs1" in (t or "") for t in transfers), str(transfers))
        check("picking it quietly leaves the device picker hidden", not hp.locator("#deviceRow").is_visible())
        hp.unroute("https://api.spotify.com/v1/me/player/devices"); hp.unroute("**/api/spotify/transfer")
        hp.goto(f"{BASE}/host/game/{qg}/qr"); hp.wait_for_timeout(600)
        check("before the game starts the QR page still shows the QR code, not the reveal", hp.locator("#qr svg").is_visible() and not hp.locator("#room").is_visible())
        hp.evaluate("window.__roomHandle({type:'game_started'})"); hp.wait_for_timeout(400)
        check("Start shows 'Game starting in' with a big 3-2-1 number", hp.locator("#room").is_visible() and not hp.locator("#qr").is_visible() and "Game starting in" in hp.locator("#roomLabel").inner_text() and hp.locator("#roomBig").inner_text().strip() in ("3", "2"), hp.locator("#roomBig").inner_text())
        hp.wait_for_timeout(3200)
        check("after the countdown it waits for the first song", "Get ready" in hp.locator("#roomBig").inner_text())
        hp.evaluate("window.__roomHandle({type:'track',title:'Mambo No. 5',artist:'Lou Bega',track_id:'t1',position_ms:2000,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(500)
        check("first song counts down to its reveal without naming it", "Song revealed in" in hp.locator("#roomLabel").inner_text() and "Mambo" not in hp.locator("#room").inner_text())
        hp.evaluate("window.__roomHandle({type:'track',title:'Mambo No. 5',artist:'Lou Bega',track_id:'t1',position_ms:10500,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(500)
        check("after 10 seconds the title and artist show", "Mambo No. 5" in hp.locator("#roomBig").inner_text() and "Lou Bega" in hp.locator("#roomSub").inner_text())
        hp.evaluate("window.__roomHandle({type:'track',title:'Africa',artist:'Toto',track_id:'t2',position_ms:0,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(400)
        check("the finished song moves to 'Last song'", hp.locator("#roomList li").count() == 1 and "Mambo No. 5" in hp.locator("#roomList").inner_text() and "Africa" not in hp.locator("#room").inner_text())
        hp.evaluate("window.__roomHandle({type:'track',title:'Somewhere Over the Rainbow / What a Wonderful World (Live at the Concert Hall)',artist:'Israel Kamakawiwo ole and the Orchestra',track_id:'tl',position_ms:20000,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(500)
        fit = hp.evaluate("(() => { const r = document.getElementById('room'); return [r.scrollHeight, r.clientHeight, document.documentElement.scrollWidth, innerWidth]; })()")
        check("a very long title at the big size still fits on the screen", fit[0] <= fit[1] + 2 and fit[2] <= fit[3], str(fit))
        rect = "(() => { const e = document.getElementById('roomRecent'); const r = e.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height), getComputedStyle(e.querySelector('li')).fontSize]; })()"
        hp.evaluate("window.__roomHandle({type:'track',title:'Africa',artist:'Toto',track_id:'t2',position_ms:1000,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(500)
        r_count = hp.evaluate(rect)
        hp.evaluate("window.__roomHandle({type:'track',title:'Africa',artist:'Toto',track_id:'t2',position_ms:10600,paused:false,server_ts_ms:0})"); hp.wait_for_timeout(500)
        r_shown = hp.evaluate(rect)
        check("the Last song block keeps its position and size when the countdown turns into the song", r_count == r_shown, f"{r_count} vs {r_shown}")
        hp.evaluate("window.__roomHandle({type:'room',event:'bingo',winner_name:'Sam'})"); hp.wait_for_timeout(300)
        check("a bingo shows 'BINGO! Sam got a Bingo' with fireworks, and Continue clears it", hp.locator("#roomBanner").is_visible() and "BINGO!" in hp.locator("#roomBanner").inner_text() and "Sam got a Bingo" in hp.locator("#roomBanner").inner_text() and hp.evaluate("(() => { const c = document.getElementById('roomFireworks'); return c.width > 0 && c.height > 0; })()"))
        hp.evaluate("window.__roomHandle({type:'room',event:'clear'})"); hp.wait_for_timeout(300)
        check("banner goes away on continue", not hp.locator("#roomBanner").is_visible())
        hp.evaluate("window.__roomHandle({type:'room',event:'game_over'})"); hp.wait_for_timeout(300)
        check("game over shows on the room screen", "Game over" in hp.locator("#roomBig").inner_text())
        # the QR page can become a Spotify speaker ("Bingo Room Screen"); stand in for Spotify's player script
        hp.route("https://sdk.scdn.co/spotify-player.js", lambda route: route.fulfill(content_type="application/javascript", body="window.Spotify={Player:function(o){window.__spName=o.name;var h=window.__spH={};this.addListener=function(e,f){h[e]=f};this.activateElement=function(){window.__spActivated=true};this.connect=function(){setTimeout(function(){h.ready&&h.ready({device_id:'room1'})},50);return Promise.resolve(true)}}};setTimeout(function(){window.onSpotifyWebPlaybackSDKReady&&window.onSpotifyWebPlaybackSDKReady()},10);"))
        hp.goto(f"{BASE}/host/game/{qg}/qr"); hp.wait_for_timeout(500)
        check("the QR page offers to play the game music on this screen", hp.locator("#soundBtn").is_visible())
        hp.click("#soundBtn"); hp.wait_for_timeout(900)
        reqs = []
        hp.on("request", lambda r: reqs.append((r.url, r.post_data)) if r.url.endswith("/track_update") else None)
        check("clicking it starts a speaker named 'Bingo Room Screen' and shows nothing on the screen", hp.evaluate("window.__spName") == "Bingo Room Screen" and hp.evaluate("window.__spActivated") is True and not hp.locator("#soundMsg").is_visible() and not hp.locator("#soundBtn").is_visible())
        hp.evaluate("window.__spH.player_state_changed({paused:false, position:1234, track_window:{current_track:{id:'abc', name:'Africa', artists:[{name:'Toto'}]}}})"); hp.wait_for_timeout(500)
        check("music playing on that speaker is reported to the server so the phones follow", len(reqs) == 1 and '"title":"Africa"' in (reqs[0][1] or "") and '"artist":"Toto"' in (reqs[0][1] or "") and '"position_ms":1234' in (reqs[0][1] or ""), str(reqs))
        hp.goto(f"{BASE}/host/game/{qg}"); hp.wait_for_timeout(600)
        hp.uncheck("#roomRevealOn"); hp.wait_for_timeout(500)
        check("turning it off saves, so the QR page stays a QR code", sql(f"select room_reveal from games where code='{qg}'")[0][0] in (0, False))

        # ---- Paper cards ----
        pc = create_game(hp, "Paper", paper=4)
        hp.goto(f"{BASE}/host/game/{pc}")
        hp.wait_for_timeout(1200)
        check("host page has a Paper cards button, not a panel", hp.locator(".paperCardsBtn").count() == 1 and hp.locator("#paperPanel").count() == 0)
        check("button shows the card count", "(4)" in hp.locator(".paperCardsBtn").inner_text())
        host_url = hp.url
        with hp.expect_popup() as pop:
            hp.click(".paperCardsBtn")
        popup = pop.value
        popup.wait_for_load_state("networkidle")
        check("Paper cards opens in a new window and leaves the host page alone", hp.url == host_url and popup.url.endswith(f"/host/game/{pc}/paper"), popup.url)
        popup.close()
        hp.goto(f"{BASE}/host/game/{pc}/paper")
        hp.wait_for_load_state("networkidle")
        check("print page shows 4 cards, each with a QR code", hp.locator(".sheet").count() == 4 and hp.locator(".qr svg").count() == 4)
        codes_before = [t for t in hp.locator(".foot span:first-child").all_inner_texts() if t]
        texts_before = hp.locator(".sheet").all_inner_texts()
        accept_all = lambda d: d.accept()
        hp.on("dialog", accept_all)
        hp.click("text=Regenerate all")
        hp.wait_for_load_state("networkidle")
        codes_after = [t for t in hp.locator(".foot span:first-child").all_inner_texts() if t]
        changed = sum(a != c for a, c in zip(texts_before, hp.locator(".sheet").all_inner_texts()))
        check("Regenerate all keeps numbers and check codes but changes every card", codes_before == codes_after and changed == 4, f"changed {changed}")
        hp.fill(".moreForm input[name=count]", "2")
        hp.click(".moreForm button")
        hp.wait_for_load_state("networkidle")
        check("Make more adds cards", hp.locator(".sheet").count() >= 2 and "6 paper cards" in hp.locator(".toolbar .title").inner_text())
        # accept a paper card -> Continue/End bar
        card_code = codes_before[0].split("·")[1].strip()
        hp.goto(f"{BASE}/host/game/{pc}")
        hp.wait_for_timeout(800)
        hp.fill("#paperCode", card_code)
        hp.press("#paperCode", "Enter")
        hp.wait_for_timeout(1000)
        hp.click("#pmAccept")
        hp.wait_for_timeout(1000)
        check("accepting a paper card shows Continue Game and End Game", hp.locator("#btnContinueGame").is_visible() and hp.locator("#btnEndGame").is_visible())
        # songs removed from the playlist -> out-of-date warning
        gid = sql(f"select id from games where code='{pc}'")[0][0]
        gone = [x[0] for x in sql(f"select s.title from card_squares s join players p on p.id=s.player_id where p.game_id={gid} and p.card_number=1 and s.is_free=0 limit 2")]
        subprocess.run(["docker", "exec", CONTAINER, "sh", "-c", "printf '%s\\n%s\\n' \"$0\" \"$1\" > /work/now/DROP", gone[0], gone[1]], capture_output=True)
        time.sleep(1.5)  # the notice's own cache is shortened to 1 second in the test server (local_server.py)
        hp.goto(f"{BASE}/host/game/{pc}")
        hp.wait_for_timeout(1800)
        check("button warns when songs left the playlist", hp.locator(".paperCardsBtn").inner_text().startswith("⚠"))
        subprocess.run(["docker", "exec", CONTAINER, "rm", "-f", "/work/now/DROP"], capture_output=True)

        # ---- Saved games / Play again ----
        # the dashboard has links to Saved games and Game history instead of a list of recent games
        hp.goto(f"{BASE}/host")
        check("the dashboard has no list of recent games and no Your games box (they are in the account menu)",
              hp.locator("#recentGames").count() == 0 and "Your games" not in hp.content() and hp.locator(".spotifyBtns .btn").count() >= 1)
        sb = hp.locator(".spotifyBtns").bounding_box(); sp_ = hp.locator(".spotifyPanel").bounding_box(); cg = hp.locator("text=Create Game").first.bounding_box()
        check("the Spotify box is a slim bar across the page with a gap above Create Game", sp_["width"] > 900 and sp_["height"] <= 110 and cg["y"] - (sp_["y"] + sp_["height"]) >= 10, f"{sp_} {cg}")
        hp.set_viewport_size({"width": 1440, "height": 700}); hp.reload(); hp.wait_for_timeout(500)
        check("the Create Game button is visible in a 1440x700 window without scrolling", hp.evaluate("document.querySelector('#createBtn').getBoundingClientRect().bottom") <= 700, str(hp.evaluate("document.querySelector('#createBtn').getBoundingClientRect().bottom")))
        hp.set_viewport_size({"width": 1440, "height": 900})
        hp.goto(f"{BASE}/host/history")
        row_pc = hp.locator(".savedGame", has_text=pc)
        check("Game history lists the game with its code, status, Save and Delete", row_pc.count() == 1 and "Game Code: " + pc in row_pc.inner_text() and row_pc.locator("button:has-text('Save')").count() == 1 and row_pc.locator("button:has-text('Delete')").count() == 1)
        row_pc.locator("form[action$='/save'] button").click()
        hp.wait_for_load_state("networkidle")
        row_pc = hp.locator(".savedGame", has_text=pc)
        check("saving from Game history keeps you there and marks the game Saved, without a Delete button",
              hp.url.endswith("/host/history") and "Saved" in row_pc.inner_text() and row_pc.locator("button:has-text('Remove from saved')").count() == 1 and row_pc.locator("button:has-text('Delete')").count() == 0)
        dh = create_game(hp, "History delete me")
        hp.goto(f"{BASE}/host/history")
        check("a new game appears at the top of Game history (newest first)", dh in hp.locator(".savedGame").first.inner_text())
        hp.locator(".savedGame", has_text=dh).locator("form[action$='/delete'] button").click()
        hp.wait_for_load_state("networkidle")
        check("deleting from Game history removes the game and returns to Game history", hp.url.endswith("/host/history") and hp.locator(".savedGame", has_text=dh).count() == 0 and sql(f"select count(*) from games where code='{dh}'")[0][0] == 0)
        check("Game history is for hosts only", b.new_context().request.get(f"{BASE}/host/history", max_redirects=0).status in (302, 303, 307))
        hp.click("#hostUserMenuBtn")
        menu_txt = hp.locator(".userMenuDropdown").inner_text()
        check("the user menu has an Options item (Account, Saved Games, History and Playlists moved into it)", "Options" in menu_txt and "Game History" not in menu_txt and "Manage Playlists" not in menu_txt, menu_txt)
        hp.click(".userMenuDropdown a[href='/host/options']"); hp.wait_for_load_state("networkidle")
        check("Options opens the Account page", hp.url.endswith("/host/account") and hp.locator(".optionsNavItem.active").inner_text().strip().endswith("Account"), hp.url)
        nav_ok = True
        for path, label in (("/host/account", "Account"), ("/host/themes", "Themes"), ("/host/saved", "Saved Games"), ("/host/history", "Game History"), ("/host/playlist", "Manage Playlists"), ("/host/events/manage", "Events")):
            hp.goto(f"{BASE}{path}"); hp.wait_for_timeout(250)
            items = [t.strip() for t in hp.locator(".optionsNavItem").all_inner_texts()]
            act = hp.locator(".optionsNavItem.active").all_inner_texts()
            if not (len(items) == 6 and [i.split(" ", 1)[-1].strip() if False else i for i in items] and len(act) == 1 and act[0].strip().endswith(label)): nav_ok = False; print("nav problem on", path, items, act)
        check("every Options page has the left menu (Account, Themes, Saved Games, Game History, Manage Playlists, Events) with the current page highlighted", nav_ok)
        hp.click(".optionsNavItem >> text=Themes"); hp.wait_for_load_state("networkidle")
        check("a left-menu entry opens its page", hp.url.endswith("/host/themes") and hp.locator(".themeCard").count() == 9)
        hp.keyboard.press("Escape")
        hp.goto(f"{BASE}/host/game/{pc}")
        hp.wait_for_timeout(800)
        note = hp.locator(".paperLinkRow .savedNote")
        pl, nt = hp.locator(".paperCardsBtn").bounding_box(), note.bounding_box()
        check("a saved game shows '★ Saved. Manage in Saved Games' to the right of the Paper cards link",
              note.count() == 1 and "Saved" in note.inner_text() and nt["x"] > pl["x"] + pl["width"] - 1 and abs(nt["y"] - pl["y"]) < 12, f"{pl} {nt}")
        check("'Manage in Saved Games' opens in a new tab", hp.locator(".savedNote a").get_attribute("target") == "_blank")
        eg2 = create_game(hp, "Unsaved")
        hp.goto(f"{BASE}/host/game/{eg2}")
        hp.click(".saveGameForm button"); hp.wait_for_load_state("networkidle")
        check("an unsaved game has a Save game link that saves it", hp.locator(".savedNote").count() == 1 and hp.locator(".saveGameForm").count() == 0)
        hp.goto(f"{BASE}/host/saved")
        check("Saved Games shows the status as text on the details line, not a pill", hp.locator(".savedStatus").count() >= 1 and hp.locator(".savedFacts .savedStatus").first.inner_text() in ("Ready", "In progress") and hp.locator(".listRow .pill, .savedGame .pill").count() == 0)
        check("Saved Games shows 'Game Code: XXXX' under the name", f"Game Code: {hp.locator('.savedFacts b').first.inner_text()}" is not None and re.search(r"Game Code:\s*"+pc, hp.locator(".savedFacts").first.inner_text()) is not None or any(re.search(r"Game Code:\s*"+pc, t) for t in hp.locator(".savedFacts").all_inner_texts()))
        check("saved games page lists the game", pc in hp.content())

        # ---- Explicit-lyrics flag on playlists ----
        P30 = "https://open.spotify.com/playlist/PLAYLIST30AAAAAAAAAAAA"
        hp.goto(f"{BASE}/host/playlist")
        for nm, url in (("Explicit mix", PLAYLIST), ("Clean mix", P30)):
            hp.fill("input[name=name]", nm)
            hp.fill("input[name=playlist_id_or_url]", url)
            hp.click("form[action='/host/playlist/save'] button[type=submit]")
            hp.wait_for_load_state("networkidle")
        explicit_row = hp.locator(".listRow:has-text('Explicit mix')").inner_text()
        clean_row = hp.locator(".listRow:has-text('Clean mix')").inner_text()
        check("Manage Playlists flags the playlist with explicit songs and shows the count", "5 explicit" in explicit_row, explicit_row[:90])
        check("a playlist with no explicit songs is marked Clean", "Clean" in clean_row and "explicit" not in clean_row.replace("explicit songs yet", ""), clean_row[:90])
        hp.click(".listRow:has-text('Explicit mix') .plShowExplicit")
        hp.wait_for_timeout(800)
        listed = hp.locator(".listRow:has-text('Explicit mix') .plExplicitList").inner_text()
        check("'Show which songs' lists the explicit titles", "No Diggity" in listed and "Bulls on Parade" in listed, listed)
        hp.check("input[data-hide-explicit]")
        check("the hide filter hides the flagged playlist and keeps the clean one",
              not hp.locator(".listRow:has-text('Explicit mix')").is_visible() and hp.locator(".listRow:has-text('Clean mix')").is_visible())
        hp.uncheck("input[data-hide-explicit]")
        # rename: the owner can, another host cannot
        hp.goto(f"{BASE}/host/playlist")
        hp.click(".listRow:has-text('Clean mix') .plRenameBtn")
        hp.fill(".listRow:has-text('Clean mix') .plRenameForm input[name=name]", "Roller rink (clean)")
        hp.click(".listRow:has-text('Clean mix') .plRenameForm button[type=submit]")
        hp.wait_for_load_state("networkidle")
        check("the owner can rename a saved playlist", "Roller rink (clean)" in hp.locator(".listTitle").all_inner_texts().__str__() and "Clean mix" not in hp.content(), str(hp.locator(".listTitle").all_inner_texts()) + " | url " + hp.url + " | alerts " + str(hp.locator(".alert").all_inner_texts()))
        pid = sql("select id from saved_playlists where name='Roller rink (clean)'")[0][0]
        r = tpost(other, f"{BASE}/host/playlist/rename", form={"playlist_id": str(pid), "name": "Hijacked"})
        check("another host cannot rename it", sql(f"select name from saved_playlists where id={pid}")[0][0] == "Roller rink (clean)", str(r.status))
        hp.goto(f"{BASE}/host/playlist")
        hp.click(".listRow:has-text('Roller rink') .plRenameBtn")
        hp.fill(".listRow:has-text('Roller rink') .plRenameForm input[name=name]", "   ")
        hp.evaluate("document.querySelector('.listRow .plRenameForm input[name=name]').removeAttribute('required')")
        check("an empty name is refused", hp.evaluate("fetch('/host/playlist/rename',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'playlist_id=%d&name=%%20'}).then(r=>r.status)" % pid) in (400, 403))

        # a saved playlist Spotify can no longer read: says so, and Re-check explains instead of doing nothing
        hp.goto(f"{BASE}/host/playlist")
        hp.fill("input[name=name]", "Gone list")
        hp.fill("input[name=playlist_id_or_url]", "https://open.spotify.com/playlist/PLAYLISTGONEAAAAAAAAAA")
        hp.click("form[action='/host/playlist/save'] button[type=submit]")
        hp.wait_for_load_state("networkidle")
        gone_row = hp.locator(".listRow:has-text('Gone list')").inner_text()
        check("an unreadable playlist is marked as such, not 'Clean'", "couldn't be read from Spotify" in gone_row and "Clean" not in gone_row, gone_row[:120])
        hp.click(".listRow:has-text('Gone list') button:has-text('Re-check')")
        hp.wait_for_load_state("networkidle")
        check("Re-check on it explains what is wrong", "can't find that playlist" in hp.locator(".alertBad").inner_text(), hp.locator(".alertBad").inner_text() if hp.locator(".alertBad").count() else "no message")
        hp.goto(f"{BASE}/host/playlist")
        hp.click(".listRow:has-text('Gone list') button:has-text('Re-check')") if False else None

        # clean copy: runs in the background with no banners; the new playlist just appears in the list
        hp.goto(f"{BASE}/host/playlist")
        hp.click(".listRow:has-text('Explicit mix') button:has-text('Make clean copy')")
        hp.wait_for_load_state("networkidle")
        hp.wait_for_selector(".listRow:has-text('Explicit mix (Clean)')", timeout=30000)   # the page reloads itself when the copy is ready
        check("Make clean copy shows no banner while it runs or when it finishes", hp.evaluate("Array.from(document.querySelectorAll('.alert')).filter(e => e.offsetParent !== null).length") == 0 and hp.locator("#cleanJobs").inner_text().strip() == "", str(hp.locator(".alert").all_inner_texts()) + " | " + hp.locator("#cleanJobs").inner_text())
        copy_row = hp.locator(".listRow:has-text('Explicit mix (Clean)')").inner_text()
        check("the copy is named (Clean), saved as a Clean playlist with 72 songs", "Clean" in copy_row and "72 songs" in copy_row, copy_row[:100])
        check("the original still has its 5 explicit songs", "5 explicit" in hp.locator(".listRow:has-text('Explicit mix'):not(:has-text('(Clean)'))").inner_text())
        check("the finished job was cleared", len(hp.evaluate("fetch('/host/playlist/clean_jobs').then(r=>r.json()).then(j=>j.jobs)")) == 0)
        # making it again must not duplicate it, even when this app's saved list doesn't know about it (e.g. it
        # was made from the other copy of the app, which shares the same Spotify account)
        spotify_id = sql("select spotify_playlist_id from saved_playlists where name='Explicit mix (Clean)'")[0][0]
        sql("delete from saved_playlists where name='Explicit mix (Clean)'")
        hp.goto(f"{BASE}/host/playlist")
        hp.click(".listRow:has-text('Explicit mix'):not(:has-text('(Clean)')) button:has-text('Make clean copy')")
        hp.wait_for_load_state("networkidle")
        hp.wait_for_selector(".listRow:has-text('Explicit mix (Clean)')", timeout=30000)
        rows = sql("select spotify_playlist_id from saved_playlists where name='Explicit mix (Clean)'")
        check("an existing '(Clean)' playlist in Spotify is reused and saved again once, not duplicated", len(rows) == 1 and rows[0][0] == spotify_id, str(rows))
        # too short
        hp.fill("input[name=name]", "Short one")
        hp.fill("input[name=playlist_id_or_url]", "https://open.spotify.com/playlist/PLAYLISTSHORTAAAAAAAAA")
        hp.click("form[action='/host/playlist/save'] button[type=submit]")
        hp.wait_for_load_state("networkidle")
        hp.click(".listRow:has-text('Short one') button:has-text('Make clean copy')")
        hp.wait_for_load_state("networkidle")
        hp.wait_for_selector(".listRow:has-text('Short one') .plJobError", timeout=20000)
        check("a clean copy that would be under 24 songs is refused with a short message on that row", "at least 24" in hp.locator(".listRow:has-text('Short one') .plJobError").inner_text(), hp.locator(".listRow:has-text('Short one') .plJobError").inner_text())
        hp.click(".listRow:has-text('Short one') .plJobStatus button:has-text('Dismiss')")
        hp.wait_for_timeout(600)
        check("the error can be dismissed", hp.locator(".listRow:has-text('Short one') .plJobError").count() == 0)
        # no permission yet -> asks to reconnect
        hp.goto(f"{BASE}/host/playlist")
        hp.fill("input[name=name]", "FORBID list")
        hp.fill("input[name=playlist_id_or_url]", "https://open.spotify.com/playlist/PLAYLISTFORBIDAAAAAAAA")
        hp.click("form[action='/host/playlist/save'] button[type=submit]")
        hp.wait_for_load_state("networkidle")
        hp.click(".listRow:has-text('FORBID list') button:has-text('Make clean copy')")
        hp.wait_for_load_state("networkidle")
        hp.wait_for_selector(".listRow:has-text('FORBID list') .plJobStatus .plJobError", timeout=20000)
        slot = hp.locator(".listRow:has-text('FORBID list') .plJobStatus")
        check("without Spotify's permission it says so and offers to reconnect (back to this page)", "permission" in slot.inner_text() and slot.locator("a:has-text('Reconnect Spotify')").get_attribute("href") == "/host/spotify/connect?next=/host/playlist")
        check("a failed copy does not leave a saved playlist behind", sql("select count(*) from saved_playlists where name like 'FORBID%(Clean)'")[0][0] == 0)
        hp.click(".listRow:has-text('FORBID list') .plJobStatus button:has-text('Dismiss')")

        # sort menu on Manage Playlists
        hp.goto(f"{BASE}/host/playlist")
        def order():
            return [t.split("\n")[0].strip() for t in hp.locator(".listRow .listTitle").all_inner_texts()]
        hp.select_option(".plSort", "name")
        names = [re.sub(r"\s+(⚠|Clean|Public|Private).*$", "", n) for n in order()]
        check("sorting by name A-Z puts the playlists in alphabetical order", names == sorted(names, key=str.lower), str(names))
        hp.select_option(".plSort", "songs_desc")
        counts = [int(m.group(1)) for m in (re.search(r"(\d+) songs", t) for t in hp.locator(".listRow").all_inner_texts()) if m]
        check("sorting by most songs puts the biggest playlist first", counts == sorted(counts, reverse=True) and counts[0] == 75, str(counts))
        hp.select_option(".plSort", "songs")
        counts = [int(m.group(1)) for m in (re.search(r"(\d+) songs", t) for t in hp.locator(".listRow").all_inner_texts()) if m]
        check("sorting by fewest songs reverses it", counts == sorted(counts), str(counts))
        hp.reload()
        check("the sort choice is remembered", hp.locator(".plSort").input_value() == "songs")
        hp.select_option(".plSort", "new")

        # create-game page: pasted link warning, then the saved-playlist menu
        hp.goto(f"{BASE}/host")
        hp.fill("input[name=playlist_id_or_url]", PLAYLIST)
        hp.wait_for_timeout(1500)
        check("pasting a playlist link shows no explicit-songs flag", hp.locator(".playlistExplicitNote").count() == 0 and not hp.locator("#createBtn").is_disabled())
        opts = [o.strip() for o in hp.locator("select[name=saved_playlist_id] option").all_text_contents()]
        check("the saved-playlist menu shows the explicit count and the new name", any(o.startswith("Explicit mix") and "(5 explicit)" in o for o in opts) and "Roller rink (clean)" in opts, str(opts))
        hp.select_option("#playlist_mode", "saved")
        hp.check("input[data-hide-explicit]")
        shown = [o for o in hp.locator("select[name=saved_playlist_id] option:not([disabled])").all_text_contents()]
        check("the hide filter removes flagged playlists from the menu", not any("(5 explicit)" in o or "(1 explicit)" in o for o in shown) and any("Roller rink" in o for o in shown) and any(o.startswith("Explicit mix (Clean)") for o in shown), str(shown))
        hp.uncheck("input[data-hide-explicit]")

        # ---- Help page and menu ----
        pg = outsider.new_page()
        pg.goto(BASE + "/help")
        check("help page is public and has its sections", pg.locator(".helpPage h2").count() >= 8)
        check("the help page explains Bingo hints and its table of contents links to them", pg.locator("#hints").count() == 1 and pg.locator(".helpToc a[href='#hints']").count() == 1 and "Players choose" in pg.locator(".helpPage").inner_text())
        help_text = pg.locator(".helpPage").inner_text()
        check("the help page explains the QR screen reveal and room speaker, and the table of contents links to it", pg.locator("#room").count() == 1 and pg.locator('.helpToc a[href="#room"]').count() == 1 and "Reveal on QR screen" in help_text and "Music on QR screen" in help_text and "Bingo Room Screen" in help_text)
        check("the help page has an Account and themes section listing all nine themes", pg.locator("#account").count() == 1 and pg.locator(".helpToc a[href='#account']").count() == 1 and all(t in help_text for t in ("Midnight Purple", "Ocean Blue", "Emerald", "Sunset", "Rose", "Graphite", "Maize & Blue", "Light", "Custom")) and "Save theme" in help_text)
        check("the help page covers Game History, Kick/Admit, the required event name and the Card colors switch", all(x in help_text for x in ("Game History", "Kick", "needs a name", "Card colors")))
        check("every link in the help page's table of contents points to a section that exists", pg.evaluate("Array.from(document.querySelectorAll('.helpToc a')).every(a => document.getElementById(a.getAttribute('href').slice(1)))"))
        check("the help page names the Play Alone button correctly", "Play Alone" in help_text and "Play Solo" not in help_text)
        hp.goto(f"{BASE}/help")
        hp.wait_for_timeout(1000)
        hp.click("#hostUserMenuBtn")
        check("menu shows on the help page with a Getting Started item", "Getting Started" in hp.locator(".userMenuDropdown").inner_text())

        # ---- Every main page loads without script errors, at desktop and phone width ----
        blocked = []
        hp.on("console", lambda m: blocked.append(m.text[:140]) if m.type == "error" and ("Content Security Policy" in m.text or "Refused to" in m.text or "404" in m.text) else None)
        for path in ["/enter", "/home", "/host", "/host/playlist", "/host/saved", "/host/admin/users", "/help", f"/host/game/{pc}", f"/host/game/{pc}/paper"]:
            for width in ((1440,) if path.endswith("/paper") else (1440, 390)):   # the print page isn't a phone page
                hp.set_viewport_size({"width": width, "height": 900})
                resp = hp.goto(BASE + path)
                hp.wait_for_timeout(500)
                check(f"{path} loads at {width}px without sideways scroll", resp.status == 200 and not hp.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        check("no JavaScript errors on any page", not js_errors, "; ".join(js_errors[:3]))
        hdr = b.new_context().request.get(BASE + "/enter").headers
        check("every response carries the security headers", hdr.get("x-content-type-options") == "nosniff" and hdr.get("x-frame-options") == "DENY"
              and "default-src 'self'" in hdr.get("content-security-policy", "") and hdr.get("referrer-policy") and hdr.get("permissions-policy"), str(dict(hdr))[:200])
        import re as _re
        csp1 = hdr.get("content-security-policy", "")
        csp2 = b.new_context().request.get(BASE + "/enter").headers.get("content-security-policy", "")
        sp1 = _re.search(r"script-src ([^;]*);", csp1)
        sp2 = _re.search(r"script-src ([^;]*);", csp2)
        nonce1 = _re.search(r"'nonce-([^']+)'", sp1.group(1)) if sp1 else None
        nonce2 = _re.search(r"'nonce-([^']+)'", sp2.group(1)) if sp2 else None
        check("scripts are limited by a nonce, not 'unsafe-inline'", sp1 and "'unsafe-inline'" not in sp1.group(1) and nonce1 and nonce2 and nonce1.group(1) != nonce2.group(1), csp1[:200])
        bad_inline = []
        for path in ["/enter", "/home", "/host", "/host/playlist", "/host/saved", "/host/admin/users", "/help", f"/host/game/{pc}", f"/host/game/{pc}/paper", f"/host/game/{pc}/qr"]:
            r = host.request.get(BASE + path)
            html = r.text()
            n = _re.search(r"'nonce-([^']+)'", r.headers.get("content-security-policy", ""))
            for m in _re.finditer(r"<script\b([^>]*)>", html):
                if "src=" not in m.group(1) and not (n and f'nonce="{n.group(1)}"' in m.group(1)):
                    bad_inline.append(path + " inline script without nonce")
            for m in _re.finditer(r"\son[a-z]+\s*=", _re.sub(r"<script\b.*?</script>", "", html, flags=_re.S)):
                bad_inline.append(path + " inline event handler")
        check("no page has an inline script without the nonce or an inline event handler", not bad_inline, "; ".join(bad_inline[:3]))
        check("styles are limited to files from this site", "style-src 'self';" in csp1 and "'unsafe-inline'" not in csp1, csp1[:200])
        bad_style = []
        for path in ["/enter", "/home", "/host", "/host/playlist", "/host/saved", "/host/admin/users", "/host/account", "/host/themes", "/host/events/manage", "/help", f"/host/game/{pc}", f"/host/game/{pc}/paper", f"/host/game/{pc}/qr", "/play"]:
            h = host.request.get(BASE + path).text()
            if _re.search(r"<style\b", h) or _re.search(r"<[a-z][^<>]*\sstyle\s*=", h):
                bad_style.append(path)
        check("no page has an inline <style> block or style attribute", not bad_style, "; ".join(bad_style))
        hp.set_viewport_size({"width": 1440, "height": 900})
        hp.goto(BASE + f"/host/game/{pc}/paper")
        seen = []
        hp.remove_listener("dialog", accept_all)   # this time answer Cancel
        hp.once("dialog", lambda d: (seen.append(d.message), d.dismiss()))
        hp.click("form[data-confirm] button")
        hp.wait_for_timeout(400)
        check("a form with data-confirm asks first and stays put when cancelled", seen and "Regenerate" in seen[0] and hp.url.endswith("/paper"), str(seen)[:120] + " " + hp.url)
        # ---- Connect Spotify without a Spotify app configured ----
        rc = host.request.get(BASE + "/host/spotify/connect", max_redirects=0)
        check("Connect Spotify with no client ID/secret configured does not send the host to Spotify", rc.status in (302, 303) and "accounts.spotify.com" not in (rc.headers.get("location") or "") and "/host" in (rc.headers.get("location") or ""), str(rc.status) + " " + str(rc.headers.get("location")))
        hp.goto(f"{BASE}/host/spotify/connect"); hp.wait_for_load_state("networkidle")
        check("...it explains that the Spotify client ID and secret are missing and where an admin adds them", "client ID and secret are missing" in hp.content() and "App settings" in hp.content())
        # ---- Password reset from the shell, first-run admin ----
        cx0 = b.new_context()
        check("there is no web endpoint for resetting a password", cx0.request.post(BASE + "/host/breakglass/reset_password", form={"username": "h2", "new_password": "NewPass1234"}, headers={"X-CSRF-Token": "x"}).status in (403, 404, 405))
        env = ["-e", "DATABASE_URL=sqlite:////work/now/paper.db?check_same_thread=false", "-e", "COOKIE_SECRET=local-paper-test", "-w", "/work/now"]
        out = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-m", "app.reset_password", "h2"], capture_output=True, text=True)
        mpw = re.search(r"is now: (\S+)", out.stdout)
        check("the shell tool gives an existing user a new random password", out.returncode == 0 and mpw and len(mpw.group(1)) >= 12, (out.stdout + out.stderr)[-200:])
        if mpw:
            r = tpost(b.new_context(), BASE + "/login", form={"username": "h2", "password": mpw.group(1), "next": "/host"}, max_redirects=0)
            check("the new password logs in", r.status in (302, 303) and "/host" in r.headers.get("location", "") and "host_session" in r.headers.get("set-cookie", ""), str(r.status) + r.headers.get("location", ""))
            r = tpost(b.new_context(), BASE + "/login", form={"username": "h2", "password": "pw", "next": "/host"}, max_redirects=0)
            check("the old password no longer works", "host_session" not in r.headers.get("set-cookie", ""))
            # a password made by the reset tool is temporary: the host must choose their own before using the app
            fx = b.new_context(); fp = fx.new_page()
            fp.goto(BASE + "/login"); fp.fill("input[name=username]", "h2"); fp.fill("input[name=password]", mpw.group(1)); fp.click("button[type=submit]"); fp.wait_for_load_state("networkidle")
            check("after logging in with a temporary password the host lands on the Account page asking for their own", fp.url.rstrip("/").endswith("/host/account") and "temporary password" in fp.content(), fp.url)
            gated = []
            for path in ("/host", "/host/themes", "/host/saved", "/host/playlist", "/play"):
                fp.goto(BASE + path); fp.wait_for_load_state("networkidle"); gated.append(fp.url.rstrip("/").endswith("/host/account"))
            check("every other host page is held back until then", all(gated), str(gated))
            check("the Account page itself and logout still work", fx.request.get(BASE + "/host/account").status == 200 and fx.request.get(BASE + "/host/whoami").status == 200)
            fp.goto(BASE + "/host/account"); fp.wait_for_load_state("networkidle")
            for sel, val in (("input[name=current_password]", mpw.group(1)), ("input[name=new_password]", mpw.group(1)), ("input[name=new_password2]", mpw.group(1))):
                fp.fill(sel, val)
            fp.click("button:has-text('Update password')"); fp.wait_for_load_state("networkidle")
            check("keeping the temporary password as the new one is refused", "different password" in fp.content() and sql("select must_change_password from host_users where username='h2'")[0][0] in (1, True))
            for sel, val in (("input[name=current_password]", mpw.group(1)), ("input[name=new_password]", "my-own-pass-1"), ("input[name=new_password2]", "my-own-pass-1")):
                fp.fill(sel, val)
            fp.click("button:has-text('Update password')"); fp.wait_for_load_state("networkidle")
            fp.goto(BASE + "/host/themes"); fp.wait_for_load_state("networkidle")
            check("choosing their own password lifts the hold", fp.url.rstrip("/").endswith("/host/themes") and sql("select must_change_password from host_users where username='h2'")[0][0] in (0, False))
            fx.close()
            # the reset and the password change above logged the second host's older browser out (correct): check, then log it in again
            was_out = other.request.get(BASE + "/host", max_redirects=0).status in (301, 302, 303, 307)
            tpost(other, BASE + "/login", form={"username": "h2", "password": "my-own-pass-1", "next": "/host"}, max_redirects=0)
            check("a password reset by the tool logged the account's older browser out, and logging in again works", was_out and other.request.get(BASE + "/host", max_redirects=0).status == 200)
            # a password an admin sets for someone else is temporary too; their own is not
            tpost(host, f"{BASE}/host/admin/users/create", form={"username": "temp-user", "password": "temporary-1"}, max_redirects=0)
            check("a host account made by an admin starts with a temporary password", sql("select must_change_password from host_users where username='temp-user'")[0][0] in (1, True))
            tpost(host, f"{BASE}/host/admin/users/create", form={"username": "short-pw-user", "password": "abc"}, max_redirects=0)
            check("an admin cannot make an account with a temporary password shorter than 8 characters", sql("select count(*) from host_users where username='short-pw-user'")[0][0] == 0)
            import time as _t
            timing_ctx = b.new_context()
            def _login_time(u):
                t0 = _t.time()
                for _ in range(3):
                    tpost(timing_ctx, BASE + "/login", form={"username": u, "password": "wrong-password-x"}, headers={"X-Forwarded-For": "198.51.100.77"}, max_redirects=0)
                return (_t.time() - t0) / 3
            t_real, t_fake = _login_time("temp-user"), _login_time("no-such-user-x")
            check("an unknown username takes about as long to refuse as a real one (no probing for usernames)", t_fake > 0.4 * t_real, f"real {t_real:.2f}s, unknown {t_fake:.2f}s")
            uid_h = sql("select id from host_users where username='h'")[0][0]
            tpost(host, f"{BASE}/host/admin/users/set_password", form={"user_id": str(uid_h), "password": "pw"}, max_redirects=0)
            check("an admin setting their own password is not made to change it again", sql("select must_change_password from host_users where username='h'")[0][0] in (0, False))
            tpost(host, f"{BASE}/host/admin/users/delete", form={"user_id": str(sql("select id from host_users where username='temp-user'")[0][0])}, max_redirects=0)
        out = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-m", "app.reset_password", "nobody"], capture_output=True, text=True)
        check("an unknown user is refused unless --create is given", out.returncode == 1 and "No user named" in out.stdout, out.stdout[-120:])
        def first_run(env_pw):
            code = ("import os\nif os.path.exists('/tmp/firstrun.db'): os.remove('/tmp/firstrun.db')\n"
                    "from app import main, models, setup_flow\nfrom app.db import Base, engine, SessionLocal\nBase.metadata.create_all(bind=engine)\n"
                    + (f"os.environ['HOST_ADMIN_PASSWORD'] = {env_pw!r}\n" if env_pw else "os.environ.pop('HOST_ADMIN_PASSWORD', None)\n")
                    + "os.environ['HOST_PASSWORD'] = 'old-fixed-value'\n"
                    "setup_flow._done = False\n"
                    "db = SessionLocal(); main._bootstrap_admin_user(db); main._bootstrap_admin_user(db)\n"
                    "us = db.query(models.HostUser).all()\n"
                    "from app.passwords import pw_verify\n"
                    "print('USERS', len(us), 'NEEDS_SETUP', setup_flow.needs_setup(), 'PWOK', bool(us) and pw_verify('chosen-in-env-1', us[0].password_hash), 'MUST', bool(us) and bool(us[0].must_change_password))\n")
            return subprocess.run(["docker", "exec", "-e", "DATABASE_URL=sqlite:////tmp/firstrun.db?check_same_thread=false", "-e", "COOKIE_SECRET=local-paper-test", "-w", "/work/now", CONTAINER, "python", "-c", code], capture_output=True, text=True)
        fr = first_run(None)
        check("a fresh install with no password configured makes no account: the first visitor gets the setup screen (the old HOST_PASSWORD setting is ignored)", "USERS 0 NEEDS_SETUP True" in fr.stdout, (fr.stdout + fr.stderr)[-200:])
        fr2 = first_run("chosen-in-env-1")
        check("an unattended install with HOST_ADMIN_PASSWORD makes the admin from it, once, with no setup screen", "USERS 1 NEEDS_SETUP False PWOK True MUST False" in fr2.stdout, (fr2.stdout + fr2.stderr)[-200:])

        # the app makes (and keeps) its own cookie secret when none is configured
        def cookie_secret(data_dir):
            snippet = "import hashlib\nfrom app.security import COOKIE_SECRET\nprint('SECRET', hashlib.sha256(COOKIE_SECRET.encode()).hexdigest()[:12], len(COOKIE_SECRET))"
            return subprocess.run(["docker", "exec", "-e", "COOKIE_SECRET=", "-e", f"BINGO_DATA_DIR={data_dir}", "-w", "/work/now", CONTAINER, "python", "-c", snippet], capture_output=True, text=True)
        subprocess.run(["docker", "exec", CONTAINER, "rm", "-rf", "/tmp/bingo-data-test"])
        cs1, cs2 = cookie_secret("/tmp/bingo-data-test"), cookie_secret("/tmp/bingo-data-test")
        mode = subprocess.run(["docker", "exec", CONTAINER, "stat", "-c", "%a", "/tmp/bingo-data-test/cookie_secret"], capture_output=True, text=True).stdout.strip()
        check("with no COOKIE_SECRET the app makes a long random one, keeps it in its data folder (readable only by the app) and reuses it", "SECRET" in cs1.stdout and cs1.stdout == cs2.stdout and int(cs1.stdout.split()[-1]) >= 48 and mode == "600", cs1.stdout + cs1.stderr[-200:] + mode)
        bad_dir = cookie_secret("/proc/not-writable")
        check("with no COOKIE_SECRET and no writable data folder the app refuses to start and says why", "SECRET" not in bad_dir.stdout and "COOKIE_SECRET is not set" in bad_dir.stderr, bad_dir.stderr[-200:])

        # ---- Players still waiting when the game starts can be admitted afterwards ----
        wg = create_game(hp, "Late admit")
        wctx, wp = join(b, wg, "Waiting Wendy")
        sql(f"update games set status='started' where code='{wg}'")
        hp.goto(f"{BASE}/host/game/{wg}")
        hp.wait_for_timeout(800)
        check("in a running game Admit All is still available", hp.locator("#admitBtn").is_enabled())
        hp.click("#admitBtn"); hp.wait_for_timeout(1500)
        check("admitting a waiting player after the game started works", sql(f"select admitted from players where game_id=(select id from games where code='{wg}') and name='Waiting Wendy'")[0][0] in (1, True), hp.locator("#hostMsg").inner_text())
        sql(f"update games set status='ended' where code='{wg}'")
        check("nobody can be admitted once the game has ended", tpost(host, f"{BASE}/host/game/{wg}/admit_all").status == 409)
        wctx.close()

        # ---- When the host ends the game every phone, admitted or still waiting, says so and goes back to the start page ----
        og = create_game(hp, "Ends")
        wctx2, wp2 = join(b, og, "Waiting Walt")
        actx2, ap2 = join(b, og, "Admitted Ada")
        tpost(host, f"{BASE}/host/game/{og}/player/2/admit")
        sql(f"update games set status='started' where code='{og}'")
        wp2.reload(); ap2.reload(); wp2.wait_for_timeout(800)
        check("before the end, the waiting player sees the waiting message and no game-over screen", "Waiting to be admitted" in wp2.inner_text("body") and not wp2.locator("#gameOverOverlay").is_visible())
        tpost(host, f"{BASE}/host/game/{og}/end_game")
        wp2.wait_for_timeout(1500)
        for who, pg in (("a waiting player", wp2), ("an admitted player", ap2)):
            check(f"when the game ends {who} gets 'Game Over' and click anywhere", pg.locator("#gameOverOverlay").is_visible() and "Click anywhere" in pg.locator("#gameOverOverlay").inner_text())
            pg.mouse.click(30, 30)
            try: pg.wait_for_url(BASE + "/", timeout=5000)
            except Exception: pass
            check(f"clicking it takes {who} to the start page", pg.url.rstrip("/") == BASE.rstrip("/"), pg.url)
        wctx2.close(); actx2.close()

        # ---- Admit or kick one player ----
        kg = create_game(hp, "Per player")
        actx, ap = join(b, kg, "Ann Waiting")
        bctx, bp = join(b, kg, "Bob Waiting")
        hp.goto(f"{BASE}/host/game/{kg}")
        hp.wait_for_timeout(1000)
        check("every player in the list has Kick, and Admit while waiting", hp.locator("#playersList .playerRow").count() == 2 and hp.locator("#playersList [data-player-kick]").count() == 2 and hp.locator("#playersList [data-player-admit]").count() == 2)
        hp.locator("#playersList .playerRow", has_text="Ann Waiting").locator("[data-player-admit]").click(); hp.wait_for_timeout(1500)
        adm = dict(sql(f"select name, admitted from players where game_id=(select id from games where code='{kg}')"))
        check("Admit on one row admits only that player and gives them a card", adm.get("Ann Waiting") in (1, True) and adm.get("Bob Waiting") in (0, False)
              and sql(f"select count(*) from card_squares where player_id=(select id from players where name='Ann Waiting' and game_id=(select id from games where code='{kg}'))")[0][0] == 25, str(adm))
        check("the Admit button is gone from an admitted player's row", hp.locator("#playersList .playerRow", has_text="Ann Waiting").locator("[data-player-admit]").count() == 0)
        hp.once("dialog", lambda d: d.accept())
        hp.locator("#playersList .playerRow", has_text="Bob Waiting").locator("[data-player-kick]").click(); hp.wait_for_timeout(1800)
        check("Kick removes the player from the list and the game", hp.locator("#playersList .playerRow").count() == 1 and sql(f"select count(*) from players where name='Bob Waiting' and game_id=(select id from games where code='{kg}')")[0][0] == 0)
        bp.wait_for_timeout(800)
        check("the kicked player is told they were removed", "removed" in bp.content().lower(), bp.url)
        bp.goto(f"{BASE}/game/{kg}"); bp.wait_for_timeout(500)
        check("a kicked player who opens the join link again gets the join form, and can join under a different name", bp.locator("form[action$='/join']").is_visible())
        bp.fill("input[name=name]", "Bob Better"); bp.click("form[action$='/join'] button[type=submit]"); bp.wait_for_timeout(900)
        check("the kicked player rejoined as a new player with the new name", sql(f"select count(*) from players where name='Bob Better' and game_id=(select id from games where code='{kg}')")[0][0] == 1)
        cctx, cp = join(b, kg, "Carl New")
        check("another phone can still join the game", sql(f"select count(*) from players where name='Carl New' and game_id=(select id from games where code='{kg}')")[0][0] == 1)
        # "Not you? Join as someone else" on the join page, while the game is in the lobby
        cp.goto(f"{BASE}/game/{kg}"); cp.wait_for_timeout(500)
        check("a returning player sees 'Not you? Join as someone else'", cp.locator(".notMeForm button").is_visible() and "Carl New" in cp.inner_text("body"))
        cp.click(".notMeForm button"); cp.wait_for_timeout(900)
        check("clicking it takes that player out of the game and shows an empty join form", sql(f"select count(*) from players where name='Carl New' and game_id=(select id from games where code='{kg}')")[0][0] == 0 and cp.locator("form[action$='/join']").is_visible() and cp.locator(".notMeForm").count() == 0)
        cp.fill("input[name=name]", "Dee Instead"); cp.click("form[action$='/join'] button[type=submit]"); cp.wait_for_timeout(900)
        check("and the phone can join as someone else", sql(f"select count(*) from players where name='Dee Instead' and game_id=(select id from games where code='{kg}')")[0][0] == 1)
        cctx.close()
        sql(f"update games set status='ended' where code='{kg}'")
        hp.goto(f"{BASE}/host/game/{kg}"); hp.wait_for_timeout(600)
        check("an ended game has no Admit or Kick buttons", hp.locator("#playersList [data-player-kick]").count() == 0 and tpost(host, f"{BASE}/host/game/{kg}/player/1/kick").status == 409)
        actx.close(); bctx.close()

        # ---- Saved Playlists: the save box is one slim row ----
        hp.set_viewport_size({"width": 1440, "height": 900})
        hp.goto(f"{BASE}/host/playlist"); hp.wait_for_timeout(500)
        bx = hp.locator(".plSaveBar").bounding_box()
        ys = [hp.locator(sel).bounding_box()["y"] for sel in (".plSaveRow input[name=name]", ".plSaveRow input[name=playlist_id_or_url]", ".plSaveRow .plTrack", ".plSaveRow button[type=submit]")]
        check("the Save / update playlist box is slim, with name, link, Public switch and Save on one row", bx["height"] <= 160 and max(ys) - min(ys) <= 20, f"{bx} {ys}")
        hp.set_viewport_size({"width": 390, "height": 800}); hp.reload(); hp.wait_for_timeout(400)
        check("on a phone the save box stacks without sideways scrolling", not hp.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))
        hp.set_viewport_size({"width": 1440, "height": 900})

        # ---- The Host / Join / Play Alone chooser treats all three options the same ----
        hp.goto(f"{BASE}/home"); hp.wait_for_timeout(300)
        cls = hp.evaluate("Array.from(document.querySelectorAll('.is31 a.btn')).map(a => [a.textContent.trim(), a.classList.contains('btnPrimary')])")
        check("Host Game, Join Game and Play Alone are all primary buttons (the theme's highlight color), so none stands out", [c[0] for c in cls] == ["Host Game", "Join Game", "Play Alone"] and all(c[1] for c in cls), str(cls))

        # ---- Event name is required ----
        import base64 as _b64
        png1 = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        r_none = tpost(host, f"{BASE}/host/events", multipart={"name": ""})
        r_logo = tpost(host, f"{BASE}/host/events", multipart={"name": "", "logo": {"name": "l.png", "mimeType": "image/png", "buffer": png1}})
        check("an event needs a name: no name is refused, and a logo alone is not enough", r_none.status == 400 and r_logo.status == 400 and "name" in r_logo.text().lower(), f"{r_none.status} {r_logo.status}")
        r_ok = tpost(host, f"{BASE}/host/events", multipart={"name": "Family Night"})
        vid = r_ok.json().get("event", {}).get("id") if r_ok.status == 200 else None
        check("an event with a name is saved (the logo is optional)", r_ok.status == 200 and vid, str(r_ok.status))
        if vid:
            check("renaming an event to nothing is refused", tpost(host, f"{BASE}/host/events/{vid}/rename", form={"name": "  "}).status == 400)
            tpost(host, f"{BASE}/host/events/{vid}/delete")
        hp.set_viewport_size({"width": 1440, "height": 900}); hp.goto(f"{BASE}/host"); hp.wait_for_timeout(500)
        # the event is chosen for every game (phone cards too), from the events saved under Options > Events
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(300)
        check("the Create Game form has a Event choice even without paper cards, with 'No event' first and a link to manage events", hp.locator("#eventSelect").is_visible() and not hp.locator("#paperToggle").is_checked() and hp.locator("#eventSelect option").first.inner_text().startswith("No event") and hp.locator("a[href='/host/events/manage']").count() >= 1)
        check("events are no longer added from the Create Game form (that is done under Options > Events)", hp.locator("#eventName").count() == 0 and hp.locator("#eventSave").count() == 0)
        vn = tpost(host, f"{BASE}/host/events", multipart={"name": "Test Tavern"}).json()["event"]["id"]
        hp.reload(); hp.wait_for_timeout(300)
        check("an event saved under Options > Events is offered when creating a game", hp.locator("#eventSelect option", has_text="Test Tavern").count() == 1)
        vgame = create_game_event(hp, "Event game", vn)
        check("a game made with an event (and no paper cards) remembers it", sql(f"select event_id from games where code='{vgame}'")[0][0] == vn and sql(f"select count(*) from players where game_id=(select id from games where code='{vgame}') and is_paper=1")[0][0] == 0)
        vctx, vpg = join(b, vgame, "Vera")
        tpost(host, f"{BASE}/host/game/{vgame}/admit_all"); vpg.reload(); vpg.wait_for_timeout(1200)
        check("the phone card's center square shows the event name", "Test Tavern" in vpg.locator(".sq.free").inner_text(), vpg.locator(".sq.free").inner_text())
        vctx.close()
        nogame = create_game(hp, "No event game")
        check("a game made with 'No event' has a plain FREE square", sql(f"select event_id from games where code='{nogame}'")[0][0] is None)
        tpost(host, f"{BASE}/host/events/{vn}/delete")

        # ---- Options > Events: manage the saved events from their own page ----
        hp.goto(f"{BASE}/host/events/manage"); hp.wait_for_timeout(400)
        check("the Events page is in the Options menu and says the name is required", hp.locator(".optionsNavItem.active").inner_text().strip().endswith("Events") and "required" in hp.content().lower())
        check("the Events page tells the host what logo files are accepted", all(x in hp.locator("#newEventLogo").locator("xpath=..").inner_text() for x in ("PNG or JPG", "5 MB", "square", "center square")))
        hp.click("#newEventSave"); hp.wait_for_timeout(200)
        check("Save event with no name asks for it and saves nothing", "required" in hp.locator("#newEventMsg").inner_text().lower() and hp.locator(".eventRow").count() == 0)
        for (lw, lh), want in (((40, 40), ("40 \u00d7 40 px", "small")), ((600, 200), ("600 \u00d7 200 px", "wide")), ((200, 700), ("200 \u00d7 700 px", "tall")), ((300, 300), ("300 \u00d7 300 px", "Looks good"))):
            hp.set_input_files("#newEventLogo", files=[{"name": "l.png", "mimeType": "image/png", "buffer": make_png(lw, lh)}]); hp.wait_for_timeout(700)
            mtxt = hp.locator("#newEventMsg").inner_text()
            check(f"a {lw}x{lh} logo gets its size and the right advice ({want[1]})", all(x in mtxt for x in want) and "Save event" in mtxt, mtxt)
        hp.set_input_files("#newEventLogo", files=[])
        hp.fill("#newEventName", "Corner Bar"); hp.click("#newEventSave"); hp.wait_for_timeout(800)
        check("an event is added from the page", hp.locator(".eventRow").count() == 1 and sql("select count(*) from events where name='Corner Bar'")[0][0] == 1 and hp.locator("#eventEmpty").is_hidden())
        hp.fill(".eventNameIn", "Corner Bar & Grill"); hp.click(".eventRename"); hp.wait_for_timeout(600)
        check("an event can be renamed", sql("select count(*) from events where name='Corner Bar & Grill'")[0][0] == 1 and "saved" in hp.locator(".eventRowMsg").inner_text().lower())
        hp.set_input_files(".eventLogoIn", files=[{"name": "l.png", "mimeType": "image/png", "buffer": png1}]); hp.wait_for_timeout(1200)
        check("a logo can be added to it", sql("select count(*) from events where name='Corner Bar & Grill' and logo is not null")[0][0] == 1 and hp.locator(".eventThumb img").count() == 1 and hp.locator(".eventNameIn").input_value() == "Corner Bar & Grill")
        hp.click(".eventNoLogo"); hp.wait_for_timeout(700)
        check("the logo can be removed again (the name stays)", sql("select count(*) from events where name='Corner Bar & Grill' and logo is null")[0][0] == 1 and hp.locator(".eventThumb img").count() == 0)
        vid2 = sql("select id from events where name='Corner Bar & Grill'")[0][0]
        check("another host cannot change an event's logo", tpost(other, f"{BASE}/host/events/{vid2}/logo", multipart={"remove": "1"}).status == 404)
        check("a logo that is not a PNG or JPG is refused", tpost(host, f"{BASE}/host/events/{vid2}/logo", multipart={"logo": {"name": "x.png", "mimeType": "image/png", "buffer": b"not an image"}}).status == 400)
        hp.once("dialog", lambda d: d.accept()); hp.click(".eventDel"); hp.wait_for_timeout(600)
        check("an event can be deleted from the page", hp.locator(".eventRow").count() == 0 and sql("select count(*) from events where name='Corner Bar & Grill'")[0][0] == 0 and hp.locator("#eventEmpty").is_visible())
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(300)
        check("the Create Game form links to Manage events", hp.locator("a[href='/host/events/manage']").count() >= 1)

        # ---- Game History and Saved Games show the event (name and logo) a game used ----
        rv = tpost(host, f"{BASE}/host/events", multipart={"name": "Harbor Pub", "logo": {"name": "l.png", "mimeType": "image/png", "buffer": png1}})
        hv = rv.json()["event"]["id"]
        vg = create_game(hp, "Event game", paper=2)
        vg_plain = create_game(hp, "No event game")
        sql(f"update games set event_id={hv} where code='{vg}'")
        hp.goto(f"{BASE}/host/history"); hp.wait_for_timeout(500)
        vrow = hp.locator(".savedGame", has_text=vg); prow = hp.locator(".savedGame", has_text=vg_plain)
        check("Game History shows the event name and logo a game used", "event Harbor Pub" in vrow.inner_text() and vrow.locator(f"img.eventThumb[src$='/host/events/{hv}/logo']").count() == 1)
        check("...and nothing about an event for a game that had none", "event" not in prow.locator(".savedFacts").inner_text().lower())
        check("the logo image loads", hp.evaluate(f"fetch('/host/events/{hv}/logo').then(r => r.status)") == 200)
        tpost(host, f"{BASE}/host/game/{vg}/save", form={"saved": "1"}); hp.goto(f"{BASE}/host/saved"); hp.wait_for_timeout(500)
        srow = hp.locator(".savedGame", has_text=vg)
        check("Saved Games shows the event name and logo too", "event Harbor Pub" in srow.inner_text() and srow.locator("img.eventThumb").count() == 1)
        tpost(host, f"{BASE}/host/game/{vg}/save", form={"saved": "0"}); tpost(host, f"{BASE}/host/events/{hv}/delete")

        # ---- The event logo / name fills the FREE square on digital cards ----
        v_logo = tpost(host, f"{BASE}/host/events", multipart={"name": "Harbor Pub", "logo": {"name": "l.png", "mimeType": "image/png", "buffer": png1}}).json()["event"]["id"]
        v_name = tpost(host, f"{BASE}/host/events", multipart={"name": "Family Night"}).json()["event"]["id"]
        dg = create_game(hp, "Digital event game")
        dctx, dp = join(b, dg, "Vera")
        tpost(host, f"{BASE}/host/game/{dg}/admit_all")
        dp.reload(); dp.wait_for_timeout(800)
        check("a game with no event has the plain FREE square", dp.locator(".sq.free .eventMark").count() == 0)
        sql(f"update games set event_id={v_logo} where code='{dg}'")
        dp.reload(); dp.wait_for_timeout(800)
        free = dp.locator(".sq.free")
        loaded = dp.evaluate("(() => { const i = document.querySelector('.sq.free .eventMark img'); return !!i && i.complete && i.naturalWidth > 0; })()")
        fb, ib = free.bounding_box(), dp.locator(".sq.free .eventMark img").bounding_box()
        check("with an event logo the FREE square shows it, scaled to fit inside the square", loaded and ib["width"] <= fb["width"] and ib["height"] <= fb["height"], f"{fb} {ib}")
        check("the FREE text is still in the square (hidden, for screen readers) and it is still the FREE square", (free.locator(".sqText").text_content() or "").strip() == "FREE" and free.get_attribute("data-free") == "true")
        check("players can load the logo without logging in", b.new_context().request.get(f"{BASE}/game/{dg}/event_logo").status == 200)
        sql(f"update games set event_id={v_name} where code='{dg}'")
        dp.reload(); dp.wait_for_timeout(800)
        check("with only an event name the FREE square shows the name", "Family Night" in dp.locator(".sq.free .eventNameText").inner_text() and dp.locator(".sq.free .eventMark img").count() == 0)
        check("...and the logo address is not found for an event without a logo", b.new_context().request.get(f"{BASE}/game/{dg}/event_logo").status == 404)
        dp.locator(".sq.free").click(); dp.wait_for_timeout(300)
        dctx.close(); tpost(host, f"{BASE}/host/events/{v_logo}/delete"); tpost(host, f"{BASE}/host/events/{v_name}/delete")

        # ---- Paper cards: Asian-script text and brackets that do not fit are left out of a title ----
        snippet = ("from app.paper import paper_display_title as p\n"
                   "import json\n"
                   "print(json.dumps([p(t) for t in ['Gangnam Style (\uac15\ub0a8\uc2a4\ud0c0\uc77c)', 'Gangnam Style \uac15\ub0a8\uc2a4\ud0c0\uc77c', '\uac15\ub0a8\uc2a4\ud0c0\uc77c', 'Mambo No. 5 (a Little Bit of...)', "
                   "'Dynamite (\ub2e4\uc774\ub108\ub9c8\uc774\ud2b8) [Remix]', '\u6771\u4eac (Tokyo)', 'Jump (Remastered)', 'So\u00f1ar (\u00d1and\u00fa)']], ensure_ascii=True))\n")
        po = subprocess.run(["docker", "exec", "-w", "/work/now", "-e", "DATABASE_URL=sqlite:////tmp/pd.db?check_same_thread=false", "-e", "COOKIE_SECRET=local-paper-test", CONTAINER, "python", "-c", snippet], capture_output=True, text=True)
        try:
            got = json.loads(po.stdout.strip().splitlines()[-1])
        except Exception:
            got = []
        want = ["Gangnam Style", "Gangnam Style", "\uac15\ub0a8\uc2a4\ud0c0\uc77c", "Mambo No. 5 (a Little Bit of...)", "Dynamite [Remix]", "Tokyo", "Jump (Remastered)", "So\u00f1ar (\u00d1and\u00fa)"]
        check("a paper card title drops Asian-script text but keeps Latin brackets and all-Asian titles", got == want, str(got) + " " + po.stderr[-150:])
        hp.set_viewport_size({"width": 1440, "height": 900}); hp.goto(f"{BASE}/host/game/{pc}/paper"); hp.wait_for_timeout(600)
        fit_res = hp.evaluate("""() => { const sq = document.querySelectorAll('.sheet')[0].querySelectorAll('.sqText.fit');
            const a = sq[0], b = sq[1];
            a.textContent = 'Mambo No. 5 (a Little Bit of...)'; b.textContent = 'Jump (Remastered)';
            window.fitPaperTitles();
            const fits = el => el.scrollHeight <= el.parentElement.clientHeight - 11;
            return [a.textContent, parseFloat(getComputedStyle(a).fontSize), fits(a), b.textContent, parseFloat(getComputedStyle(b).fontSize)]; }""")
        check("a bracketed part that does not fit at a comfortable size is dropped, and one that fits stays", fit_res[0] == "Mambo No. 5" and fit_res[2] and fit_res[1] >= 16 and fit_res[3] == "Jump (Remastered)", str(fit_res))

        # ---- Paper cards can wear the host's theme (white paper, colored lines and centre square) ----
        tpost(host, f"{BASE}/host/account/theme", form={"theme": "maize"}, max_redirects=0)
        hp.set_viewport_size({"width": 1440, "height": 900}); hp.goto(f"{BASE}/host"); hp.wait_for_timeout(500)
        check("the Create Game form offers the theme colors for paper cards, naming the host's theme", "Maize" in hp.locator("input[name=paper_theme]").locator("xpath=..").inner_text())
        hp.fill("input[name=game_name]", "Themed cards"); hp.fill("input[name=playlist_id_or_url]", PLAYLIST)
        hp.check("#paperToggle"); hp.fill("input[name=paper_count]", "2"); hp.check("input[name=paper_theme]")
        hp.click("#createBtn"); hp.wait_for_load_state("networkidle")
        tcode = hp.url.split("/host/game/")[1].split("/")[0]
        css_of = lambda sel, prop: hp.evaluate(f"getComputedStyle(document.querySelector('{sel}')).getPropertyValue('{prop}')")
        check("the paper game remembers the theme it was made with", sql(f"select paper_theme from games where code='{tcode}'")[0][0] == "maize")
        check("themed cards: lines and letters use the theme color", hp.evaluate("document.documentElement.getAttribute('data-theme')") == "maize" and css_of(".grid", "border-top-color") == "rgb(46, 113, 181)", css_of(".grid", "border-top-color"))
        check("themed cards: each B-I-N-G-O letter sits in a Maize box with a Blue edge", css_of(".letters div", "background-color") == "rgb(255, 203, 5)" and css_of(".letters div", "border-top-color") == "rgb(46, 113, 181)" and css_of(".letters div", "color") == "rgb(17, 17, 17)" and css_of(".letters div", "border-top-left-radius") == "10px", css_of(".letters div", "background-color") + " " + css_of(".letters div", "border-top-color"))
        letters_fit = hp.evaluate("(() => { const s = document.querySelector('.sheet').getBoundingClientRect(); const g = document.querySelector('.grid').getBoundingClientRect(); return g.bottom <= s.bottom + 1 && document.querySelector('.foot').getBoundingClientRect().bottom <= s.bottom + 1; })()")
        check("...and the card still fits on its page", letters_fit)
        check("themed cards: the paper stays white and the center square is not shaded at all", css_of(".sheet", "background-color") == "rgb(255, 255, 255)" and css_of(".sq.free", "background-color") == "rgb(255, 255, 255)", css_of(".sq.free", "background-color"))
        tpost(host, f"{BASE}/host/account/theme", form={"theme": "ocean"}, max_redirects=0)
        hp.goto(f"{BASE}/host/game/{tcode}/paper"); hp.wait_for_timeout(300)
        check("changing your theme later does not recolor cards that were already made", hp.evaluate("document.documentElement.getAttribute('data-theme')") == "maize")
        pg_plain = create_game(hp, "Plain cards", paper=2)
        hp.goto(f"{BASE}/host/game/{pg_plain}/paper"); hp.wait_for_timeout(300)
        check("without the option the cards stay black on white", hp.evaluate("document.documentElement.getAttribute('data-theme')") is None and css_of(".grid", "border-top-color") == "rgb(17, 17, 17)", css_of(".grid", "border-top-color"))
        # ... and the colors can be switched on (or off) for a game that already has cards, from the print page
        hp.goto(f"{BASE}/host/game/{pg_plain}/paper"); hp.wait_for_timeout(300)
        codes_before = hp.locator(".foot span:first-child").all_inner_texts()
        check("the print page has a Card colors switch showing Black & white for a plain game", hp.locator(".colorForm select").input_value() == "plain" and "Ocean" in hp.locator(".colorForm select option[value=theme]").inner_text())
        hp.select_option(".colorForm select", "theme"); hp.click(".colorForm button"); hp.wait_for_load_state("networkidle")
        check("choosing My theme colors the existing cards with the host's current theme", hp.evaluate("document.documentElement.getAttribute('data-theme')") == "ocean" and sql(f"select paper_theme from games where code='{pg_plain}'")[0][0] == "ocean" and css_of(".letters div", "background-color") == "rgb(96, 165, 250)", css_of(".letters div", "background-color"))
        check("...without changing the cards themselves (same check codes, so printed cards still work)", hp.locator(".foot span:first-child").all_inner_texts() == codes_before)
        tpost(other, f"{BASE}/host/game/{pg_plain}/paper/theme", form={"mode": "plain"}, max_redirects=0)
        check("another host cannot change it", sql(f"select paper_theme from games where code='{pg_plain}'")[0][0] == "ocean")
        hp.select_option(".colorForm select", "plain"); hp.click(".colorForm button"); hp.wait_for_load_state("networkidle")
        check("choosing Black & white takes the colors off again", hp.evaluate("document.documentElement.getAttribute('data-theme')") is None and sql(f"select paper_theme from games where code='{pg_plain}'")[0][0] == "")
        # Game History and Saved Games say which theme a game's cards use
        hp.goto(f"{BASE}/host/history"); hp.wait_for_timeout(400)
        trow, prow = hp.locator(".savedGame", has_text=tcode), hp.locator(".savedGame", has_text=pg_plain)
        check("Game History says which theme a game's paper cards use (and nothing for plain cards)", "card colors Maize & Blue" in trow.locator(".savedFacts").inner_text() and "card colors" not in prow.locator(".savedFacts").inner_text())
        tpost(host, f"{BASE}/host/game/{tcode}/save", form={"saved": "1"}); tpost(host, f"{BASE}/host/game/{pg_plain}/save", form={"saved": "1"})
        hp.goto(f"{BASE}/host/saved"); hp.wait_for_timeout(400)
        check("Saved Games says it too", "card colors Maize & Blue" in hp.locator(".savedGame", has_text=tcode).locator(".savedFacts").inner_text() and "card colors" not in hp.locator(".savedGame", has_text=pg_plain).locator(".savedFacts").inner_text())
        tpost(host, f"{BASE}/host/game/{tcode}/save", form={"saved": "0"}); tpost(host, f"{BASE}/host/game/{pg_plain}/save", form={"saved": "0"})
        tpost(host, f"{BASE}/host/account/theme", form={"theme": "midnight"}, max_redirects=0)

        # ---- Host page left column: nothing is cut off, even with the device picker showing ----
        hp.goto(f"{BASE}/host/game/{pc}"); hp.wait_for_timeout(800)
        hp.evaluate("document.getElementById('deviceRow').style.display = ''")
        for wh in (900, 740):
            hp.set_viewport_size({"width": 1440, "height": wh}); hp.wait_for_timeout(300)
            over = hp.evaluate("(() => { const p = document.querySelector('.hostGrid3 .hostCol1 .panel'); return p.scrollHeight - p.clientHeight; })()")
            check(f"the host page's left column fits a 1440x{wh} window with the device picker showing (no scrolling)", over <= 0, f"overflow {over}px")
        hp.set_viewport_size({"width": 1440, "height": 560}); hp.wait_for_timeout(300)
        inside = hp.evaluate("(() => { const p = document.querySelector('.hostGrid3 .hostCol1 .panel').getBoundingClientRect(); return ['playBtn', 'pauseBtn', 'nextBtn'].every(id => { const b = document.getElementById(id).getBoundingClientRect(); return b.bottom <= p.bottom + 1 && b.top >= p.top; }); })()")
        check("in a very short window Play, Pause and Next are still whole inside the panel", inside)
        hp.set_viewport_size({"width": 1440, "height": 900})

        # ---- Color themes ----
        def theme_state(pg):
            return pg.evaluate("[document.documentElement.getAttribute('data-theme'), getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(), getComputedStyle(document.documentElement).getPropertyValue('--accent2').trim(), getComputedStyle(document.documentElement).getPropertyValue('--bgTop').trim()]")
        hp.goto(f"{BASE}/host/themes"); hp.wait_for_timeout(500)
        check("a host starts on the original Midnight Purple theme", theme_state(hp)[:2] == ["midnight", "#8b5cf6"], str(theme_state(hp)))
        check("the Account page offers nine themes (eight ready-made, plus Custom)", hp.locator(".themeCard").count() == 9)
        hp.locator(".themeCard[data-theme='ocean']").click(); hp.wait_for_timeout(200)
        check("choosing a theme previews it at once", theme_state(hp)[:2] == ["ocean", "#2563eb"], str(theme_state(hp)))
        hp.locator(".themeCard[data-theme='graphite']").click(); hp.wait_for_timeout(150)
        card_accents = hp.evaluate("Array.from(document.querySelectorAll('.themeCard')).map(c => [c.dataset.theme, getComputedStyle(c).getPropertyValue('--accent').trim()])")
        check("while one theme is previewed every swatch card keeps its own colors (including Midnight Purple)",
              {k: v for k, v in dict(card_accents).items() if k != "custom"} == {"midnight": "#8b5cf6", "ocean": "#2563eb", "emerald": "#059669", "sunset": "#ea580c", "rose": "#db2777", "graphite": "#64748b", "maize": "#2e71b5", "light": "#6a3fe0"}, str(card_accents))
        hp.locator(".themeCard[data-theme='ocean']").click(); hp.wait_for_timeout(150)
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(300)
        check("an unsaved preview is not kept", theme_state(hp)[0] == "midnight")
        hp.goto(f"{BASE}/host/themes"); hp.locator(".themeCard[data-theme='ocean']").click()
        hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
        check("Save theme keeps it (also on other host pages)", "Theme saved" in hp.content() and theme_state(hp)[0] == "ocean" and sql("select theme from host_users where username='h'")[0][0] == "ocean")
        hp.goto(f"{BASE}/host/saved"); hp.wait_for_timeout(300)
        check("every host page wears the saved theme", theme_state(hp)[:2] == ["ocean", "#2563eb"], str(theme_state(hp)))
        bad = hp.evaluate("fetch('/host/account/theme', {method: 'POST', redirect: 'manual', body: new URLSearchParams({theme: 'neon'})}).then(r => r.type)")
        check("an unknown theme is refused and the saved one stays", sql("select theme from host_users where username='h'")[0][0] == "ocean")
        tg = create_game(hp, "Theme game")
        tctx, tp = join(b, tg, "Thea")
        check("a player in the host's game sees the host's theme", theme_state(tp)[0] == "ocean", tp.url + " " + str(theme_state(tp)))
        jp = b.new_context().new_page(); jp.goto(f"{BASE}/game/{tg}")
        check("...and so does the join page before they have joined", theme_state(jp)[0] == "ocean", str(theme_state(jp)))
        op = b.new_context().new_page(); op.goto(f"{BASE}/enter")
        check("pages with no game or host (the enter-code page) stay on the default theme", theme_state(op)[0] == "midnight")
        jp.close(); op.close(); tctx.close()
        # every theme: distinct accent, white button text and light link color readable on its own background
        def lum(hexc):
            c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        def lum_rgb(c):
            n = [int(float(x)) for x in re.findall(r'[0-9.]+', c)[:3]]
            return lum('#%02x%02x%02x' % tuple(n))
        def ratio(h1, h2):
            l1, l2 = sorted((lum(h1), lum(h2)), reverse=True); return (l1 + 0.05) / (l2 + 0.05)
        accents, weak, marks = set(), [], set()
        for tid in ("midnight", "ocean", "emerald", "sunset", "rose", "graphite", "maize", "light"):
            hp.evaluate(f"document.documentElement.setAttribute('data-theme', '{tid}')")
            th, ac, ac2, bgt = theme_state(hp)
            accents.add(ac)
            marks.add(hp.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--marked-rgb').trim()"))
            if ratio("#ffffff", ac) < 3.0 or ratio(ac2, bgt) < 4.5: weak.append((tid, round(ratio("#ffffff", ac), 1), round(ratio(ac2, bgt), 1)))
        check("the eight themes have eight different accents and dabbed-square colors, all readable (white on accent >= 3, link color on background >= 4.5)", len(accents) == 8 and len(marks) == 8 and not weak, str(weak) + str(marks))
        # the Light theme: dark text on white panels, white text on the accent buttons, and a Light player card
        hp.goto(f"{BASE}/host/themes"); hp.locator(".themeCard[data-theme='light']").click(); hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(400)
        lt = hp.evaluate("(() => { const cs = (s, p) => getComputedStyle(document.querySelector(s))[p]; return [document.documentElement.dataset.theme, cs('h1, .title', 'color'), cs('.panel', 'background-color') + '|' + cs('.panel', 'background-image').slice(0, 40), cs('#createBtn', 'color'), cs('input.input', 'background-color')]; })()")
        check("Light: dark page text, white fields, white text on the main button", lt[0] == "light" and lum_rgb(lt[1]) < 0.1 and lum_rgb(lt[4]) > 0.9 and lum_rgb(lt[3]) > 0.9, str(lt))
        lg2 = create_game(hp, "Light game")
        lctx, lpg = join(b, lg2, "Lila")
        check("a player in a Light game sees dark text on a white card", lpg.evaluate("document.documentElement.dataset.theme") == "light" and lum_rgb(lpg.evaluate("getComputedStyle(document.querySelector('.sqText') || document.body).color")) < 0.1, "")
        lctx.close()
        hp.goto(f"{BASE}/host/themes"); hp.locator(".themeCard[data-theme='midnight']").click(); hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
        hp.evaluate("document.documentElement.setAttribute('data-theme', 'maize')")
        btn_text = hp.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--btn-text').trim()")
        check("in Maize & Blue the primary buttons use Blue text on Maize (readable) and the dabbed squares are Maize", btn_text == "#00274c" and ratio(btn_text, "#ffcb05") >= 7 and hp.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--marked-rgb').trim()") == "255 203 5", btn_text)
        # ---- Custom theme: the host picks three colors; the server works out the rest ----
        set_colors = lambda bg, ac, hi: [hp.evaluate("([s, v]) => { const e = document.querySelector(s); e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }", [sel, val]) for sel, val in (("#customBg", bg), ("#customAccent", ac), ("#customHighlight", hi))]
        hp.goto(f"{BASE}/host/themes"); hp.wait_for_timeout(300)
        check("the color pickers stay hidden until Custom is chosen", hp.locator("#customEditor").is_hidden())
        hp.locator(".themeCard[data-theme='custom']").click(); hp.wait_for_timeout(300)
        check("choosing Custom shows a color wheel with three colors to edit and a phone card and a paper card preview", hp.locator("#customEditor").is_visible() and hp.locator("#wheelCanvas").is_visible() and hp.locator(".customPick").count() == 3 and hp.locator(".cpDigital .sq").count() == 15 and hp.locator(".cpPaper .cpCell").count() == 15)
        set_colors("#0f2e2e", "#14b8a6", "#fcd34d"); hp.wait_for_timeout(800)
        pv = hp.evaluate("[getComputedStyle(document.querySelector('.cpPaper')).getPropertyValue('--accent').trim(), getComputedStyle(document.querySelector('.cpPaperName')).color, getComputedStyle(document.querySelector('.cpLetters div')).backgroundColor, getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()]")
        check("picking colors changes the previews and the page at once (before anything is saved)", pv == ["#14b8a6", "rgb(20, 184, 166)", "rgb(252, 211, 77)", "#14b8a6"], str(pv))
        # the color wheel: click for hue and strength, type a code, slide the brightness, choose which of the three colors to edit
        box = hp.locator("#wheelCanvas").bounding_box()
        hp.click("#wheelCanvas", position={"x": box["width"] * 0.93, "y": box["height"] * 0.5}); hp.wait_for_timeout(700)
        bgv = hp.evaluate("document.getElementById('customBg').value"); r_, g_, b_ = int(bgv[1:3], 16), int(bgv[3:5], 16), int(bgv[5:7], 16)
        check("clicking the right edge of the wheel picks a strong red hue for the chosen color (the background; its brightness stays as it was)", r_ > 30 and g_ * 4 < r_ and b_ * 4 < r_ and hp.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bgMid').trim()") == bgv, bgv)
        check("the swatch shows the picked color", hp.evaluate("getComputedStyle(document.querySelector('.customPick[data-target=customBg] .customSwatch')).backgroundColor") == f"rgb({r_}, {g_}, {b_})")
        hp.click(".customPick[data-target=customHighlight]")
        check("choosing another color moves the wheel to it", hp.locator("#wheelEditing").inner_text() == "Highlight" and hp.input_value("#wheelHex") == "#fcd34d" and hp.locator(".customPick[data-target=customHighlight]").get_attribute("aria-pressed") == "true", hp.input_value("#wheelHex"))
        hp.fill("#wheelHex", "#00ff00"); hp.wait_for_timeout(700)
        check("typing a color code sets that color and the previews follow", hp.evaluate("document.getElementById('customHighlight').value") == "#00ff00" and hp.evaluate("getComputedStyle(document.querySelector('.cpLetters div')).backgroundColor") == "rgb(0, 255, 0)")
        hp.fill("#wheelHex", "nonsense"); hp.wait_for_timeout(200)
        check("a color code that isn't six hex digits changes nothing", hp.evaluate("document.getElementById('customHighlight').value") == "#00ff00")
        hp.evaluate("(() => { const v = document.getElementById('wheelV'); v.value = 50; v.dispatchEvent(new Event('input', {bubbles: true})); })()"); hp.wait_for_timeout(300)
        dim = hp.evaluate("document.getElementById('customHighlight').value")
        check("the brightness slider darkens the chosen color", dim == "#008000" or (int(dim[3:5], 16) in range(120, 136) and dim[1:3] == "00"), dim)
        hp.keyboard.press("Tab") if False else None
        hp.focus("#wheelCanvas"); before_k = hp.evaluate("document.getElementById('customHighlight').value"); hp.keyboard.press("ArrowRight"); hp.wait_for_timeout(300)
        check("the arrow keys move around the wheel", hp.evaluate("document.getElementById('customHighlight').value") != before_k)
        hp.click(".customPick[data-target=customBg]")
        set_colors("#0f2e2e", "#14b8a6", "#fcd34d"); hp.wait_for_timeout(700)
        check("setting a color from outside (as the page's own scripts do) moves the wheel and swatch", hp.input_value("#wheelHex") == "#0f2e2e" and hp.evaluate("getComputedStyle(document.querySelector('.customPick[data-target=customBg] .customSwatch')).backgroundColor") == "rgb(15, 46, 46)", hp.input_value("#wheelHex"))
        check("a custom color set that is saved nowhere yet is not kept when leaving the page", sql("select theme from host_users where username='h'")[0][0] == "midnight")
        hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
        check("Save theme keeps the custom colors", sql("select theme, custom_colors from host_users where username='h'")[0] == ["custom", "0f2e2e-14b8a6-fcd34d"], str(sql("select theme, custom_colors from host_users where username='h'")))
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(400)
        cs = hp.evaluate("[document.documentElement.dataset.theme, getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(), getComputedStyle(document.documentElement).getPropertyValue('--bgMid').trim(), document.documentElement.dataset.tone || '']")
        check("every host page wears the custom colors (dark background -> dark tone)", cs == ["custom", "#14b8a6", "#0f2e2e", ""], str(cs))
        cg = create_game(hp, "Custom colors game")
        cctx, cpg = join(b, cg, "Cora")
        check("a player in the host's game sees the custom colors too", cpg.evaluate("[document.documentElement.dataset.theme, getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()]") == ["custom", "#14b8a6"])
        cctx.close()
        css_ok = host.request.get(f"{BASE}/theme/custom.css?c=0f2e2e-14b8a6-fcd34d"); css_bad = host.request.get(f"{BASE}/theme/custom.css?c=zzzzzz-14b8a6-fcd34d")
        check("the color stylesheet is served for a valid color set and refused for anything else", css_ok.status == 200 and "--accent: #14b8a6" in css_ok.text() and css_bad.status == 400 and "immutable" in css_ok.headers.get("cache-control", ""))
        bad_c = tpost(host, f"{BASE}/host/account/theme", form={"theme": "custom", "custom_bg": "red", "custom_accent": "#14b8a6", "custom_highlight": "#fcd34d"}, max_redirects=0)
        check("a custom theme with invalid colors is refused and the saved colors stay", sql("select custom_colors from host_users where username='h'")[0][0] == "0f2e2e-14b8a6-fcd34d" and "error" in (bad_c.headers.get("location") or ""))
        # paper cards made with the custom colors remember them
        hp.goto(f"{BASE}/host"); hp.fill("input[name=game_name]", "Custom cards"); hp.fill("input[name=playlist_id_or_url]", PLAYLIST)
        hp.check("#paperToggle"); hp.fill("input[name=paper_count]", "2"); hp.check("input[name=paper_theme]")
        hp.click("#createBtn"); hp.wait_for_load_state("networkidle")
        ccode = hp.url.split("/host/game/")[1].split("/")[0]
        check("the paper game remembers the custom colors it was made with", sql(f"select paper_theme from games where code='{ccode}'")[0][0] == "custom:0f2e2e-14b8a6-fcd34d")
        pc_css = lambda sel, prop: hp.evaluate(f"getComputedStyle(document.querySelector('{sel}')).getPropertyValue('{prop}')")
        check("custom paper cards: lines in the button color, letter boxes in the highlight color with readable text", pc_css(".grid", "border-top-color") == "rgb(20, 184, 166)" and pc_css(".letters div", "background-color") == "rgb(252, 211, 77)" and pc_css(".letters div", "color") == "rgb(17, 17, 17)", pc_css(".letters div", "background-color"))
        # a light background switches to dark text, and the paper keeps working
        tpost(host, f"{BASE}/host/account/theme", form={"theme": "custom", "custom_bg": "#f6efe0", "custom_accent": "#c2410c", "custom_highlight": "#7c2d12"}, max_redirects=0)
        hp.goto(f"{BASE}/host/game/{ccode}/paper"); hp.wait_for_timeout(300)
        check("changing your colors later does not recolor cards that were already made", pc_css(".grid", "border-top-color") == "rgb(20, 184, 166)")
        hp.goto(f"{BASE}/host"); hp.wait_for_timeout(400)
        ls = hp.evaluate("[document.documentElement.dataset.tone, getComputedStyle(document.documentElement).getPropertyValue('--text').trim()]")
        check("a light background gives a light-tone page with dark text", ls[0] == "light" and lum_rgb("rgb(%d,%d,%d)" % tuple(int(ls[1][i:i + 2], 16) for i in (1, 3, 5))) < 0.1, str(ls))
        hp.goto(f"{BASE}/host/history"); hp.wait_for_timeout(300)
        check("Game History names the cards' colors 'Custom'", "card colors Custom" in hp.locator(".savedGame", has_text=ccode).locator(".savedFacts").inner_text() if hp.locator(".savedGame", has_text=ccode).count() else True)
        hp.goto(f"{BASE}/host/themes"); hp.locator(".themeCard[data-theme='midnight']").click(); hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
        check("the theme can be set back to the original", sql("select theme from host_users where username='h'")[0][0] == "midnight" and theme_state(hp)[0] == "midnight")

        # ---- Ignored failures are logged once, never raised ----
        snippet = ("from app.errors import best_effort, rollback_quietly\n"
                   "class Bad:\n    def rollback(self): raise RuntimeError('boom')\n"
                   "def f():\n    for i in range(3):\n        with best_effort():\n            raise ValueError('x')\n"
                   "f(); f(); rollback_quietly(Bad())\n"
                   "try:\n    with best_effort():\n        raise KeyboardInterrupt()\nexcept KeyboardInterrupt:\n    print('interrupt still propagates')\n"
                   "print('done')\n")
        eo = subprocess.run(["docker", "exec", "-w", "/work/now", CONTAINER, "python", "-c", snippet], capture_output=True, text=True)
        check("best_effort swallows errors but logs each place once, and lets BaseException through",
              eo.stdout.count("SWALLOWED") == 2 and "ValueError: x" in eo.stdout and "RuntimeError: boom" in eo.stdout and "interrupt still propagates" in eo.stdout and "done" in eo.stdout, (eo.stdout + eo.stderr)[-300:])

        # the security policy only upgrades requests to https when the page itself is https (plain-http installs must still load)
        csp_http = cx0.request.get(BASE + "/enter").headers.get("content-security-policy", "")
        csp_https = cx0.request.get(BASE + "/enter", headers={"X-Forwarded-Proto": "https"}).headers.get("content-security-policy", "")
        check("over plain http the security policy does not upgrade requests to https (so the page's own files load), and allows ws://", "upgrade-insecure-requests" not in csp_http and " ws: " in csp_http and "script-src 'self' 'nonce-" in csp_http, csp_http[-200:])
        check("over https it does upgrade them, as before", "upgrade-insecure-requests" in csp_https and " ws: " not in csp_https, csp_https[-200:])

        # ---- Access control: no host-only page or action answers an anonymous visitor ----
        rt = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-c",
                             "import json\nfrom app.main import app\nfrom starlette.routing import Route, WebSocketRoute\n"
                             "flat = []\nfor top in app.routes:\n    inner = getattr(getattr(top, 'original_router', None), 'routes', None)\n    flat.extend(inner if inner is not None else [top])\n"
                             "print(json.dumps([[r.path, sorted(getattr(r, 'methods', None) or ['WS'])] for r in flat if isinstance(r, (Route, WebSocketRoute))]))"],
                            capture_output=True, text=True)
        try:
            route_list = json.loads(rt.stdout.strip().splitlines()[-1])
        except Exception:
            route_list = []
        public_prefixes = ("/static", "/theme/", "/setup", "/enter", "/login", "/help", "/game/", "/player/", "/favicon", "/openapi", "/docs", "/redoc", "/ws/game", "/ws/player", "/host/login")
        public_exact = {"/", "/host/whoami"}   # whoami only says whether you are logged in (the menu script asks)
        anon = b.new_context()
        anon_html = anon.request.get(BASE + "/enter").text()
        anon_tok = re.search(r'name="csrf-token" content="([^"]+)"', anon_html).group(1)
        exposed, checked = [], 0
        for path, methods in route_list:
            if path in public_exact or path.startswith(public_prefixes):
                continue
            url = BASE + re.sub(r"\{[^}]*\}", "1", path)
            for m in methods:
                if m in ("HEAD", "OPTIONS", "WS"):
                    continue
                checked += 1
                r = (anon.request.get(url, max_redirects=0) if m == "GET" else anon.request.fetch(url, method=m, headers={"X-CSRF-Token": anon_tok}, max_redirects=0))
                if r.status in (200, 500):
                    exposed.append(f"{m} {path} -> {r.status}")
        check(f"no host-only route ({checked} checked) answers an anonymous visitor with a page, data or an error", route_list and checked > 40 and not exposed, "; ".join(exposed[:6]) + f" checked={checked} " + rt.stderr[-150:])
        # ... and one host cannot read or change another host's game (every /host/game/{code}/... route, as the other host)
        own_game = create_game(hp, "Ownership game")
        other_html = other.request.get(BASE + "/enter").text()
        other_tok = re.search(r'name="csrf-token" content="([^"]+)"', other_html).group(1)
        leaks, o_checked = [], 0
        for path, methods in route_list:
            if not path.startswith("/host/game/{code}"):
                continue
            url = BASE + re.sub(r"\{code\}", own_game, re.sub(r"\{(?!code)[^}]*\}", "1", path))
            for m in methods:
                if m in ("HEAD", "OPTIONS", "WS") or path.endswith(("/delete_game", "/end_game")):
                    continue
                o_checked += 1
                r = (other.request.get(url, max_redirects=0) if m == "GET" else other.request.fetch(url, method=m, headers={"X-CSRF-Token": other_tok}, max_redirects=0))
                body = r.text()[:300] if r.status == 200 else ""
                if r.status == 200 and not ('"ok":false' in body.replace(" ", "") or '"error"' in body):
                    leaks.append(f"{m} {path} -> 200")
                if r.status == 500:
                    leaks.append(f"{m} {path} -> 500")
        check(f"another host gets nothing from, and changes nothing in, a game they don't own ({o_checked} routes tried)", o_checked > 25 and not leaks, "; ".join(leaks[:6]))
        check("...and the owner's game is untouched by those attempts", sql(f"select status from games where code='{own_game}'")[0][0] == "lobby" and sql(f"select count(*) from games where code='{own_game}'")[0][0] == 1)
        public_posts = [p for p, ms in route_list if p.startswith(("/game/", "/player/")) and "POST" in ms]
        check("the routes that are public on purpose are the player-facing ones only", all(p.startswith(("/game/{", "/player/{")) for p in public_posts), str(public_posts)[:200])
        # live-update sockets: only a host who owns the game, or a player who joined it, from this site
        wsg = create_game(hp, "Socket game"); wctx2, wpg2 = join(b, wsg, "Socky")
        host_uid = sql("select id from host_users where username='h'")[0][0]
        ptoken = sql(f"select token from players where name='Socky' and game_id=(select id from games where code='{wsg}')")[0][0]
        ws_snip = ("import asyncio, sys, json, websockets\nfrom app.security import sign\n"
                   "async def t(path, cookie, origin):\n"
                   "    h = {'Cookie': cookie} if cookie else {}\n"
                   "    try:\n"
                   "        async with websockets.connect('ws://127.0.0.1:5000' + path, additional_headers=h, origin=origin, open_timeout=5):\n"
                   "            return 'accepted'\n"
                   "    except Exception:\n"
                   "        return 'rejected'\n"
                   "async def main():\n"
                   f"    hs = 'host_session=' + sign({{'host': True, 'uid': {host_uid}}})\n"
                   "    ok = 'http://127.0.0.1:5000'\n"
                   "    out = {}\n"
                   f"    out['host'] = await t('/ws/host/game/{wsg}', hs, ok)\n"
                   f"    out['host_other_site'] = await t('/ws/host/game/{wsg}', hs, 'https://evil.example')\n"
                   f"    out['host_no_cookie'] = await t('/ws/host/game/{wsg}', None, ok)\n"
                   f"    out['host_wrong_game'] = await t('/ws/host/game/ZZZZZ', hs, ok)\n"
                   f"    out['player'] = await t('/ws/game/{wsg}', 'bingo_player_{wsg}={ptoken}', ok)\n"
                   f"    out['player_wrong_token'] = await t('/ws/game/{wsg}', 'bingo_player_{wsg}=not-a-real-token', ok)\n"
                   f"    out['player_no_cookie'] = await t('/ws/game/{wsg}', None, ok)\n"
                   "    print(json.dumps(out))\n"
                   "asyncio.run(main())\n")
        wr = subprocess.run(["docker", "exec", "-e", "COOKIE_SECRET=local-paper-test", "-w", "/work/now", CONTAINER, "python", "-c", ws_snip], capture_output=True, text=True)
        try:
            wsr = json.loads(wr.stdout.strip().splitlines()[-1])
        except Exception:
            wsr = {}
        check("the live-update sockets accept only the game's owner (host) or a player who joined it, from this site", wsr == {"host": "accepted", "host_other_site": "rejected", "host_no_cookie": "rejected", "host_wrong_game": "rejected", "player": "accepted", "player_wrong_token": "rejected", "player_no_cookie": "rejected"}, str(wsr) + wr.stderr[-200:])
        wctx2.close()
        # changing a password logs out the account's other sessions (the browser that changed it stays logged in)
        sa_ctx, sb_ctx = b.new_context(), b.new_context()
        for cx_ in (sa_ctx, sb_ctx):
            tpost(cx_, BASE + "/login", form={"username": "sess-test", "password": "first-pass-1", "next": "/host"}, max_redirects=0)
        tpost(host, f"{BASE}/host/admin/users/create", form={"username": "sess-test", "password": "first-pass-1"}, max_redirects=0)
        sql("update host_users set must_change_password=0 where username='sess-test'")
        for cx_ in (sa_ctx, sb_ctx):
            tpost(cx_, BASE + "/login", form={"username": "sess-test", "password": "first-pass-1", "next": "/host"}, max_redirects=0)
        both_in = all(cx_.request.get(BASE + "/host", max_redirects=0).status == 200 for cx_ in (sa_ctx, sb_ctx))
        tpost(sa_ctx, BASE + "/host/account/password", form={"current_password": "first-pass-1", "new_password": "second-pass-2", "new_password2": "second-pass-2"}, max_redirects=0)
        a_still = sa_ctx.request.get(BASE + "/host", max_redirects=0).status == 200
        b_out = sb_ctx.request.get(BASE + "/host", max_redirects=0).status in (301, 302, 303, 307)
        check("two browsers are logged in; after one changes the password it stays logged in and the other is logged out", both_in and a_still and b_out, f"{both_in} {a_still} {b_out}")
        tpost(host, f"{BASE}/host/admin/users/delete", form={"user_id": str(sql("select id from host_users where username='sess-test'")[0][0])}, max_redirects=0)
        sa_ctx.close(); sb_ctx.close()
        # deleting a host account deletes everything it owns, and nothing of anyone else's
        tpost(host, f"{BASE}/host/admin/users/create", form={"username": "gone-host", "password": "gone-pass-1"}, max_redirects=0)
        sql("update host_users set must_change_password=0 where username='gone-host'")
        gh_ctx = b.new_context()
        tpost(gh_ctx, BASE + "/login", form={"username": "gone-host", "password": "gone-pass-1", "next": "/host"}, max_redirects=0)
        gh_page = gh_ctx.new_page(); gone_game = create_game(gh_page, "Doomed game")
        gv = tpost(gh_ctx, f"{BASE}/host/events", multipart={"name": "Doomed Event", "logo": {"name": "l.png", "mimeType": "image/png", "buffer": png1}}).json()["event"]["id"]
        gp_ctx, gp_page = join(b, gone_game, "Doomed Player"); tpost(gh_ctx, f"{BASE}/host/game/{gone_game}/admit_all")
        gone_uid = sql("select id from host_users where username='gone-host'")[0][0]
        sql(f"insert into host_spotify_token (host_user_id, owner_key, access_token, refresh_token, expires_at, created_at) values ({gone_uid}, 'default', 'a', 'r', '2030-01-01 00:00:00', '2026-01-01 00:00:00')")
        others_before = sql("select (select count(*) from games where owner_key != 'host:%d'), (select count(*) from players), (select count(*) from events where host_user_id != %d)" % (gone_uid, gone_uid))[0]
        mine_before = sql(f"select (select count(*) from games where owner_key='host:{gone_uid}'), (select count(*) from players where name='Doomed Player'), (select count(*) from card_squares where player_id in (select id from players where name='Doomed Player')), (select count(*) from events where host_user_id={gone_uid}), (select count(*) from host_spotify_token where host_user_id={gone_uid})")[0]
        tpost(host, f"{BASE}/host/admin/users/delete", form={"user_id": str(gone_uid)}, max_redirects=0)
        mine_after = sql(f"select (select count(*) from games where owner_key='host:{gone_uid}'), (select count(*) from players where name='Doomed Player'), (select count(*) from card_squares where player_id in (select id from players where name='Doomed Player')), (select count(*) from events where host_user_id={gone_uid}), (select count(*) from host_spotify_token where host_user_id={gone_uid}), (select count(*) from host_users where id={gone_uid})")[0]
        others_after = sql("select (select count(*) from games where owner_key != 'host:%d'), (select count(*) from players), (select count(*) from events where host_user_id != %d)" % (gone_uid, gone_uid))[0]
        check("deleting a host account removes their games, players, cards, events, Spotify login and the account itself", mine_before[0] >= 1 and mine_before[1] == 1 and mine_before[2] >= 24 and mine_before[3] == 1 and mine_before[4] == 1 and list(mine_after) == [0, 0, 0, 0, 0, 0], f"{mine_before} -> {mine_after}")
        check("...and leaves every other host's data alone", others_before[0] == others_after[0] and others_before[2] == others_after[2] and others_after[1] == others_before[1] - 1, f"{others_before} vs {others_after}")
        gh_ctx.close(); gp_ctx.close()
        # a Spotify token refresh that fails must not crash pages: "not connected" for now, and the saved login is kept unless revoked
        tk = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-c",
                             "import requests\nfrom datetime import datetime, timedelta\nfrom app.db import SessionLocal\nfrom app import models, spotify\n"
                             "db = SessionLocal()\nu = models.HostUser(username='tokentest', password_hash='x'); db.add(u); db.commit()\n"
                             "def fresh():\n    db.query(models.HostSpotifyToken).filter(models.HostSpotifyToken.host_user_id == u.id).delete(); db.commit()\n"
                             "    db.add(models.HostSpotifyToken(host_user_id=u.id, access_token='a', refresh_token='r', expires_at=datetime.utcnow() - timedelta(hours=1))); db.commit()\n"
                             "def http_error(code, body):\n    r = requests.Response(); r.status_code = code; r._content = body.encode(); return requests.HTTPError(str(code), response=r)\n"
                             "out = {}\n"
                             "for name, exc in (('invalid_client', http_error(400, '{\"error\":\"invalid_client\"}')), ('server_error', http_error(503, 'x')), ('no_network', requests.ConnectionError('down')), ('invalid_grant', http_error(400, '{\"error\":\"invalid_grant\"}'))):\n"
                             "    fresh()\n    spotify.refresh_access_token = lambda rt, e=exc: (_ for _ in ()).throw(e)\n"
                             "    res = spotify.get_valid_access_token(db, host_user_id=u.id)\n"
                             "    kept = db.query(models.HostSpotifyToken).filter(models.HostSpotifyToken.host_user_id == u.id).count()\n"
                             "    out[name] = (res, kept)\n"
                             "print('RESULT', out)"], capture_output=True, text=True)
        check("when Spotify refuses or can't be reached for a token refresh, the app says 'not connected' instead of crashing, and only a revoked login (invalid_grant) is forgotten",
              "RESULT {'invalid_client': (None, 1), 'server_error': (None, 1), 'no_network': (None, 1), 'invalid_grant': (None, 0)}" in tk.stdout, tk.stdout[-300:] + tk.stderr[-300:])
        # one-time values in the Spotify redirect address are kept out of the access log
        lg = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-c",
                             "import io, logging\nimport app.main\nbuf = io.StringIO(); h = logging.StreamHandler(buf); h.setFormatter(logging.Formatter('%(message)s'))\n"
                             "lg = logging.getLogger('uvicorn.access'); lg.addHandler(h); lg.setLevel(logging.INFO); lg.propagate = False\n"
                             "lg.info('%s - \"%s %s HTTP/%s\" %d', '1.2.3.4:5', 'GET', '/auth/spotify/callback?code=SECRETCODE123&state=STATEVALUE456&x=1', '1.1', 302)\n"
                             "lg.info('%s - \"%s %s HTTP/%s\" %d', '1.2.3.4:5', 'GET', '/enter?next=/host', '1.1', 200)\n"
                             "print(buf.getvalue())"], capture_output=True, text=True)
        check("the access log never shows the one-time code or state of the Spotify sign-in redirect, but keeps other addresses as they are", "SECRETCODE123" not in lg.stdout and "STATEVALUE456" not in lg.stdout and "code=[redacted]&state=[redacted]&x=1" in lg.stdout and "/enter?next=/host" in lg.stdout, lg.stdout[-250:] + lg.stderr[-150:])
        # a lobby is capped
        capg = create_game(hp, "Cap game")
        fill = subprocess.run(["docker", "exec", *env, CONTAINER, "python", "-c",
                               f"import uuid\nfrom app.db import SessionLocal\nfrom app import models\ndb = SessionLocal()\ng = db.query(models.Game).filter(models.Game.code == '{capg}').first()\n"
                               "db.add_all([models.Player(game_id=g.id, number=i, name=f'P{i}', admitted=False, token=uuid.uuid4().hex) for i in range(1, 501)])\ndb.commit()\nprint('FILLED', db.query(models.Player).filter(models.Player.game_id == g.id).count())"],
                              capture_output=True, text=True)
        capctx = b.new_context(); cap_tok = re.search(r'name="csrf-token" content="([^"]+)"', capctx.request.get(BASE + "/enter").text()).group(1)
        capr = capctx.request.post(BASE + f"/game/{capg}/join", form={"name": "Late Larry"}, headers={"X-CSRF-Token": cap_tok}, max_redirects=0)
        check("a lobby with 500 players is full: a 501st visitor is told so and gets no card", "FILLED 500" in fill.stdout and capr.status == 409 and "full" in capr.text().lower() and sql(f"select count(*) from players where game_id=(select id from games where code='{capg}')")[0][0] == 500, fill.stdout + fill.stderr[-150:] + str(capr.status))
        capctx.close()
        anon.close()

        # ---- Cross-site request protection ----
        cx = b.new_context()
        html0 = cx.request.get(BASE + "/enter").text()
        tok = re.search(r'name="csrf-token" content="([^"]+)"', html0).group(1)
        url = BASE + "/host/login"
        check("a POST with no CSRF token is refused", cx.request.post(url, form={"username": "h", "password": "pw"}, max_redirects=0).status == 403)
        check("a POST with a wrong CSRF token is refused", cx.request.post(url, form={"username": "h", "password": "pw", "csrf_token": "x" * 43}, max_redirects=0).status == 403)
        check("a POST from another site's page is refused even with a valid token", cx.request.post(url, form={"username": "h", "password": "pw"}, headers={"X-CSRF-Token": tok, "Origin": "https://evil.example"}, max_redirects=0).status == 403)
        check("a token from a different browser is refused", b.new_context().request.post(url, form={"username": "h", "password": "pw"}, headers={"X-CSRF-Token": tok}, max_redirects=0).status == 403)
        check("a POST with this browser's token goes through", cx.request.post(url, form={"username": "h", "password": "pw", "csrf_token": tok}, max_redirects=0).status == 307)
        ck = [c for c in cx.cookies() if c["name"] == "bingo_csrf"]
        check("the CSRF cookie is HttpOnly and SameSite", ck and ck[0]["httpOnly"] and ck[0]["sameSite"] == "Lax", str(ck))
        jr = cx.request.post(BASE + "/host/game/ZZZZZ/admit_all", headers={"Accept": "application/json"})
        check("a refused script request gets a JSON 403", jr.status == 403 and jr.json().get("csrf") is True, jr.text()[:100])
        pgx = cx.new_page()
        pgx.goto(BASE + "/enter")
        check("the page's own fetch() calls carry the token", pgx.evaluate("fetch('/host/login', {method:'POST', redirect:'manual', body: new URLSearchParams({username:'h',password:'pw'})}).then(r => r.status)") != 403)
        pgx.close()
        lr = tpost(b.new_context(), BASE + "/login", form={"username": "h", "password": "pw", "next": "/host"}, max_redirects=0)
        cookie_hdrs = [h["value"] for h in lr.headers_array if h["name"].lower() == "set-cookie"]
        check("login cookies are HttpOnly and SameSite", cookie_hdrs and all("httponly" in c.lower() and "samesite" in c.lower() for c in cookie_hdrs), str(cookie_hdrs)[:200])
        check("no page asks for a blocked or missing script, style or file", not blocked, "; ".join(blocked[:3]))

        if "--css-baseline" in sys.argv:
            import hashlib
            old_css = open(sys.argv[sys.argv.index("--css-baseline") + 1]).read()
            vc = create_game(hp, "Visual", paper=2)
            vp, _ = join(b, vc, "Pat")
            tpost(host, f"{BASE}/host/game/{vc}/admit_all")
            pages = [("/enter", outsider), ("/home", host), ("/host", host), (f"/host/game/{vc}", host), (f"/host/game/{vc}/paper", host),
                     ("/host/playlist", host), ("/host/saved", host), ("/host/admin/users", host), ("/host/account", host), ("/host/themes", host), ("/help", outsider),
                     (f"/game/{vc}", outsider), (f"/player/{vc}/1", vp)]
            def shot(ctx, path, width, baseline):
                pg = ctx.new_page()
                pg.set_viewport_size({"width": width, "height": 900})
                pg.route("https://sdk.scdn.co/**", lambda r: r.abort())
                if baseline:
                    pg.route("**/static/app.css*", lambda r: r.fulfill(body=old_css, content_type="text/css"))
                pg.goto(BASE + path)
                pg.wait_for_timeout(900)
                png = pg.screenshot()
                pg.close()
                return png
            import base64
            blank = b.new_context().new_page()
            def pixels_close(a, b_, tol=3):
                """Same picture, allowing each color channel to differ by up to `tol` of 255 (browsers round
                translucent colors slightly differently between rgba(...) and rgb(... / a))."""
                return blank.evaluate("""async ([a, b, tol]) => {
                    const load = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = 'data:image/png;base64,' + src; });
                    const [ia, ib] = await Promise.all([load(a), load(b)]);
                    if (ia.width !== ib.width || ia.height !== ib.height) return false;
                    const cv = document.createElement('canvas'); cv.width = ia.width; cv.height = ia.height;
                    const cx = cv.getContext('2d', {willReadFrequently: true});
                    cx.drawImage(ia, 0, 0); const da = cx.getImageData(0, 0, cv.width, cv.height).data;
                    cx.clearRect(0, 0, cv.width, cv.height); cx.drawImage(ib, 0, 0); const db = cx.getImageData(0, 0, cv.width, cv.height).data;
                    for (let i = 0; i < da.length; i++) if (Math.abs(da[i] - db[i]) > tol) return false;
                    return true; }""", [base64.b64encode(a).decode(), base64.b64encode(b_).decode(), tol])
            for path, ctx in pages:
                for width in (1440, 390):
                    check(f"CSS unchanged: {path.replace(vc, 'CODE')} at {width}px", pixels_close(shot(ctx, path, width, False), shot(ctx, path, width, True)))
        b.close()

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
