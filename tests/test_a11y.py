#!/usr/bin/env python3
"""Accessibility: axe-core on the main pages (dark and light theme, desktop and phone width). Fails on any critical or serious
problem (form fields without a name, unreadable colors, ...). Needs `pip install axe-playwright-python`; without it the
check is skipped. Run through tests/run_tests.sh."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from axe_playwright_python.sync_playwright import Axe
except ImportError:
    print("SKIP  accessibility checks (pip install axe-playwright-python to run them)"); sys.exit(0)
from playwright.sync_api import sync_playwright
import fake_spotify

BASE = os.environ.get("BASE", "http://127.0.0.1:5104").rstrip("/")
results, axe = [], Axe()
TAGS = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]}}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


def bad(pg):
    out = []
    for v in axe.run(pg, options=TAGS).response["violations"]:
        if v["impact"] in ("critical", "serious"):
            out.append(f"{v['id']} ({len(v['nodes'])}): {v['nodes'][0]['html'][:70]!r}")
    return out


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for theme in ("midnight", "light"):
            for tag, vp in (("desktop", {"width": 1280, "height": 900}), ("phone", {"width": 390, "height": 780})):
                hctx = b.new_context(viewport=vp); hp = hctx.new_page(); fake_spotify.install(hp, [])
                hp.goto(BASE + "/login?next=/host"); hp.fill("input[name=username]", "h"); hp.fill("input[name=password]", "pw"); hp.click("button[type=submit]"); hp.wait_for_load_state("networkidle")
                hp.goto(BASE + "/host/themes"); hp.check(f"input[name=theme][value={theme}]", force=True); hp.click("#themeForm button[type=submit]"); hp.wait_for_load_state("networkidle")
                pages = {}
                for path in ("/host", "/host/account", "/host/themes", "/host/events/manage", "/host/saved", "/host/history", "/host/playlist", "/host/admin/users", "/help", "/play"):
                    hp.goto(BASE + path); hp.wait_for_timeout(300); pages[path] = bad(hp)
                hp.goto(BASE + "/host"); hp.fill("input[name=game_name]", "A11y"); hp.fill("input[name=playlist_id_or_url]", "PLAYLIST75AAAAAAAAAAAA"); hp.check("#paperToggle"); hp.fill("input[name=paper_count]", "2"); hp.click("#createBtn"); hp.wait_for_load_state("networkidle")
                code = hp.url.split("/host/game/")[1].split("/")[0]
                for name, path in (("host game", f"/host/game/{code}"), ("paper cards", f"/host/game/{code}/paper"), ("QR page", f"/host/game/{code}/qr")):
                    hp.goto(BASE + path); hp.wait_for_timeout(500); pages[name] = bad(hp)
                pctx = b.new_context(viewport=vp); pp = pctx.new_page()
                pp.goto(f"{BASE}/game/{code}"); pages["join page"] = bad(pp)
                pp.fill("input[name=name]", "Ann"); pp.click("button[type=submit]"); pp.wait_for_load_state("networkidle"); pages["waiting"] = bad(pp)
                hp.evaluate(f"fetch('/host/game/{code}/player/1/admit', {{method: 'POST'}})"); pp.wait_for_timeout(1500); pp.reload(); pp.wait_for_timeout(800); pages["player card"] = bad(pp)
                ep = b.new_context(viewport=vp).new_page(); ep.goto(BASE + "/enter"); pages["/enter"] = bad(ep)
                lp = b.new_context(viewport=vp).new_page(); lp.goto(BASE + "/login"); pages["/login"] = bad(lp)
                problems = {k: v for k, v in pages.items() if v}
                check(f"no critical or serious accessibility problems on {len(pages)} pages ({theme}, {tag})", not problems, "; ".join(f"{k}: {v[0]}" for k, v in list(problems.items())[:3]))
                hctx.close(); pctx.close()
        b.close()
    print(f"\n{sum(results)}/{len(results)} accessibility checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
