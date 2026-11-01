#!/usr/bin/env python3
"""First-run setup screen checks, against a brand-new copy of the app with no accounts (run through tests/run_tests.sh,
which starts that copy and sets BASE and CONTAINER)."""
import os, re, subprocess, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_spotify

BASE = os.environ["BASE"].rstrip("/")
CONTAINER = os.environ["CONTAINER"]
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


def main():
    out = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True)
    check("a brand-new install says in its log to open /setup", "SETUP: no host account exists yet" in out.stdout + out.stderr and "setup code" not in (out.stdout + out.stderr).lower(), "no SETUP line in the log")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
        fake_spotify.install(pg, [])
        for path in ("/", "/enter", "/login", "/host", "/home", "/help"):
            pg.goto(BASE + path); pg.wait_for_load_state("networkidle")
            check(f"{path} sends a visitor to the setup screen while there is no account", pg.url.endswith("/setup") and "Welcome to Music Bingo" in pg.content(), pg.url)
        check("the stylesheet is still served during setup", ctx.request.get(BASE + "/static/app.css").status == 200)
        check("the setup screen asks for a username and password, the public address and Spotify details", all(pg.locator(s).count() == 1 for s in ("input[name=username]", "input[name=password]", "input[name=password2]", "input[name=public_url]", "input[name=spotify_client_id]", "input[name=spotify_client_secret]", "input[name=spotify_redirect_uri]")))
        try:
            from axe_playwright_python.sync_playwright import Axe
            serious = [f"{v['id']}: {v['nodes'][0]['html'][:70]!r}" for v in Axe().run(pg, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]}}).response["violations"] if v["impact"] in ("critical", "serious")]
            check("the setup screen has no critical or serious accessibility problems (labels, contrast)", not serious, "; ".join(serious[:3]))
        except ImportError:
            pass   # pip install axe-playwright-python to include this check
        check("the setup screen explains where to get a Spotify client ID and secret, with the redirect address to register", "Where do I get a client ID and secret?" in pg.content() and "Web Playback SDK" in pg.content() and "View client secret" in pg.content() and pg.locator(".spotifyStepRedirect").inner_text() == BASE + "/auth/spotify/callback", pg.locator(".spotifyStepRedirect").inner_text() if pg.locator(".spotifyStepRedirect").count() else "missing")
        check("the public address is guessed from the address in use", pg.input_value("input[name=public_url]") == BASE, pg.input_value("input[name=public_url]"))
        check("the Spotify redirect address is shown for that address", pg.locator("#setupRedirect").inner_text() == BASE + "/auth/spotify/callback", pg.locator("#setupRedirect").inner_text())
        pg.fill("input[name=public_url]", "https://bingo.example.org/"); pg.wait_for_timeout(100)
        check("the redirect address in the steps follows what is typed too", pg.locator(".spotifyStepRedirect").inner_text() == "https://bingo.example.org/auth/spotify/callback")
        check("the redirect address follows what is typed", pg.locator("#setupRedirect").inner_text() == "https://bingo.example.org/auth/spotify/callback")
        pg.fill("input[name=spotify_redirect_uri]", "http://127.0.0.1:5000/auth/spotify/callback"); pg.wait_for_timeout(100)
        check("a separate Spotify redirect address (for running on your own computer) replaces it", pg.locator("#setupRedirect").inner_text() == "http://127.0.0.1:5000/auth/spotify/callback")

        def submit(**kw):
            vals = dict(username="owner", password="a-long-password", password2="a-long-password", public_url="https://bingo.example.org", spotify_client_id="", spotify_client_secret="")
            vals.update(kw)
            pg.goto(BASE + "/setup"); pg.wait_for_load_state("networkidle")
            for k, v in vals.items():
                pg.fill(f"input[name={k}]", v)
            pg.click("form.setupForm button[type=submit]"); pg.wait_for_load_state("networkidle")
            return pg.locator(".alert.alertBad").inner_text() if pg.locator(".alert.alertBad").count() else ""

        check("mismatching passwords are refused", "do not match" in submit(password2="something-else"))
        check("a short password is refused", "at least 8" in submit(password="short", password2="short"))
        check("an odd username is refused", "username needs" in submit(username="a b"))
        check("a public address with a path is refused", "public address" in submit(public_url="https://x.example/path"))
        check("no account was made by the refused attempts", pg.url.endswith("/setup"))
        ctx2 = b.new_context(extra_http_headers={"X-Forwarded-For": "203.0.113.77"})
        pg = ctx2.new_page(); fake_spotify.install(pg, [])
        err = submit(spotify_client_id="my-client-id", spotify_client_secret="my-client-secret", spotify_redirect_uri="http://127.0.0.1:5000/auth/spotify/callback")
        check("the right code and details create the admin account and log in", err == "" and pg.url.rstrip("/").endswith("/host"), pg.url + " " + err)
        check("the new admin is signed in on the dashboard", "Host Dashboard" in pg.content() or pg.locator("#createBtn").count() == 1)
        pg.goto(BASE + "/host/admin/users"); pg.wait_for_load_state("networkidle")
        check("the account is an admin account with the chosen username", "owner" in pg.content())
        check("the Admin page and the help page say which version of Music Bingo this is", "Music Bingo dev" in pg.content() and "Music Bingo dev" in ctx2.request.get(BASE + "/help").text())
        check("the Admin page explains where to get a Spotify client ID and secret", "Where do I get a Spotify client ID and secret?" in pg.content() and "Web Playback SDK" in pg.content())
        check("the Admin page shows the saved address and Spotify details (the secret is not sent back)", pg.input_value("input[name=public_url]") == "https://bingo.example.org" and pg.input_value("input[name=spotify_client_id]") == "my-client-id" and "my-client-secret" not in pg.content() and pg.input_value("input[name=spotify_redirect_uri]") == "http://127.0.0.1:5000/auth/spotify/callback", pg.input_value("input[name=public_url]"))
        pg.goto(BASE + "/setup"); pg.wait_for_load_state("networkidle")
        check("the setup screen is gone once an account exists", pg.url.endswith("/login"))
        check("the setup screen stops working once an account exists", ctx2.request.post(BASE + "/setup", form={"username": "x1y2z", "password": "another-pass1", "password2": "another-pass1"}, max_redirects=0).status in (302, 303, 403, 400, 404))
        ctx3 = b.new_context(); lp = ctx3.new_page()
        lp.goto(BASE + "/login"); lp.fill("input[name=username]", "owner"); lp.fill("input[name=password]", "a-long-password"); lp.click("button[type=submit]"); lp.wait_for_load_state("networkidle")
        check("the new admin can log in again with the chosen password", "/login" not in lp.url and lp.locator("input[name=password]").count() == 0, lp.url)
        lp.goto(BASE + "/host/themes"); lp.wait_for_load_state("networkidle")
        check("the chosen password is not a temporary one (no forced change)", lp.url.rstrip("/").endswith("/host/themes"), lp.url)
        check("no JavaScript errors", not errors, "; ".join(errors[:3]))
        b.close()
    print(f"\n{sum(results)}/{len(results)} setup checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
