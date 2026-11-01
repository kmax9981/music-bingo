/* Play Alone: the 10-second song reveal with its countdown, and the Bingo hint. Needs window.BINGO_SOLO (set in play_solo.html). */
// Shows the current song after 10s of play, with the hosted card's countdown until then. The song is
// added to Played Tracks (onReveal) when it's revealed, or when the next song starts, whichever is first,
// so the list doesn't give the answer away.
// Fed by the Spotify player's state events: update({uri, title, artist, posMs, paused, onReveal}).
// ---- Bingo hints (per game, remembered on this device) ----
(function(){
  var KEY = "soloHint:" + window.BINGO_SOLO.code, chk = null, last = null;
  function grid(){ return document.getElementById("soloCardGrid"); }
  function apply(){
    if (!window.BingoHint) return;
    if (chk && chk.checked && last) window.BingoHint.show(grid(), last.title, window.BINGO_SOLO.code + ":" + last.uri);
    else window.BingoHint.clear(grid());
  }
  window.__soloHintTrack = function(title, uri){
    if (!title) { last = null; apply(); return; }
    if (last && last.uri === uri) return;   // same song: keep the same column
    last = { title: title, uri: uri }; apply();
  };
  document.addEventListener("DOMContentLoaded", function(){
    chk = document.getElementById("soloHintChk");
    if (!chk) return;
    try { chk.checked = localStorage.getItem(KEY) === "1"; } catch(_) {}
    chk.addEventListener("change", function(){ try { localStorage.setItem(KEY, chk.checked ? "1" : "0"); } catch(_) {} apply(); });
    apply();
  });
})();

