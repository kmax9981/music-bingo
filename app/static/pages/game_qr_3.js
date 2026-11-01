// Optional: this tab becomes a Spotify speaker named "Bingo Room Screen" (Spotify Web Playback SDK), so the music the
// host controls from the host page plays out of this screen's speakers / HDMI audio. Needs one click (browsers block
// sound until the page is clicked) and the host's Spotify Premium. Nothing is started here: on the host page click
// "Refresh devices" and pick "Bingo Room Screen" before Start Game. While music plays here, this page also reports the
// current song to the server (the host page can only do that for its own embedded player).
(function () {
  var btn = document.getElementById("soundBtn"), msg = document.getElementById("soundMsg");
  if (!btn) return;
  var player = null;

  // The host page only hears about songs played on its own embedded player, so when the music plays here this page
  // tells the server what is playing (same message the host page sends), and the phones and the reveal screen follow.
  var ping = { at: 0, id: null, paused: null }, chain = Promise.resolve();
  function reportState(state) {
    try {
      if (!state || !state.track_window || !state.track_window.current_track) return;
      var t = state.track_window.current_track, paused = !!state.paused, now = Date.now();
      var changed = t.id !== ping.id || paused !== ping.paused;
      if (!changed && now - ping.at < 1000) return;
      ping = { at: now, id: t.id, paused: paused };
      var body = JSON.stringify({ track_id: t.id || "", title: t.name || "", artist: (t.artists && t.artists[0] && t.artists[0].name) || "",
                                  position_ms: typeof state.position === "number" ? state.position : 0, paused: paused });
      chain = chain.then(function () {
        return fetch("/host/game/" + encodeURIComponent(document.body.dataset.code) + "/track_update",
                     { method: "POST", headers: { "Content-Type": "application/json" }, body: body, credentials: "same-origin" });
      }).catch(function () {});
    } catch (e) {}
  }

  function say(text) { msg.textContent = text; msg.hidden = !text; }

  function token() {
    return fetch("/api/spotify/token", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ("HTTP " + r.status)); return j.access_token; }); });
  }

  function loadSdk() {
    return new Promise(function (resolve, reject) {
      if (window.Spotify && window.Spotify.Player) return resolve();
      window.onSpotifyWebPlaybackSDKReady = function () { resolve(); };
      var s = document.createElement("script");
      s.src = "https://sdk.scdn.co/spotify-player.js"; s.async = true;
      s.onerror = function () { reject(new Error("couldn't load Spotify's player")); };
      document.head.appendChild(s);
      setTimeout(function () { reject(new Error("Spotify's player didn't load")); }, 15000);
    });
  }

  btn.addEventListener("click", function () {
    if (player) return;
    btn.hidden = true; say("Starting the speaker…");
    loadSdk().then(function () {
      player = new window.Spotify.Player({
        name: "Bingo Room Screen", volume: 0.9,
        getOAuthToken: function (cb) { token().then(cb).catch(function () { cb(""); }); }
      });
      try { player.activateElement(); } catch (e) {}      // unlocks sound; this click is the permission the browser wants
      player.addListener("ready", function () { say(""); });       // nothing on screen: the host sees "Bingo Room Screen" in the device list
      player.addListener("not_ready", function () { say("Speaker went offline. Reload this page and click again."); });
      player.addListener("player_state_changed", reportState);
      player.addListener("initialization_error", function (e) { say("This browser can't play Spotify: " + e.message); });
      player.addListener("authentication_error", function () { say("Spotify sign-in problem. Reconnect Spotify on the host page, then reload."); });
      player.addListener("account_error", function () { say("Spotify Premium is needed to play music here."); });
      return player.connect();
    }).catch(function (e) { player = null; btn.hidden = false; say("Couldn't start the speaker: " + e.message); });
  });
})();
