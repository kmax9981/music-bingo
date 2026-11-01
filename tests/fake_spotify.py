"""A stand-in for Spotify in the browser: a fake Web Playback SDK script plus canned api.spotify.com answers.
Use install(page) before opening a page that plays music; then play(page, title) pretends Spotify started that song."""
import json

FAKE_SDK = r"""
window.Spotify = { Player: class {
  constructor(o){ this.o = o; this.l = {}; window.__fake = this; }
  addListener(e, f){ (this.l[e] = this.l[e] || []).push(f); return true; }
  removeListener(){ return true; }
  async connect(){ setTimeout(() => this.emit('ready', { device_id: 'fakedev' }), 30); return true; }
  disconnect(){}
  _c(n){ (window.__fakeCalls = window.__fakeCalls || []).push(n); }
  async pause(){ this._c('pause'); } async resume(){ this._c('resume'); } async nextTrack(){ this._c('nextTrack'); }
  async previousTrack(){} async seek(){ this._c('seek'); } async togglePlay(){ this._c('togglePlay'); }
  async setVolume(){} async activateElement(){}
  async getCurrentState(){ return this.state || null; }
  emit(e, d){ (this.l[e] || []).forEach(f => f(d)); }
  playTrack(t, ctx, pos){
    const s = { paused: false, position: pos, duration: 200000, context: { uri: ctx },
      track_window: { current_track: { id: t.id, name: t.name, uri: 'spotify:track:' + t.id, artists: [{ name: t.artist || 'Band' }] }, previous_tracks: [], next_tracks: [] } };
    this.state = s; this.emit('player_state_changed', s);
  }
} };
setTimeout(() => { if (window.onSpotifyWebPlaybackSDKReady) window.onSpotifyWebPlaybackSDKReady(); }, 0);
"""


def install(page, calls=None):
    """Serve the fake SDK and answer Spotify's web API. `calls` (a list) collects 'METHOD /path' for every API call."""
    page.route("https://sdk.scdn.co/**", lambda r: r.fulfill(body=FAKE_SDK, content_type="application/javascript"))

    def api(route):
        req = route.request
        path = req.url.split("api.spotify.com", 1)[1]
        if calls is not None:
            calls.append(f"{req.method} {path.split('?')[0]}")
        if req.method == "GET" and path.startswith("/v1/me/player"):
            body = {"device": {"id": "fakedev", "is_active": True}, "is_playing": True, "shuffle_state": True, "repeat_state": "context", "progress_ms": 11000}
        elif req.method == "GET" and "/playlists/" in path:
            body = {"name": "Test list", "tracks": {"total": 75}}
        elif req.method == "GET":
            body = {}
        else:
            route.fulfill(status=204, body="")
            return
        route.fulfill(status=200, body=json.dumps(body), content_type="application/json",
                      headers={"access-control-allow-origin": "*"})
    page.route("https://api.spotify.com/**", api)


def play(page, title, artist="Band", tid=None, playlist="PLAYLIST75AAAAAAAAAAAA", pos=0):
    """Spotify reports `title` playing, `pos` milliseconds in."""
    tid = tid or "t" + str(sum(map(ord, title)))
    page.evaluate("([t, ctx, pos]) => window.__fake.playTrack(t, ctx, pos)",
                  [{"id": tid, "name": title, "artist": artist}, "spotify:playlist:" + playlist, pos])


def listen(page, title, **kw):
    """A song starts, and 10.5 seconds in is reported once the page's 3-second 'stale position' window has passed
    (so the page reveals it and adds it to Played Tracks). Takes about 3.3 seconds."""
    play(page, title, pos=0, **kw)
    page.wait_for_timeout(3300)
    play(page, title, pos=10500, **kw)
    page.wait_for_timeout(300)