window.__soloReveal = (function(){
  const REVEAL_MS = 10000;
  const SHOWN_KEY = "soloNowPlaying:" + window.BINGO_SOLO.code;
  const $ = (id) => document.getElementById(id);
  const titleEl = $("npTitle"), artistEl = $("npArtist");
  const cd = $("npCountdown"), cdNum = $("npcNum"), cdLabel = $("npcLabel"), cdSub = $("npcSub"), cdFill = $("npcFill"), cdSr = $("npcSr");
  let shownUri = "", pending = null, revealTimer = null, tick = null;
  // Spotify keeps reporting the song left over from before this game (the previous game's last song)
  // until our playlist takes over. Ignore everything until the game's own playback has started, then
  // ignore that leftover song and, for a fresh start, anything not near the start of a song.
  let gameStarted = false, blockedUri = "", needFreshStart = false;
  // Right after a song change Spotify's first updates can still carry the previous song's position
  // (the seek-to-0 guard elsewhere exists for the same reason), which made a skipped-to song reveal
  // at once. Only the first song seen after the page loads (a refresh mid-song) is taken at face value.
  let firstSongThisPage = true;
  const STALE_WINDOW_MS = 3000;

  function setBox(title, artist){ titleEl.textContent = title || ""; artistEl.textContent = artist || ""; }
  try {  // a refresh keeps showing the last revealed song
    const saved = JSON.parse(sessionStorage.getItem(SHOWN_KEY) || "null");
    if (saved && saved.uri) { shownUri = saved.uri; setBox(saved.title, saved.artist); }
  } catch(_) {}

  function setFill(fraction, durationMs){
    cdFill.style.transition = "none";
    cdFill.style.width = (Math.max(0, Math.min(1, fraction)) * 100) + "%";
    if (durationMs > 0) {
      void cdFill.offsetWidth;  // commit the start width before animating
      cdFill.style.transition = `width ${durationMs}ms linear`;
      cdFill.style.width = "100%";
    }
  }
  function stopCountdown(){
    if (tick) clearInterval(tick);
    tick = null;
    cd.hidden = true; cd.classList.remove("isPaused");
  }
  function startCountdown(remainingMs){
    const end = Date.now() + remainingMs, wasHidden = cd.hidden;
    cd.classList.remove("isPaused");
    cdLabel.textContent = "Song revealed in"; cdSub.textContent = "Guess it by ear";
    cd.hidden = false;
    setFill(1 - remainingMs / REVEAL_MS, remainingMs);
    const step = () => {
      const left = Math.max(0, end - Date.now());
      cdNum.textContent = String(Math.ceil(left / 1000));
      if (left <= 0 && tick) { clearInterval(tick); tick = null; }
    };
    if (tick) clearInterval(tick);
    step(); tick = setInterval(step, 200);
    if (wasHidden) cdSr.textContent = `New song playing. Title shows in ${Math.ceil(remainingMs / 1000)} seconds.`;
  }
  function pauseCountdown(remainingMs){
    if (tick) clearInterval(tick);
    tick = null;
    cd.classList.add("isPaused");
    cdLabel.textContent = "Paused"; cdNum.textContent = ""; cdSub.textContent = "Resumes with the music";
    cd.hidden = false;
    setFill(1 - remainingMs / REVEAL_MS, 0);
    cdSr.textContent = "Song paused.";
  }
  function clearRevealTimer(){ if (revealTimer) clearTimeout(revealTimer); revealTimer = null; }

  function reveal(){
    clearRevealTimer(); stopCountdown();
    if (!pending) return;
    const p = pending; pending = null;
    shownUri = p.uri;
    setBox(p.title, p.artist);
    try { sessionStorage.setItem(SHOWN_KEY, JSON.stringify({ uri: p.uri, title: p.title, artist: p.artist })); } catch(_) {}
    try { if (p.onReveal) p.onReveal(); } catch(_) {}
  }

  function update(st){
    const uri = String((st && st.uri) || "");
    if (!uri || !gameStarted) return;
    const pos = Number(st.posMs) || 0;
    // The leftover song stays blocked (late events keep reporting it mid-song) until it really plays from
    // the start, e.g. when the shuffle reaches it, or when the random first song happens to be the same one.
    if (blockedUri && uri === blockedUri) {
      if (pos > 1500) return;
      blockedUri = "";
    }
    if (needFreshStart) {
      if (pos > 5000) return;
      needFreshStart = false;
    }
    if (uri === shownUri) {  // already revealed; just keep it recorded
      try { if (st.onReveal) st.onReveal(); } catch(_) {}
      return;
    }
    if (!pending || pending.uri !== uri) {
      clearRevealTimer();
      const trustPos = firstSongThisPage;
      // The previous song was heard even if it never reached 10s (e.g. Next during the countdown):
      // still add it to Played Tracks, just without showing it in the box.
      if (pending) { try { if (pending.onReveal) pending.onReveal(); } catch(_) {} }
      pending = { uri, seenAt: Date.now(), trustPos };
      setBox("", "");  // a new song: hide the previous one until this is revealed
    }
    firstSongThisPage = false;
    pending.title = st.title || pending.title || "";
    pending.artist = st.artist || pending.artist || "";
    if (st.onReveal) pending.onReveal = st.onReveal;

    let posMs = Math.max(0, Number(st.posMs) || 0);
    const sinceSeen = Date.now() - pending.seenAt;
    if (!pending.trustPos && sinceSeen < STALE_WINDOW_MS) posMs = Math.min(posMs, sinceSeen + 500);
    if (posMs >= REVEAL_MS) { reveal(); return; }
    clearRevealTimer();
    if (st.paused) { pauseCountdown(REVEAL_MS - posMs); return; }
    startCountdown(REVEAL_MS - posMs);
    revealTimer = setTimeout(reveal, REVEAL_MS - posMs + 50);
  }

  // Bingo: reveal (and record) the song now, so a square dabbed by ear counts.
  document.addEventListener("click", (ev) => {
    try { if (ev.target && ev.target.closest && ev.target.closest("#btnBingo")) reveal(); } catch(_) {}
  }, true);

  // Before starting the playlist: forget anything seen so far (it isn't this game's), block leftoverUri.
  function beginGame(leftoverUri){
    clearRevealTimer(); stopCountdown();
    pending = null; gameStarted = false;
    blockedUri = String(leftoverUri || "");
  }
  // Playback for this game is running. fresh = just started the playlist (vs. a page refresh mid-game).
  function playbackStarted(fresh){
    needFreshStart = !!fresh;
    if (!fresh) blockedUri = "";
    gameStarted = true;
  }

  return { update, reveal, beginGame, playbackStarted, stop(){ clearRevealTimer(); stopCountdown(); } };
})();
