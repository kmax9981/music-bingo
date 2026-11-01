#!/usr/bin/env python3
"""Solo game checks with a faked Spotify (see fake_spotify.py). Run through tests/run_tests.sh. Prints OBS lines
(what the page did) and PASS/FAIL checks; exits 1 on any failure."""
import json, os, re, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_spotify

BASE = os.environ.get("BASE", "http://127.0.0.1:5104").rstrip("/")
PLAYLIST = "https://open.spotify.com/playlist/PLAYLIST75AAAAAAAAAAAA"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


def main():
    errors, posts, calls = [], [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
        pg.on("request", lambda r: posts.append(json.loads(r.post_data or "{}")) if r.method == "POST" and r.url.endswith("/played_track") else None)
        fake_spotify.install(pg, calls)
        pg.goto(BASE + "/login?next=/play")
        pg.fill("input[name=username]", "h"); pg.fill("input[name=password]", "pw")
        pg.click("button[type=submit]"); pg.wait_for_load_state("networkidle")
        pg.fill("input[name=playlist]", PLAYLIST)
        pg.click("button:has-text('Start')"); pg.wait_for_load_state("networkidle")
        m = re.search(r"/play/solo/([A-Z0-9]+)/(\d+)", pg.url)
        check("starting a solo game opens the solo page", bool(m), pg.url)
        code, pn = m.group(1), m.group(2)
        pg.wait_for_timeout(3500)
        status = pg.locator("#playStatus").inner_text() + " | " + (pg.locator("#soloPlayStatusText").inner_text() if pg.locator("#soloPlayStatusText").count() else "")
        print("OBS status:", status.strip()[:100])
        print("OBS spotify api calls:", calls)
        check("the page started the playlist on the (fake) device", any(c.startswith("PUT /v1/me/player/play") for c in calls), str(calls))
        squares = pg.locator("#soloCardGrid .sq")
        check("card has 25 squares", squares.count() == 25)
        for vw, vh in ((1917, 870), (1534, 700), (1280, 600)):
            pg.set_viewport_size({"width": vw, "height": vh}); pg.wait_for_timeout(300)
            bottom = pg.evaluate("document.querySelector('#soloCardPanel').getBoundingClientRect().bottom")
            check(f"the whole solo card fits in a {vw}x{vh} window", bottom <= vh, f"panel bottom {bottom}")
        pg.set_viewport_size({"width": 1280, "height": 720})
        check("the solo page has a Bingo hints switch, off by default", pg.locator("#soloHintChk").count() == 1 and not pg.locator("#soloHintChk").is_checked())
        check("the solo card has B I N G O above its columns", pg.locator("#soloCardGrid .cardLetter").all_inner_texts() == list("BINGO"))
        titles = {i: pg.locator(f'#soloCardGrid .sq[data-pos="{i}"] .sqText').inner_text().strip() for i in range(25) if i != 12 and pg.locator(f'#soloCardGrid .sq[data-pos="{i}"] .sqText').count()}
        row = [titles[i] for i in range(5)]

        # a song that is not on the card, then the first row's songs, played in order
        fake_spotify.listen(pg, "Some Other Song")
        for t in row:
            fake_spotify.listen(pg, t)
        chips = pg.locator("#playedList .chip").all_inner_texts()
        print("OBS played list:", chips)
        check("Played Tracks lists every song newest first", len(chips) == 6 and row[-1] in chips[0] and "Some Other Song" in chips[-1], str(chips))
        check("the count label matches", "6" in pg.locator("#songsCount").inner_text(), pg.locator("#songsCount").inner_text())
        titles_posted = [p.get("title") for p in posts]
        print("OBS played_track posts:", titles_posted)
        check("every song was reported to the server at least once", all(t in titles_posted for t in row + ["Some Other Song"]), str(titles_posted))
        # Bingo hints: off does nothing; on lights the song's column, or one decoy column when it is not on the card
        lit = lambda: pg.evaluate("Array.from(document.querySelectorAll('#soloCardGrid .cardLetter')).map((e, i) => e.classList.contains('lit') ? i : -1).filter(i => i >= 0)")
        fake_spotify.listen(pg, row[3])
        check("with hints off no letter lights", lit() == [])
        pg.check("#soloHintChk")
        fake_spotify.listen(pg, row[1])
        check("hints on: a song on the card lights its own column", lit() == [1], str(lit()))
        fake_spotify.listen(pg, "Some Other Song")
        check("hints on: a song that is not on the card lights exactly one column", len(lit()) == 1, str(lit()))
        pg.uncheck("#soloHintChk")
        check("turning hints off clears the letter", lit() == [])
        # replaying the same song doesn't add it twice
        fake_spotify.play(pg, row[0], pos=10500); pg.wait_for_timeout(500)
        check("a repeated song is not listed twice", pg.locator("#playedList .chip").count() == 6)

        # buttons and refresh
        pg.evaluate("window.__fakeCalls = []")
        for sel in ("#btnPause", "#btnPlay", "#btnNext"):
            pg.click(sel); pg.wait_for_timeout(500)
        fake_calls = pg.evaluate("window.__fakeCalls")
        print("OBS player calls from Pause, Play, Next:", fake_calls)
        check("Pause, Play and Next reach the player", "pause" in fake_calls and "nextTrack" in fake_calls and ("resume" in fake_calls or "togglePlay" in fake_calls or any(c.startswith("PUT /v1/me/player/play") for c in calls)), str(fake_calls))
        pg.reload(); pg.wait_for_timeout(2500)
        check("a refresh in the same tab keeps the Played Tracks list", pg.locator("#playedList .chip").count() == 6, str(pg.locator("#playedList .chip").count()))
        # tapping a square reacts at once even when the server is slow, and a failed save puts it back
        def slow_toggle(route):
            pg.wait_for_timeout(1500)
            route.continue_()
        pg.route("**/toggle", slow_toggle)
        probe = next(i for i in range(25) if i != 12 and i in titles and titles[i] not in row)
        sq = f'#soloCardGrid .sq[data-pos="{probe}"]'
        pg.click(sq)
        pg.wait_for_timeout(250)
        check("a tapped square is marked immediately, not after the server replies", "marked" in (pg.locator(sq).get_attribute("class") or ""))
        pg.wait_for_timeout(2000)
        pg.click(sq)
        pg.wait_for_timeout(250)
        check("tapping it again unmarks it immediately", "marked" not in (pg.locator(sq).get_attribute("class") or ""))
        pg.wait_for_timeout(2000)
        check("the server agrees afterwards", "marked" not in (pg.locator(sq).get_attribute("class") or ""))
        pg.unroute("**/toggle")
        pg.route("**/toggle", lambda route: route.abort())
        pg.click(sq)
        pg.wait_for_timeout(600)
        check("if saving fails the square goes back", "marked" not in (pg.locator(sq).get_attribute("class") or ""))
        pg.unroute("**/toggle")

        # invalid claim: dab a square whose song has not played
        other = next(i for i in range(25) if i != 12 and i in titles and titles[i] not in row and titles[i] != "Some Other Song")
        pg.click(f'#soloCardGrid .sq[data-pos="{other}"]'); pg.wait_for_timeout(400)
        pg.click("#btnBingo"); pg.wait_for_timeout(1500)
        msg = pg.locator("#bingoResult").inner_text()
        print("OBS invalid claim message:", msg)
        check("a claim with an unplayed dabbed square says which square", titles[other].lower()[:12] in msg.lower() or "dabbed" in msg.lower() or "not played" in msg.lower(), msg)
        pg.click(f'#soloCardGrid .sq[data-pos="{other}"]'); pg.wait_for_timeout(300)   # un-dab it

        # valid claim: dab the first row
        for i in range(5):
            pg.click(f'#soloCardGrid .sq[data-pos="{i}"]'); pg.wait_for_timeout(250)
        marked = pg.locator("#soloCardGrid .sq.marked").count()
        check("dabbed squares are marked", marked >= 5, str(marked))
        pg.click("#btnBingo"); pg.wait_for_timeout(2500)
        msg = pg.locator("#bingoResult").inner_text()
        over = pg.locator("#soloGameOver").is_visible() if pg.locator("#soloGameOver").count() else False
        print("OBS valid claim message:", msg, "| game over shown:", over)
        check("a real bingo is accepted", bool(msg) and not msg.lower().startswith(("no bingo", "sorry", "checking")), msg)
        check("no JavaScript errors", not errors, "; ".join(errors[:3]))
        b.close()
    print(f"\n{sum(results)}/{len(results)} solo checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
