"""Throwaway copy of the app for tests: python local_server.py <app_dir> <port>.
Fresh SQLite database next to the app, two hosts (h / pw, an admin, and h2 / pw), and Spotify simulated: playlist
PLAYLIST75AAAAAAAAAAAA has 75 songs and PLAYLIST30AAAAAAAAAAAA has 30. Put song titles (one per line) in a file
named DROP in <app_dir> to take them out of the playlist, or in ADD to add them, to test playlist changes."""
import os, re, sys, types, uuid, requests
app_dir, port = sys.argv[1], int(sys.argv[2])
db_path = os.path.join(app_dir, "paper.db")
if os.path.exists(db_path):
    os.remove(db_path)
os.environ["DATABASE_URL"] = os.environ.get("LOAD_DATABASE_URL") or f"sqlite:///{db_path}?check_same_thread=false"   # LOAD_DATABASE_URL: run on Postgres (load tests)
os.environ["COOKIE_SECRET"] = "local-paper-test"
os.environ["TRUST_PROXY_HEADERS"] = "true"  # lets the login-throttle test pretend to be different visitors
sys.path.insert(0, app_dir); os.chdir(app_dir)
from app import spotify
spotify._spotify_access_token_is_valid = lambda *a, **k: True
from app import main, models
from app import paper as _paper
_paper._STALE_TITLES_TTL_S = 1   # the out-of-date-cards notice re-reads the playlist after 1 second here (20 in real use), so tests needn't wait

SONGS = ["Take On Me", "Billie Jean", "Sweet Child O' Mine", "Livin' on a Prayer", "Don't Stop Believin'", "Every Breath You Take",
 "Girls Just Want to Have Fun", "Wake Me Up Before You Go-Go", "Jump", "Like a Prayer", "Beat It", "Africa", "Come On Eileen",
 "Tainted Love", "Material Girl", "Sweet Dreams (Are Made of This)", "Total Eclipse of the Heart", "Footloose", "Eye of the Tiger",
 "Never Gonna Give You Up", "I Wanna Dance with Somebody (Who Loves Me)", "Here I Go Again", "Pour Some Sugar on Me", "Hungry Like the Wolf",
 "Don't You (Forget About Me)", "Karma Chameleon", "Walk Like an Egyptian", "Everybody Wants to Rule the World", "Just Can't Get Enough",
 "Smells Like Teen Spirit", "Wonderwall", "Losing My Religion", "Black Hole Sun", "Under the Bridge", "Creep", "Torn", "Zombie",
 "Semi-Charmed Life", "Mr. Jones", "Bitter Sweet Symphony", "No Diggity", "Waterfalls", "Gangsta's Paradise", "Vogue", "Ironic",
 "Jumpdafuckup", "...Baby One More Time", "MMMBop", "Wannabe", "Ice Ice Baby", "U Can't Touch This", "Gonna Make You Sweat (Everybody Dance Now)",
 "Rhythm Is a Dancer", "What Is Love", "Macarena", "Kiss from a Rose", "Everybody (Backstreet's Back)", "I Want It That Way", "Bye Bye Bye",
 "Genie in a Bottle", "Livin' la Vida Loca", "All Star", "Blue (Da Ba Dee)", "Torn Between Two Lovers", "Closing Time", "Bulls on Parade",
 "Song 2", "Basket Case", "Interstate Love Song", "Wonderful Tonight", "Two Princes", "Hey Ya!", "Mo Money Mo Problems", "Return of the Mack", "Barbie Girl"]
assert len(SONGS) == 75, len(SONGS)
# Songs Spotify would mark explicit: all after the 30th, so PLAYLIST30 is clean and PLAYLIST75 has 5
EXPLICIT = {"Gangsta's Paradise", "Jumpdafuckup", "No Diggity", "Bulls on Parade", "Song 2"}
PLAYLISTS = {"PLAYLIST75AAAAAAAAAAAA": SONGS, "PLAYLIST30AAAAAAAAAAAA": SONGS[:30],
             "PLAYLISTSHORTAAAAAAAAA": SONGS[:20] + sorted(EXPLICIT),   # only 20 clean songs: too short for a clean copy
             "PLAYLISTFORBIDAAAAAAAA": SONGS[30:60]}                  # 27 clean songs; a copy named FORBID... is refused (403)
CLEAN_COPIES = set()   # (playlist id, title) of clean releases added to a clean copy


