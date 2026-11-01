// Room display: when the host turns on "Reveal on QR screen", the QR code gives way to the song reveal once the
// game starts: "Game starting in 3, 2, 1", then each song with the same 10-second countdown the phones use.
(function () {
  var REVEAL_MS = 10000, START_SECS = 3;
  var body = document.body, CODE = body.dataset.code;
  var $ = function (id) { return document.getElementById(id); };
  var room = $("room"), label = $("roomLabel"), big = $("roomBig"), sub = $("roomSub"), bar = $("roomBar"), fill = $("roomFill");
  var recent = $("roomRecent"), list = $("roomList"), banner = $("roomBanner"), bannerText = $("roomBannerText");
  var fireworks = window.createBingoFireworks ? window.createBingoFireworks($("roomFireworks")) : null;

  var on = body.dataset.room === "1", sound = body.dataset.sound === "1", started = body.dataset.started === "1", ended = body.dataset.ended === "1";
  var startingUntil = 0;          // while > now: "Game starting in N"
  var cur = null;                 // {id, title, artist, pos, at, paused}
  var songs = [];                 // earlier songs, newest first
  var tick = null;

  function esc(s) { return String(s == null ? "" : s); }

  function setBig(text, isNum) { big.textContent = text; big.classList.toggle("num", !!isNum); }

  function renderRecent() {
    list.textContent = "";
    songs.slice(0, 1).forEach(function (s) {      // just the song before this one
      var li = document.createElement("li");
      li.textContent = s.title;
      if (s.artist) { var sp = document.createElement("span"); sp.textContent = " – " + s.artist; li.appendChild(sp); }
      list.appendChild(li);
    });
    recent.classList.toggle("empty", songs.length === 0);
  }

  // Text is as big as the screen allows: a very long title steps the sizes down until everything fits
  var fitKey = "";
  function fitText() {
    var main = big.parentElement;
    var key = [label.textContent, big.textContent, sub.textContent, bar.hidden, innerWidth, innerHeight].join("|");
    if (key === fitKey) return;
    fitKey = key;
    var scale = 1;
    room.style.setProperty("--rs", "1");
    while (scale > 0.35 && (main.scrollHeight > main.clientHeight + 1 || main.scrollWidth > main.clientWidth + 1)) {
      scale -= 0.07;
      room.style.setProperty("--rs", scale.toFixed(2));
    }
  }

  function render() { renderNow(); if (!room.hidden) fitText(); }
  function renderNow() {
    var show = on && (started || ended);
    body.classList.toggle("roomOn", show);
    room.hidden = !show;
    if (!show) return;
    var now = Date.now();
    bar.hidden = true;
    if (ended) { label.textContent = ""; setBig("Game over", false); sub.textContent = "Thanks for playing!"; return; }
    if (startingUntil > now) {
      label.textContent = "Game starting in";
      setBig(String(Math.max(1, Math.ceil((startingUntil - now) / 1000))), true);
      sub.textContent = "";
      return;
    }
    if (!cur) { label.textContent = ""; setBig("Get ready…", false); sub.textContent = "The first song is on its way"; return; }
    var elapsed = cur.paused ? cur.pos : cur.pos + (now - cur.at);
    var remaining = REVEAL_MS - elapsed;
    if (remaining > 0) {
      label.textContent = "Song revealed in";
      setBig(String(Math.ceil(remaining / 1000)), true);
      sub.textContent = "Guess it by ear!";
      bar.hidden = false;
      fill.style.width = Math.max(0, Math.min(100, (elapsed / REVEAL_MS) * 100)) + "%";
    } else {
      label.textContent = cur.paused ? "Paused" : "Now playing";
      setBig(cur.title, false);
      sub.textContent = cur.artist;
    }
  }

  function handleTrack(m) {
    if (!m || m.type !== "track") return;
    var id = m.track_id || (m.title + "|" + m.artist);
    if (!cur || cur.id !== id) {
      if (cur && cur.title) songs.unshift({ title: cur.title, artist: cur.artist });
      renderRecent();
    }
    cur = { id: id, title: esc(m.title), artist: esc(m.artist), pos: Number(m.position_ms) || 0, at: Date.now(), paused: !!m.paused };
    render();
  }

  function hideBanner() { banner.hidden = true; if (fireworks) { try { fireworks.stop(); } catch (e) {} } }

  function handleMsg(m) {
    if (!m || typeof m !== "object") return;
    if (m.type === "room_reveal") { on = !!m.on; sound = !!m.sound; $("soundCtl").hidden = !(on && sound); render(); }
    else if (m.type === "game_started") {
      if (!started) { started = true; ended = false; if (on) startingUntil = Date.now() + START_SECS * 1000; }
      render();
    }
    else if (m.type === "track") handleTrack(m);
    else if (m.type === "room") {
      if (m.event === "bingo") {
        bannerText.textContent = "";
        bannerText.appendChild(document.createTextNode("BINGO!"));
        var s = document.createElement("small"); s.textContent = (m.winner_name || "Someone") + " got a Bingo"; bannerText.appendChild(s);
        banner.hidden = false;
        if (fireworks) { try { fireworks.start(10000); } catch (e) {} }
      } else if (m.event === "clear") hideBanner();
      else if (m.event === "game_over") { hideBanner(); ended = true; render(); }
    }
  }

  window.__roomHandle = handleMsg;     // test hook

  function connect() {
    var ws;
    try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/host/game/" + encodeURIComponent(CODE)); } catch (e) { return; }
    ws.onmessage = function (ev) { try { handleMsg(JSON.parse(ev.data)); } catch (e) {} };
    ws.onclose = function () { setTimeout(connect, 2000); };
  }

  // Opened (or reloaded) mid-game: pick up the song that is playing, with no starting countdown
  if (started && !ended) {
    fetch("/game/" + encodeURIComponent(CODE) + "/last_track_state", { credentials: "same-origin" })
      .then(function (r) { return r.json(); }).then(function (m) { if (m && m.type === "track") handleTrack(m); }).catch(function () {});
  }
  tick = setInterval(render, 250);
  render();
  connect();
})();