def _items(pid):
    drop = set()
    try: drop = set(open(os.path.join(app_dir, "DROP")).read().splitlines())
    except Exception: pass
    extra = []
    try: extra = [l for l in open(os.path.join(app_dir, "ADD")).read().splitlines() if l]
    except Exception: pass
    return [{"track": {"id": f"t{i}", "name": n, "type": "track", "explicit": n in EXPLICIT and (pid, n) not in CLEAN_COPIES, "duration_ms": 200000, "uri": f"spotify:track:t{i}", "artists": [{"name": "Band"}]}}
            for i, n in enumerate(PLAYLISTS.get(pid, []) + (extra if pid == "PLAYLIST75AAAAAAAAAAAA" else [])) if n not in drop]
def _t(i, name, explicit, artist="Band", ms=200000):
    return {"id": i, "name": name, "uri": f"spotify:track:{i}", "explicit": explicit, "artists": [{"name": artist}], "duration_ms": ms}
# What a Spotify search for a clean version finds. Only c13 and c21 are acceptable matches; the others are decoys.
SEARCH = {"No Diggity": [_t("c10", "No Diggity (Live)", False), _t("c11", "No Diggity", True), _t("c12", "No Diggity", False, artist="Other"), _t("c13", "No Diggity", False, ms=202000)],
          "Bulls on Parade": [_t("c20", "Bulls on Parade", False, ms=260000), _t("c21", "Bulls on Parade - Radio Edit", False, ms=199000)]}
CLEAN_NAMES = {"c13": "No Diggity", "c21": "Bulls on Parade - Radio Edit"}


MY_PLAYLISTS = []   # playlists created in the (fake) Spotify account by Make clean copy


def fake_api_get(db, path, params=None, host_user_id=None, **k):
    if path == "/me":
        return {"id": "me"}
    if path == "/me/playlists":
        off = int((params or {}).get("offset", 0)); lim = int((params or {}).get("limit", 50))
        return {"items": MY_PLAYLISTS[off:off + lim], "next": None}
    if path == "/search":
        m = re.search(r'track:"([^"]*)"', (params or {}).get("q", ""))
        return {"tracks": {"items": SEARCH.get(m.group(1) if m else "", [])}}
    if "/tracks" in path:
        pid = path.split("/playlists/")[1].split("/")[0]
        if pid == "PLAYLISTGONEAAAAAAAAAA":   # deleted or made private since it was saved: Spotify answers 404
            raise requests.HTTPError("404 Not Found", response=types.SimpleNamespace(status_code=404, text='{"error":{"status":404}}'))
        off = int((params or {}).get("offset", 0))
        return {"items": _items(pid) if off == 0 else [], "next": None, "total": len(_items(pid))}
    if path.startswith("/playlists/"):
        pid = path.split("/playlists/")[1].split("?")[0]
        return {"name": pid, "tracks": {"total": len(_items(pid))}}
    return {}
spotify.api_get = fake_api_get
spotify.api_put = lambda *a, **k: None
import re, types, requests
def fake_api_post(db, path, json=None, params=None, host_user_id=None, **k):
    """Spotify's create-playlist and add-songs calls: new playlists are served back by the fake playlist reader."""
    if path == "/me/playlists":
        if "FORBID" in (json or {}).get("name", ""):
            raise requests.HTTPError(response=types.SimpleNamespace(status_code=403))
        pid = "CLEAN%017d" % len(PLAYLISTS)
        PLAYLISTS[pid] = []
        MY_PLAYLISTS.append({"id": pid, "name": (json or {}).get("name", ""), "owner": {"id": "me"}})
        return {"id": pid}
    m = re.match(r"/playlists/([^/]+)/(tracks|items)$", path)
    if m:
        for u in (json or {}).get("uris", []):
            tid = u.rsplit(":", 1)[1]
            if tid.startswith("c"):
                PLAYLISTS[m.group(1)].append(CLEAN_NAMES[tid]); CLEAN_COPIES.add((m.group(1), CLEAN_NAMES[tid]))
            else:
                PLAYLISTS[m.group(1)].append(SONGS[int(tid[1:])])
        return {"snapshot_id": "x"}
    return None
spotify.api_post = fake_api_post
spotify.get_valid_access_token = lambda *a, **k: "fake-token"

if not os.environ.get("NO_SEED"):   # NO_SEED=1: a brand-new install with no accounts (for the first-run setup screen tests)
    db = main.SessionLocal()
    u = models.HostUser(username="h", password_hash=main._pw_hash("pw"), is_admin=True); db.add(u)
    u2 = models.HostUser(username="h2", password_hash=main._pw_hash("pw")); db.add(u2); db.commit()
import uvicorn
uvicorn.run(main.app, host="0.0.0.0", port=port, log_level="warning")
