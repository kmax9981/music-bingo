/* Host game page: Spotify player, game controls, claims, hints, live updates. Needs window.BINGO_HOST = {code, status, paperCount} (set in host_game.html). */
/*
   Prevents "onSpotifyWebPlaybackSDKReady is not defined" / AnthemError when the Spotify Web Playback SDK loads.
*/
window.onSpotifyWebPlaybackSDKReady = window.onSpotifyWebPlaybackSDKReady || function () {
  try { window.__spotify_sdk_ready = true; } catch(e) {}
};

(function(){

  // ---- Utilities ----
  const CODE = window.BINGO_HOST.code;
  window.__hostContinueSeq = 0;
  // Persisted game state (server-rendered)
  const __GAME_STATUS = window.BINGO_HOST.status;
  const __GAME_STARTED = (__GAME_STATUS === "started");
  const __GAME_ENDED = (__GAME_STATUS === "ended");
  try {
    if (__GAME_ENDED) {
      const sb = document.getElementById("startBtn");
      if (sb) { sb.disabled = true; sb.classList.add("disabled"); }
      const ab = document.getElementById("admitBtn");
      if (ab) { ab.disabled = true; ab.classList.add("disabled"); }
      const ed = document.getElementById("btnEndGame");
      if (ed) { ed.disabled = true; ed.classList.add("disabled"); }
      for (const id of ["playBtn", "pauseBtn", "nextBtn"]) {
        const tb = document.getElementById(id);
        if (tb) { tb.disabled = true; tb.classList.add("disabled"); }
      }
      const cg = document.getElementById("btnContinueGame");
      if (cg) { cg.disabled = true; cg.classList.add("disabled"); }
      const bar = document.getElementById("bingoDecisionBar");
      if (bar) { bar.classList.add("hidden"); }
      try { setMsg("Game Ended ✅"); } catch(_){}
    }
  } catch(_) {}

  function __isEnded(){
    try { return (String(__GAME_STATUS || "").toLowerCase() === "ended"); } catch(e){ return false; }
  }

  try { window.__bingoGameStarted = __GAME_STARTED; 
} catch(_) {}

  try {
    if (window.__bingoGameStarted) {
      const sb = document.getElementById("startBtn");
      if (sb) { sb.disabled = true; sb.classList.add("disabled"); }
    }
  } catch(_) {}

  const msg = document.getElementById("hostMsg");

  function setMsg(t){
  // Inline status line (below Admit/Start). Keep layout stable.
  try {
    const el = document.getElementById('hostMsg');
    if (!el) return;
    const txt = (t || '').toString();
    el.textContent = txt;
    el.title = txt;
  } catch(_) {}
}

  function setTransportMsg(t){
    // Transport status line (below Play/Pause/Next). Single-line overwrite.
    try {
      const el = document.getElementById('transportMsg');
      if (!el) return;
      const txt = (t || '').toString();
      el.textContent = txt;
    } catch(_) {}
  }

  async function postJson(url, bodyObj){
    const opts = { method: "POST", credentials: "same-origin" };
    if (bodyObj !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(bodyObj);
    }
    const r = await fetch(url, opts);
    const j = await r.json().catch(()=> ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  // ---- Counters (players / songs) ----
  function __updateCounters(){
    try {
      const pc = document.getElementById("playersCount");
      if (pc) {
        const items = document.querySelectorAll("#playersList .playerRow, #playersList li, #playersList .row");
        pc.textContent = String(items.length || 0);
      }
      const sc = document.getElementById("songsCount");
      if (sc) {
        const items = document.querySelectorAll("#playedList .chip, #playedList li");
        sc.textContent = String(items.length || 0);
      }
    } catch(_) {}
  }
  try { window.__updateCounters = __updateCounters; } catch(_) {}

  // ---- Copy join link (click the text) ----
  const joinLink = document.getElementById("joinLink");
  if (joinLink) {
    joinLink.style.cursor = "pointer";
    joinLink.addEventListener("click", async () => {
      joinLink.select();
      const hint = document.getElementById("copyHint");
      try {
        await navigator.clipboard.writeText(joinLink.value);
        if (hint) { hint.textContent = "Copied join link ✅"; setTimeout(() => { hint.textContent = "Click the link to copy it"; }, 2000); }
      } catch(_) {
        if (hint) hint.textContent = "Couldn't copy (browser permissions)";
      }
    });
  }

  // ---- Start / End Game / Play again: one slot that follows the game's state ----
  window.__showGameState = function(st){
    window.__gameStatus = st;
    try { if (window.__syncPatternLock) window.__syncPatternLock(); } catch(_) {}
    const show = (el, on) => { if (el) el.classList.toggle("isHidden", !on); };
    show(document.getElementById("startBtn"), st === "lobby");
    show(document.getElementById("endGameMainBtn"), st === "started");
    show(document.getElementById("playAgainForm"), st === "ended");
    if (st === "ended") {
      window.__bingoEnded = true;
      const ab = document.getElementById("admitBtn");
      if (ab) { ab.disabled = true; ab.classList.add("disabled"); }
      // The game is over: no more music controls, and stop whatever is still playing in this browser
      for (const id of ["playBtn", "pauseBtn", "nextBtn"]) {
        const b = document.getElementById(id);
        if (b) { b.disabled = true; b.classList.add("disabled"); }
      }
      try { if (typeof player !== "undefined" && player) player.pause(); } catch(_) {}
    }
  };
  async function __endGame(){
    const r = await fetch(`/host/game/${CODE}/end_game${window.__gameDeviceQuery ? window.__gameDeviceQuery() : ""}`, { method: "POST", credentials: "same-origin" });
    if (!r.ok && r.status !== 409) throw new Error("HTTP " + r.status);
    window.__showGameState("ended");
    try { setMsg("Game ended ✅"); } catch(_) {}
  }
  const endMainBtn = document.getElementById("endGameMainBtn");
  if (endMainBtn) {
    endMainBtn.addEventListener("click", async () => {
      if (!confirm("End this game? Players will see it is over and the music stops. You can play it again afterwards.")) return;
      endMainBtn.disabled = true;
      try { await __endGame(); } catch(e) {
        setMsg("End Game failed: " + String(e && e.message ? e.message : e));
      } finally { endMainBtn.disabled = false; }
    });
  }

  // ---- Bingo hints (per game): off / everyone / players choose ----
  const hintOn = document.getElementById("hintOn"), hintOptin = document.getElementById("hintOptin"), hintOptinWrap = document.getElementById("hintOptinWrap");
  async function __saveHintMode(){
    const mode = !hintOn.checked ? "off" : (hintOptin.checked ? "optin" : "all");
    if (hintOptin) hintOptin.disabled = !hintOn.checked;
    if (hintOptinWrap) hintOptinWrap.classList.toggle("isOff", !hintOn.checked);
    try {
      const r = await fetch(`/host/game/${CODE}/hint_mode`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setMsg(mode === "off" ? "Hints off" : (mode === "all" ? "Hints on for everyone" : "Players can choose hints"));
    } catch(e) { setMsg("Couldn't change hints: " + String(e && e.message ? e.message : e)); }
  }
  if (hintOn) hintOn.addEventListener("change", __saveHintMode);
  if (hintOptin) hintOptin.addEventListener("change", __saveHintMode);

  // ---- What counts as bingo (any line, four corners, X, ...) ----
  const patternSel = document.getElementById("patternSel");
  // The pattern can change before the game starts, or between rounds (once a bingo is accepted): not while a round is being played.
  window.__syncPatternLock = function(){
    if (!patternSel) return;
    const st = window.__gameStatus || __GAME_STATUS;
    const bar = document.getElementById("bingoDecisionBar");
    const afterBingo = !!bar && !bar.classList.contains("hidden");
    const locked = !(st === "lobby" || (st === "started" && afterBingo));
    patternSel.disabled = locked;
    const note = document.getElementById("patternLock"); if (note) note.hidden = !locked || st === "ended";
  };
  document.addEventListener("pattern:update", (e) => {
    const full = document.getElementById("btnContinueFull"); if (full) full.hidden = e.detail.key === "full";
  });
  if (patternSel) patternSel.addEventListener("change", async () => {
    try {
      const r = await __postJson(`/host/game/${CODE}/pattern`, { pattern: patternSel.value });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || ("HTTP " + r.status));
      window.PatternBadge.update(j);
      setMsg("Bingo is now: " + j.label);
    } catch(e) { setMsg("Couldn't change the pattern: " + String(e && e.message ? e.message : e)); try { patternSel.value = (document.querySelector("#patternRow .patternBadge") || {}).dataset.pattern || patternSel.value; } catch(_) {} }
  });
  window.__syncPatternLock();

  // ---- Co-host link: a second person decides bingo calls from their own phone ----
  const cohostBtn = document.getElementById("cohostBtn"), cohostBox = document.getElementById("cohostBox"), cohostUrl = document.getElementById("cohostUrl");
  async function __cohost(action){
    const r = action ? await __postJson(`/host/game/${CODE}/cohost`, { action }) : await fetch(`/host/game/${CODE}/cohost`, { credentials: "same-origin" });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j.url;
  }
  if (cohostBtn) cohostBtn.addEventListener("click", async () => {
    if (!cohostBox.hidden) { cohostBox.hidden = true; return; }
    try {
      let url = await __cohost("");
      if (!url) url = await __cohost("on");
      cohostUrl.value = url; cohostBox.hidden = false; cohostUrl.select();
    } catch(e) { setMsg("Couldn't make the co-host link: " + String(e && e.message ? e.message : e)); }
  });
  const cohostCopy = document.getElementById("cohostCopy"), cohostOff = document.getElementById("cohostOff");
  if (cohostCopy) cohostCopy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(cohostUrl.value); setMsg("Co-host link copied"); } catch(_) { cohostUrl.select(); setMsg("Press Ctrl+C to copy the link"); }
  });
  if (cohostOff) cohostOff.addEventListener("click", async () => {
    try { await __cohost("off"); cohostBox.hidden = true; cohostUrl.value = ""; setMsg("Co-host link turned off"); } catch(e) { setMsg("Couldn't turn it off: " + String(e && e.message ? e.message : e)); }
  });

  // ---- Song reveal on the QR screen (room display), and optionally its speaker ----
  const roomRevealOn = document.getElementById("roomRevealOn"), roomSoundOn = document.getElementById("roomSoundOn"), roomSoundWrap = document.getElementById("roomSoundWrap");
  async function __saveRoom(){
    if (roomSoundOn) roomSoundOn.disabled = !roomRevealOn.checked;
    if (roomSoundWrap) roomSoundWrap.classList.toggle("isOff", !roomRevealOn.checked);
    try {
      const r = await fetch(`/host/game/${CODE}/room_reveal`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on: roomRevealOn.checked, sound: !!(roomSoundOn && roomSoundOn.checked) }) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setMsg(!roomRevealOn.checked ? "QR screen: QR code only" : (roomSoundOn && roomSoundOn.checked ? "QR screen: reveal + music button" : "QR screen: song reveal on"));
    } catch(e) { setMsg("Couldn't change the QR screen: " + String(e && e.message ? e.message : e)); }
  }
  if (roomRevealOn) roomRevealOn.addEventListener("change", __saveRoom);
  if (roomSoundOn) roomSoundOn.addEventListener("change", __saveRoom);

  // ---- Claim times: shown in the host's own clock (the server stores UTC) ----
  function __localizeClaimTimes(){
    try {
      document.querySelectorAll("time.claimTime").forEach((el) => {
        const d = new Date(el.getAttribute("datetime"));
        if (!isNaN(d.getTime())) el.textContent = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
      });
    } catch(_) {}
  }
  __localizeClaimTimes();
  try {
    const __claimsEl = document.getElementById("claimsList");
    if (__claimsEl) new MutationObserver(__localizeClaimTimes).observe(__claimsEl, { childList: true });
  } catch(_) {}

  // ---- Admit all ----
  const admitBtn = document.getElementById("admitBtn");
  if (admitBtn) {
    admitBtn.addEventListener("click", async () => {
      setMsg("");
      try {
        await postJson(`/host/game/${CODE}/admit_all`);
        setMsg(window.__bingoGameStarted ? "Admitted the waiting players ✅" : "Admitted + generated cards ✅");
      } catch(e) {
        setMsg(String(e && e.message ? e.message : e));
      }
    });
  }

  // ---- Played list live chips + Now Playing ----
  
  // Normalize titles for UI (do not show " - Single Version" etc)
  function __bingoCleanTitle(t) {
    let s = String(t || "");
    // Common suffixes we never want on cards/UI
    s = s.replace(/\s*-\s*single\s+version\s*$/i, "");
    s = s.replace(/\s*\(\s*single\s+version\s*\)\s*$/i, "");
    s = s.replace(/\s*-\s*radio\s+edit\s*$/i, "");
    s = s.replace(/\s*\(\s*radio\s+edit\s*\)\s*$/i, "");
    // Light cleanup
    s = s.replace(/\s{2,}/g, " ").trim();
    return s;
  }

  const playedListEl = document.getElementById("playedList");
  function addPlayedTrack(title, artist, trackId){
    if (!playedListEl) return;
    // (was a bare identifier: threw ReferenceError, so this never ran)
    const tRaw = (title || "").trim();
    const t = __bingoCleanTitle(tRaw);
    const a = (artist || "").trim();
    const id = (trackId || "").trim();

    // Build a stable key for dedupe (prefer trackId, fall back to text)
    const key = id ? ("id:" + id) : ("ta:" + t + "||" + a);

    // Normalize helper for comparing existing chip text (covers server-rendered chips)
    const __norm = (v) => String(v || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

    const wantText = __norm(a ? (`${t} — ${a}`) : t);

    // If the newest chip already matches, don't add a duplicate.
    // NOTE: server-rendered chips often do not have data-track-key, so compare text too.
    try {
      const first = playedListEl.querySelector(".chip, li");
      if (first) {
        const firstKey = (first.getAttribute("data-track-key") || "").trim();
        if (firstKey && firstKey === key) return;

        const firstText = __norm(first.textContent || "");
        if (firstText && wantText && firstText === wantText) {
          // retro-fit key onto existing chip so later dedupe is stronger
          try { if (key) first.setAttribute("data-track-key", key); } catch(_) {}
          return;
        }
      }
    } catch(_) {}

    // Prevent duplicates that already exist anywhere in the list (defensive).
    // Prefer key lookup when available; otherwise scan the top few chips by text.
    try {
      if (key) {
        if (playedListEl.querySelector('.chip[data-track-key="' + CSS.escape(key) + '"]')) return;
      } else {
        const chips = playedListEl.querySelectorAll(".chip, li");
        for (let i = 0; i < Math.min(12, chips.length); i++) {
          const txt = __norm(chips[i].textContent || "");
          if (txt && wantText && txt === wantText) return;
        }
      }
    } catch(_) {}

    const chip = document.createElement("div");
    chip.className = "chip";
    try { chip.setAttribute("data-track-key", key); } catch(_) {}

    // Build stable markup from the start (prevents title/artist “flash” on refresh)
    const titleSpan = document.createElement('span');
    titleSpan.className = 'playedTrackTitle';
    titleSpan.textContent = title;

    const artistSpan = document.createElement('span');
    artistSpan.className = 'playedTrackArtist';
    artistSpan.textContent = '— ' + artist;

    chip.textContent = '';
    chip.appendChild(titleSpan);
    chip.appendChild(document.createTextNode(' '));
    chip.appendChild(artistSpan);

    playedListEl.prepend(chip);
  }

  // ---- Now Playing timer (sync with Spotify playback position) ----
  const __npTimerEl = document.getElementById("hostNpTimer");
  let __npTicker = null;
  let __npPosMs = 0;
  let __npDurMs = 0;
  let __npPaused = true;
  let __npLastTick = 0;

  function __fmtMs(ms){
    ms = Math.max(0, Number(ms)||0);
    const total = Math.floor(ms/1000);
    const m = Math.floor(total/60);
    const s = total % 60;
    return String(m) + ":" + String(s).padStart(2,"0");
  }

  function __renderNpTimer(){
    if (!__npTimerEl) return;
    // Nothing loaded yet: show no time at all instead of 0:00
    const loaded = (__npDurMs > 0) || (__npPosMs > 0);
    __npTimerEl.textContent = loaded ? __fmtMs(__npPosMs) : "";
  }

  function __stopNpTicker(){
    if (__npTicker) { clearInterval(__npTicker); __npTicker = null; }
  }

  function __startNpTicker(){
    if (__npTicker) return;
    __npLastTick = Date.now();
    __npTicker = setInterval(() => {
      try {
        if (__npPaused) { __stopNpTicker(); return; }
        const now = Date.now();
        const delta = now - (__npLastTick || now);
        __npLastTick = now;
        __npPosMs = Math.min(__npDurMs || 1e12, (__npPosMs || 0) + delta);
        __renderNpTimer();
      } catch(_) {}
    }, 250);
  }

  // ---- Soft refresh helpers (fetch the same page and replace an element's innerHTML) ----
  async function __fetchAndReplaceById(id){
    try {
      const r = await fetch(location.pathname, { credentials: "same-origin", cache: "no-store" });
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById(id);
      const cur = document.getElementById(id);
      if (!cur || !fresh) return false;
      cur.innerHTML = fresh.innerHTML;
      return true;
    } catch(_) {
      return false;
    }
  }

  // Refreshes asked for within a moment of each other are combined (a later request used to replace an earlier one)
  let __refreshTimer = null;
  const __pendingRefresh = new Set();
  function __scheduleRefresh(which){
    __pendingRefresh.add(which);
    if (__refreshTimer) clearTimeout(__refreshTimer);
    __refreshTimer = setTimeout(async () => {
      const wanted = Array.from(__pendingRefresh);
      __pendingRefresh.clear();
      try {
        const all = wanted.some(w => w !== "played" && w !== "claims" && w !== "players");
        if (all || wanted.includes("claims")) await __fetchAndReplaceById("claimsList");
        if (all || wanted.includes("played")) await __fetchAndReplaceById("playedList");
        if (all || wanted.includes("players")) await __fetchAndReplaceById("playersList");
        __updateCounters();
      } catch(_) {}
    }, 150);
  }

  // ---- Players: Admit / Kick one player (the list is re-rendered by soft refreshes, so listen on the list itself) ----
  const pl = document.getElementById("playersList");
  if (pl) {
    pl.addEventListener("click", async (e) => {
      const ad = e.target.closest("button[data-player-admit]");
      const kick = e.target.closest("button[data-player-kick]");
      const btn = ad || kick;
      if (!btn) return;
      const row = btn.closest(".playerRow");
      const nm = row && row.querySelector(".playerName") ? row.querySelector(".playerName").textContent.trim() : "this player";
      if (kick && !window.confirm("Remove " + nm + " from the game? Their card and any bingo claim are deleted.")) return;
      btn.disabled = true;
      try {
        await postJson(`/host/game/${CODE}/player/${ad ? ad.dataset.playerAdmit : kick.dataset.playerKick}/${ad ? "admit" : "kick"}`);
        setMsg(ad ? nm + " admitted ✅" : nm + " removed");
        __scheduleRefresh("players");
        if (kick) __scheduleRefresh("claims");
      } catch (err) {
        setMsg(String(err && err.message ? err.message : err));
        btn.disabled = false;
      }
    });
  }

  // ---- Claims: accept/reject + show decision bar on accepted ----
  const cl = document.getElementById("claimsList");
  if (cl) {
    cl.addEventListener("click", async (e) => {
      const rm = e.target.closest("button[data-claim-delete]");
      if (rm) {
        rm.disabled = true;
        try {
          const r = await fetch(`/host/game/${CODE}/claim/${rm.getAttribute("data-claim-delete")}/delete`, { method: "POST", credentials: "same-origin" });
          if (!r.ok) { const j = await r.json().catch(() => ({})); setMsg(j.error || "Couldn't remove the claim"); }
        } catch(err) { setMsg(String(err && err.message ? err.message : err)); }
        __scheduleRefresh("claims");
        return;
      }
      const btn = e.target.closest("button[data-claim]");
      if (!btn) return;
      const claimId = btn.getAttribute("data-claim");
      const status = btn.getAttribute("data-status");
      if (!(window.__bingoGameStarted)) { setMsg(""); }
      try {
        const form = new URLSearchParams({ status });
        const r = await fetch(`/host/game/${CODE}/claim/${claimId}/set`, {
          method: "POST",
          headers: {"Content-Type":"application/x-www-form-urlencoded"},
          body: form.toString(),
          credentials: "same-origin"
        });
        const j = await r.json().catch(()=> ({}));
        if (r.ok) {
          setTransportMsg("Claim " + status + " ✅");
          if (status === "accepted") {
            const bar = document.getElementById("bingoDecisionBar");
            if (bar) bar.classList.remove("hidden");
          }
        } else {
          setMsg(j.error || "Failed to update claim");
        }
      } catch(err) {
        setMsg(String(err && err.message ? err.message : err));
      } finally {
        __scheduleRefresh("claims");
      }
    });
  }

  // ---- Post-accept decision buttons (Continue / End) ----
  const __decisionBar = document.getElementById("bingoDecisionBar");
  const __btnContinue = document.getElementById("btnContinueGame");
  const __btnEnd = document.getElementById("btnEndGame");

  

  // If host refreshes after a bingo was already accepted, the server renders the claim as 'Accepted'
  // but the decision bar can remain hidden (because it's normally shown only on the click-handler).
  // This restores the Continue/End buttons on page load.
  try {
    const accepted = !!document.querySelector(`#claimsList .claimRow[data-status="accepted"][data-round="${window.BINGO_HOST.round}"]`);   // a bingo accepted in THIS round (older rounds' wins don't count)
    if (accepted && __decisionBar) __decisionBar.classList.remove('hidden');
  } catch(_) {}
async function __postJson(url, body){
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  }
async function __postNoBody(url){
    const r = await fetch(url, { method: "POST", credentials: "same-origin" });
    return r;
  }

  if (__btnContinue) {
    __btnContinue.addEventListener("click", async () => {
      try { await __postJson(`/host/game/${CODE}/continue_game`, {}); } catch(_) {}
      try { if (__decisionBar) __decisionBar.classList.add("hidden"); } catch(_) {}
      __scheduleRefresh("claims");
    });
  }
  const __btnContinueFull = document.getElementById("btnContinueFull");
  if (__btnContinueFull) {
    __btnContinueFull.addEventListener("click", async () => {
      try { await __postJson(`/host/game/${CODE}/continue_game`, { pattern: "full" }); } catch(_) {}
      try { if (__decisionBar) __decisionBar.classList.add("hidden"); } catch(_) {}
      __scheduleRefresh("claims");
    });
  }
  // the pattern box follows the decision bar: open after a bingo, locked once the next round starts
  if (__decisionBar && window.MutationObserver) new MutationObserver(() => { try { window.__syncPatternLock(); } catch(_) {} }).observe(__decisionBar, { attributes: true, attributeFilter: ["class"] });
  try { window.__syncPatternLock(); } catch(_) {}
  if (__btnEnd) {
    __btnEnd.addEventListener("click", async () => {
      try { await __endGame(); } catch(e) { try { setMsg("End Game failed: " + String(e && e.message ? e.message : e)); } catch(_) {} }
      try { if (__decisionBar) __decisionBar.classList.add("hidden"); } catch(_) {}
      __scheduleRefresh("claims");
    });
  }

  // ---- Spotify Web Playback SDK (embedded player) ----
  const sdkStatusEl = document.getElementById("sdkStatus");
  function setSdkStatus(t){
    try { const x=document.getElementById("deviceTransferStatus"); if (x && (t||"").toString().trim()) { x.style.display="none"; } } catch(_) {}
if (sdkStatusEl) sdkStatusEl.textContent = t;
    try { console.log("[Spotify SDK]", t); } catch(_) {}
  }
  try { window.setSdkStatus = setSdkStatus; } catch(_) {}

  let player = null;

  // ~1s after Play/Pause, re-read the player and send its state even if nothing "changed": right after
  // resume()/pause() getCurrentState() can still report the old state, so this makes the last word correct.
  window.__bingoSettleTrackState = function () {
    setTimeout(async () => {
      try { if (window.__bingoTrackPing) window.__bingoTrackPing.lastAt = 0; } catch(_) {}
      try { await window.__bingoFlushTrackState(); } catch(_) {}
    }, 1000);
  };

  // Send the current (or last seen) player state right after track updates are enabled.
  window.__bingoFlushTrackState = async function () {
    try {
      let s = null;
      try { if (player) s = await player.getCurrentState(); } catch(_) {}
      s = s || window.__bingoPendingState;
      window.__bingoPendingState = null;
      if (s && window.__bingoOnPlayerState) window.__bingoOnPlayerState(s);
    } catch(_) {}
  };
  let sdkDeviceId = "";
  let sdkReady = false;
  // ---- Start Game gating (must have a playback device ready) ----
  const __startBtn = document.getElementById("startBtn");
  function __hasStartDevice(){
    try {
      // External device selected?
      if (typeof window.__bingoChosenDeviceId === "string" && window.__bingoChosenDeviceId.trim()) return true;
    } catch(_) {}
    try {
      // Embedded SDK device ready?
      if (typeof sdkDeviceId === "string" && sdkDeviceId.trim() && sdkReady) return true;
    } catch(_) {}
    return false;
  }
  function __updateStartBtn(){
    if (!__startBtn) return;
    try {
      if (window.__bingoGameStarted) {
        __startBtn.disabled = true;

      /*
         If the 'no device' warning is currently displayed and a device becomes available,
         clear it automatically.
      */
      try {
        const WARN = "Playback device not set. Pick a device in the dropdown, or leave it on Embedded.";
        const hostMsgEl = document.getElementById("hostMsg");
        const topMsgEl = null /* removed #msg */;
        const curTxt = (topMsgEl && typeof topMsgEl.textContent === "string" && topMsgEl.textContent.trim())
          || (hostMsgEl && typeof hostMsgEl.textContent === "string" && hostMsgEl.textContent.trim())
          || "";
        if (curTxt === WARN && typeof __startBtn !== "undefined" && __startBtn && __startBtn.disabled === false) {
          if (!(window.__bingoGameStarted)) { setMsg(""); }
        }
      } catch(_) {}
        __startBtn.classList.add("disabled");
        return;
      }
    } catch(_) {}

    if (__hasStartDevice()) {
      __startBtn.disabled = false;
      __startBtn.classList.remove("disabled");
      return;
    }
    __startBtn.disabled = false;
    __startBtn.classList.remove("disabled");
}

  function waitForSpotifySDK(timeoutMs=8000){
    return new Promise((resolve, reject) => {
      if (window.Spotify && window.Spotify.Player) return resolve(true);
      const start = Date.now();
      const t = setInterval(() => {
        if (window.Spotify && window.Spotify.Player) { clearInterval(t); resolve(true); return; }
        if (Date.now() - start > timeoutMs) { clearInterval(t); reject(new Error("Spotify SDK not available")); }
      }, 100);
    });
  }

  async function fetchAccessToken(){
    const r = await fetch(`/api/spotify/token`, { credentials: "same-origin", cache: "no-store" });
    const j = await r.json().catch(()=> ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j.access_token;
  }

  async function startEmbeddedPlayer(){
    try {
      setSdkStatus("Starting embedded player…");
      await waitForSpotifySDK();
      if (player) { setSdkStatus("Embedded player already started."); return; }

      player = new window.Spotify.Player({
        name: "Bingo Host Player",
        getOAuthToken: async (cb) => {
          try { cb(await fetchAccessToken()); } catch(e){ console.error(e); cb(""); }
        },
        volume: 0.9
      });

      player.addListener("ready", async ({ device_id }) => {
        sdkDeviceId = device_id;
        sdkReady = true;
        
        try { __updateStartBtn(); } catch(_) {}
setSdkStatus("Embedded player ready ✅ (transferring playback…)");

        // Transfer playback to this device (do NOT auto-play game playlist here)
        try {
          await postJson("/api/spotify/transfer", { device_id: sdkDeviceId, play: false });
          try {
            const x = document.getElementById("deviceTransferStatus");
            if (x) { x.textContent = "Playback transferred ✅"; x.style.display = "block"; }
          } catch(_) {}
          setSdkStatus("");
        // Safety: stop any previously-resumed playback immediately on the SDK device.
        // This prevents the last session's track+timestamp from briefly playing/appearing.
        // IMPORTANT: do NOT interrupt host-initiated playback after the game has started.
        try {
          const __started = !!(window.__bingoGameStarted || window.__bingoEmbeddedPlaylistStarted);
          if (!__started) { await player.pause(); }
        } catch(_) {}

        } catch (e) {
          setSdkStatus("Transfer failed: " + String((e && e.message) ? e.message : e));
        }

        try { window.__bingoEmbeddedPlaylistStarted = false; } catch(_) {}
        // Start Game waits for this: the transfer+pause above must finish before the game playlist starts.
        try { window.__bingoSdkReadyHandled = true; } catch(_) {}
      });

      player.addListener("not_ready", () => { sdkReady=false; setSdkStatus("Embedded player went offline."); });
      player.addListener("initialization_error", ({ message }) => setSdkStatus("SDK init error: " + message));
      player.addListener("authentication_error", ({ message }) => setSdkStatus("SDK auth error: " + message));
      player.addListener("account_error", ({ message }) => setSdkStatus("SDK account error: " + message));
      player.addListener("playback_error", ({ message }) => setSdkStatus("SDK playback error: " + message));

      // Track updates -> your server
      let lastTrackId = null;
      const __onPlayerState = (state) => {
        try {
          // Updates are disabled until host-initiated Play finishes. Spotify only fires this event on
          // changes, so keep the latest state; __bingoFlushTrackState() sends it once updates are enabled
          // (otherwise the first song of the game is never recorded).
          if (typeof window !== "undefined" && !window.__bingoAllowTrackUpdates) { window.__bingoPendingState = state; return; }
          if (!state || !state.track_window || !state.track_window.current_track) return;

          const t = state.track_window.current_track;
          const artist = (t.artists && t.artists[0] && t.artists[0].name) ? t.artists[0].name : "";
          const posMs = (typeof state.position === "number") ? state.position : 0;
          const paused = !!state.paused;

          // ---- keep Now Playing timer in sync (UPDATE ON EVERY STATE CHANGE) ----
          try {
            __npPosMs = posMs;
            __npDurMs = (typeof state.duration === "number") ? state.duration : (__npDurMs || 0);
            __npPaused = paused;
            __renderNpTimer();
            if (!__npPaused) __startNpTicker(); else __stopNpTicker();
          } catch(_) {}

          // update UI title/artist immediately (host sees instantly; players are delayed)
          try {
            const tEl = document.getElementById("hostNpTitle");
            const aEl = document.getElementById("hostNpArtist");
            if (tEl) tEl.textContent = t.name || "";
            if (aEl) aEl.textContent = artist || "";
          } catch(_) {}

          // ---- POST updates to server ----
          // Track inserts happen server-side only when track_id changes.
          // But we still send pause/position updates periodically so players can reveal at 10s correctly.
          const now = Date.now();
          if (!window.__bingoTrackPing) window.__bingoTrackPing = { lastAt: 0, lastTrackId: null };

          const trackChanged = (t && t.id && t.id !== window.__bingoTrackPing.lastTrackId);
          // Never throttle a paused<->playing flip: Spotify often reports paused then playing within
          // a second on track load, and dropping the "playing" update leaves players' reveal stuck.
          const pausedChanged = (paused !== window.__bingoTrackPing.lastPaused);
          const due = (now - (window.__bingoTrackPing.lastAt || 0)) >= 1000;

          if (trackChanged || pausedChanged || due) {
            window.__bingoTrackPing.lastAt = now;
            window.__bingoTrackPing.lastPaused = paused;
            window.__bingoTrackPing.lastTrackId = (t && t.id) ? t.id : window.__bingoTrackPing.lastTrackId;

            if (!(window.__bingoAllowTrackUpdates)) { return; }
            // Send updates one at a time, in order: two near-simultaneous posts (e.g. on resume) could
            // otherwise arrive reversed and leave players stuck on a stale "paused".
            const body = JSON.stringify({
              track_id: (t && t.id) ? t.id : "",
              title: t.name || "",
              artist,
              position_ms: posMs,
              paused: paused
            });
            window.__bingoTrackPostChain = (window.__bingoTrackPostChain || Promise.resolve())
              .then(() => fetch(`/host/game/${CODE}/track_update`, {
                method: "POST", headers: {"Content-Type":"application/json"}, body, credentials: "same-origin"
              }))
              .catch(()=>{});
          }

          if (t && t.id) {
            if (!window.__bingoLastTrackId) window.__bingoLastTrackId = null;
            if (t.id !== window.__bingoLastTrackId) {
              window.__bingoLastTrackId = t.id;
              __updateCounters();
            }
          }
        } catch(_) {}
      };
      player.addListener("player_state_changed", __onPlayerState);
      window.__bingoOnPlayerState = __onPlayerState;

      const ok = await player.connect();
      if (!ok) throw new Error("Spotify Player connect() returned false");
      setSdkStatus("Connecting…");
    } catch(e) {
      console.error(e);
      setSdkStatus(String((e && e.message) ? e.message : e));
    }
  }

  // publish for early click bridge
  try { window.__bingoStartEmbeddedPlayer = startEmbeddedPlayer; } catch(_) {}

  // Start Game / Play with the embedded player selected but not started (first start, or after a host
  // page reload mid-game): start it and wait until it's ready, including its ready handler's transfer.
  async function __ensureEmbeddedPlayerReady(timeoutMs){
    if (sdkReady && sdkDeviceId && window.__bingoSdkReadyHandled) return;
    const t0 = Date.now();
    let activated = false;
    if (!player) {
      window.__bingoSdkReadyHandled = false;
      // Not awaited: player.connect() can hang without ever resolving, and the deadline below must still apply
      startEmbeddedPlayer().catch(() => {});
    }
    await new Promise((resolve, reject) => {
      const iv = setInterval(() => {
        // Mobile Safari only plays audio from an element "activated" close to the user's click
        if (!activated && player && player.activateElement) { activated = true; try { player.activateElement(); } catch(_) {} }
        if (sdkReady && sdkDeviceId && window.__bingoSdkReadyHandled) { clearInterval(iv); resolve(); }
        else if (Date.now() - t0 > timeoutMs) {
          clearInterval(iv);
          // Drop the half-started player so the next Start Game / Play click starts a fresh one
          if (!sdkReady && player) { try { player.disconnect(); } catch(_) {} player = null; }
          reject(new Error("the embedded player didn't become ready"));
        }
      }, 150);
    });
  }

  
    // ---- Hybrid device dropdown + "Playing on" status ----
    // Default behavior: embedded SDK device when available.
    // Optional: host can select an external Spotify Connect device from their Spotify account.

    const deviceSelect = document.getElementById("deviceSelect");
    const deviceRefreshBtn = document.getElementById("deviceRefreshBtn");
    const deviceNowPlaying = document.getElementById("deviceNowPlaying");

    let __bingoChosenDeviceId = "";     // empty => embedded (default)
    let __bingoLastNowPlayingText = "";

    function setNowPlayingText(t) {
      if (!deviceNowPlaying) return;
      if (t === __bingoLastNowPlayingText) return;
      __bingoLastNowPlayingText = t;
      deviceNowPlaying.textContent = (t || "").toString().replaceAll("⏸️","").replaceAll("▶️","").replaceAll("⏯️","").replaceAll("⏵","").replaceAll("⏸","").replaceAll("▶","").replace(/\s{2,}/g," ").trim();
    }

    async function spotifyApiGet(path) {
      // Token scope fix:
      // `accessToken` is not a global var in this page. The SDK uses fetchAccessToken().
      // So this poller should call fetchAccessToken() (or fall back to /api/spotify/token).
      if (!window.__bingoAccessToken) window.__bingoAccessToken = { token: "", ts: 0 };

      async function getToken() {
        const now = Date.now();
        const ageMs = now - (window.__bingoAccessToken.ts || 0);
        if (window.__bingoAccessToken.token && ageMs < 25000) return window.__bingoAccessToken.token;

        let t = "";
        try {
          if (typeof fetchAccessToken === "function") {
            t = await fetchAccessToken();
          } else {
            const r = await fetch(`/api/spotify/token`, { credentials: "same-origin", cache: "no-store" });
            const j = await r.json().catch(()=> ({}));
            if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
            t = j.access_token || "";
          }
        } catch (e) {
          t = "";
        }

        window.__bingoAccessToken.token = t;
        window.__bingoAccessToken.ts = Date.now();
        return t;
      }

      const tok = await getToken();
      if (!tok) throw new Error("No Spotify token available (connect Spotify).");

      const r = await fetch("https://api.spotify.com/v1" + path, {
        headers: { "Authorization": "Bearer " + tok },
        cache: "no-store",
      });

      // /me/player may return 204 (no content) — handle gracefully.
      if (r.status === 204) return { __no_content: true, status: 204 };

      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        const msg = (j && (j.error && (j.error.message || j.error))) ? (j.error.message || j.error) : ("HTTP " + r.status);
        throw new Error("Spotify API error: " + msg);
      }
      j.__status = r.status;
      return j;
    }

    async function refreshDeviceList(ev) {
      if (!deviceSelect) return;
      const announce = !!(ev && ev.type === "click");   // clicked by the host (not the automatic look when the page opens)
      try {
        // keep the first option (embedded)
        const keep0 = deviceSelect.options[0];
        deviceSelect.innerHTML = "";
        deviceSelect.appendChild(keep0);

        const dj = await spotifyApiGet("/me/player/devices");
        const devs = (dj && dj.devices) ? dj.devices : [];

        // Deduplicate by id, and hide the SDK device from "external list"
        const seen = new Set();
        for (const d of devs) {
          const id = d && d.id ? String(d.id) : "";
          if (!id) continue;
          if (seen.has(id)) continue;
          seen.add(id);

          // If SDK device id is known, don't show it as "external"
          try {
            if (typeof sdkDeviceId !== "undefined" && sdkDeviceId && id === String(sdkDeviceId)) continue;
          } catch(_) {}

          const name = d.name || "Unknown device";
          // Play Alone sessions register their own web player under the same Spotify account; a hosted game must never play on one
          if (/^Music Bingo Solo\b/i.test(name)) continue;
          const type = d.type || "";
          const active = !!d.is_active;
          const opt = document.createElement("option");
          opt.value = id;
          opt.textContent = `${name}${type ? " (" + type + ")" : ""}${active ? " — active" : ""}`;
          deviceSelect.appendChild(opt);
        }

        // Re-apply selection if still present
        if (__bingoChosenDeviceId) {
          const found = Array.from(deviceSelect.options).some(o => o.value === __bingoChosenDeviceId);
          if (!found) __bingoChosenDeviceId = "";
        }
        deviceSelect.value = __bingoChosenDeviceId;
        // The picker only matters when Spotify knows another device besides the embedded player
        const row = document.getElementById("deviceRow");
        // The picker shows only while Spotify knows another device (found by Refresh devices), until a choice is made
        // and never once the game has started
        if (row) row.style.display = (deviceSelect.options.length > 1) ? "" : "none";
        if (announce) {
          const others = Array.from(deviceSelect.options).slice(1).map(o => o.textContent.replace(/ \(.*$/, ""));
          setSdkStatus(!others.length ? "No other devices found." : "Found: " + others.join(", ") + (window.__bingoGameStarted ? ". Picking one moves the music there." : ""));
        }
      } catch (e) {
        console.error(e);
        if (announce) setSdkStatus("Couldn't look for devices. Try again.");
      }
    }

    async function pollNowPlayingOnce() {
      try {
        const pj = await spotifyApiGet("/me/player");
        if (pj && pj.__no_content) {
          setNowPlayingText("Playing on: nothing yet");
          return;
        }
        const dev = pj && pj.device ? pj.device : null;
        const devName = dev && dev.name ? dev.name : "(unknown device)";
        const devId = dev && dev.id ? dev.id : "";
        const playing = (pj && typeof pj.is_playing === "boolean") ? pj.is_playing : false;

        // The embedded player is this browser tab: say so instead of showing the device name and id
        const embedded = (devId && sdkDeviceId && String(devId) === String(sdkDeviceId)) || /bingo host player/i.test(devName);
        const where = embedded ? "embedded player (this browser)" : devName;
        setNowPlayingText("Playing on: " + where + (playing ? " ▶" : " ⏸"));
      } catch (e) {
        setNowPlayingText("Playing on: (unavailable — connect Spotify)");
      }
    }

    async function applyChosenDevice() {
      __bingoChosenDeviceId = deviceSelect.value || "";
      try { __updateStartBtn(); } catch(_) {}
      try { window.__bingoChosenDeviceId = __bingoChosenDeviceId; } catch(_) {}
      // If host chooses external device, transfer immediately (play=false keeps the playback state, so a game
      // in progress carries on). Choosing the embedded player again moves it back here.
      const targetId = __bingoChosenDeviceId || ((typeof sdkDeviceId === "string" && sdkDeviceId) ? sdkDeviceId : "");
      if (targetId) {
        try {
          await postJson("/api/spotify/transfer", { device_id: targetId, play: false });
        } catch (e) {
          console.error(e);
        }
      }
      // The choice is made: the picker goes away again until Refresh devices finds something new
      try { const dr = document.getElementById("deviceRow"); if (dr) dr.style.display = "none"; } catch(_) {}
      await pollNowPlayingOnce();
    }

    // The device this game plays on (picked speaker, else this browser's player): Pause/Next are aimed at it
    function __gameDeviceQuery() {
      const id = __bingoChosenDeviceId || ((typeof sdkDeviceId === "string" && sdkDeviceId) ? sdkDeviceId : "");
      return id ? "?device_id=" + encodeURIComponent(id) : "";
    }
    window.__gameDeviceQuery = __gameDeviceQuery;

    let __hostPickedDevice = false;   // the host chose by hand: the room screen is no longer picked for them
    if (deviceSelect) {
      deviceSelect.addEventListener("change", () => { __hostPickedDevice = true; applyChosenDevice(); });
    }

    // With "play the music on the QR screen" on, pick the "Bingo Room Screen" speaker as soon as it shows up
    // (it registers when someone clicks the speaker button on the QR page)
    let __roomPickBusy = false;
    async function autoPickRoomScreen() {
      const sw = document.getElementById("roomSoundOn");
      if (!deviceSelect || !sw || !sw.checked || __hostPickedDevice || __roomPickBusy) return;
      const cur = Array.from(deviceSelect.options).find(o => o.value === __bingoChosenDeviceId);
      if (cur && /^Bingo Room Screen\b/i.test(cur.textContent)) return;   // already on it
      __roomPickBusy = true;
      const row = document.getElementById("deviceRow");
      const rowWas = row ? row.style.display : "";
      try {
        await refreshDeviceList();
        if (row) row.style.display = rowWas;   // looking quietly must not bring the picker back
        const opt = Array.from(deviceSelect.options).find(o => o.value && /^Bingo Room Screen\b/i.test(o.textContent));
        if (opt) {
          deviceSelect.value = opt.value;
          await applyChosenDevice();
          setSdkStatus("Music is now playing through the room screen.");
        }
      } catch (e) {
        console.error(e);
      } finally {
        __roomPickBusy = false;
      }
    }
    try { setInterval(autoPickRoomScreen, 4000); } catch(_) {}
    if (deviceRefreshBtn) deviceRefreshBtn.addEventListener("click", refreshDeviceList);

    /*
       Keep #deviceRefreshBtn inside .sdkBtns even if other layout code rearranges DOM.
       This is UI-only: no Spotify API calls here.
    */

      // Removed burst DOM-move fixer (__bingoFixRefreshBtnPlacement).
      // Disabled old DOM-move helpers for Spotify header buttons.
// Initial device list + status
    try { refreshDeviceList(); } catch(_) {}
    try { pollNowPlayingOnce(); } catch(_) {}
    try { setInterval(pollNowPlayingOnce, 3000); } catch(_) {}

  try { window.__bingoAllowTrackUpdates = false; } catch(_) {}

  try { __updateStartBtn(); } catch(_) {}
// ---- Game start should start the playlist on the embedded device (if present) ----
  const startBtn = document.getElementById("startBtn");
  if (startBtn) {
    startBtn.addEventListener("click", async () => {

        if (__isEnded()) { try { setMsg('Game already ended.'); } catch(_) {} return; }
      // Guard: prevent re-starting after the game is already started.
      try {
        if (window.__bingoGameStarted) { setMsg("Game already started."); return; }
      } catch(_) {}
      if (!(window.__bingoGameStarted)) { setMsg(""); }
      // Cards printed ahead: warn if songs on them have since left the Spotify playlist
      if (window.__bingoPaperCount > 0) {
        try {
          const r = await fetch(`/host/game/${CODE}/paper/missing?fresh=1`, { credentials: "same-origin" });
          const j = await r.json().catch(() => ({}));
          const m = (j && j.missing) || [];
          if (m.length) {
            const list = m.slice(0, 5).join(", ") + (m.length > 5 ? ", …" : "");
            const cards = ((j && j.affected_cards) || []).slice(0, 12).join(", ");
            const one = m.length === 1;
            if (!confirm(`${m.length} song${one ? "" : "s"} on the printed cards ${one ? "is" : "are"} no longer in the Spotify playlist (${list}). ${one ? "That square" : "Those squares"} can't be won. Cards affected: ${cards}.\n\nCancel and use "Update cards" to fix them, or start anyway?`)) return;
          }
        } catch(_) {}
      }
      try {
        // Decide target device:
// If host selected an external device from the dropdown, use it.
// Else if embedded SDK device id is present, use that.
// Else block Start Game (must pick a device first).
const chosenDeviceId = (typeof window.__bingoChosenDeviceId === "string" && window.__bingoChosenDeviceId) ? window.__bingoChosenDeviceId : "";
let targetDeviceId = chosenDeviceId || (sdkDeviceId || "");
if (!targetDeviceId) {
  // Embedded player selected (dropdown default) but not started yet: start it as part of Start Game.
  try {
    if (__startBtn) { __startBtn.disabled = true; __startBtn.classList.add("disabled"); }
    setMsg("Starting the embedded player…");
    await __ensureEmbeddedPlayerReady(15000);
    targetDeviceId = sdkDeviceId || "";
    setMsg("");
  } catch (e) {
    setMsg("Couldn't start the embedded player (" + String((e && e.message) ? e.message : e) + "). Click Start Game to try again.");
  } finally {
    try { __updateStartBtn(); } catch(_) {}
  }
  if (!targetDeviceId) return;
}

// Tell server which device this game will use.

await postJson(`/host/game/${CODE}/start`, { device_id: targetDeviceId });
        // The QR screen counts "Game starting in 3, 2, 1" (if the room reveal is on) before the first song
        if (roomRevealOn && roomRevealOn.checked) { setMsg("Game starting in 3…"); await new Promise((res) => setTimeout(res, 3000)); setMsg(""); }
        try { window.__bingoGameStarted = true; } catch(_) {}
        try { const dr = document.getElementById("deviceRow"); if (dr) dr.style.display = "none"; } catch(_) {}
        try { __updateStartBtn(); } catch(_) {}
        try { window.__showGameState("started"); } catch(_) {}

        try { window.__bingoGameStarted = true; } catch(_) {}
if (sdkDeviceId || (typeof window.__bingoChosenDeviceId === "string" && window.__bingoChosenDeviceId)) {   // the embedded player, or another device picked in the list (e.g. the room screen)
          try {
            setSdkStatus("Starting game playlist…");
            // Decide target device:
// If host selected an external device from the dropdown, use it.
// Else if embedded SDK device id is present, use that.
// Else fall back to no device_id (Spotify decides).
const chosenDeviceId = (typeof __bingoChosenDeviceId !== "undefined" && __bingoChosenDeviceId) ? __bingoChosenDeviceId : "";
const targetDeviceId = chosenDeviceId || (sdkDeviceId || "");

if (targetDeviceId) {
  // Ensure playback is on the target device first (helps avoid "plays on web player")
  try { await postJson("/api/spotify/transfer", { device_id: targetDeviceId, play: false }); } catch(_) {}
  await postJson(`/host/game/${CODE}/spotify/play?device_id=${encodeURIComponent(targetDeviceId)}`);
} else {
  await postJson(`/host/game/${CODE}/spotify/play`);
}
            try { window.__bingoEmbeddedPlaylistStarted = true;
try {
  await fetch(`/host/game/${CODE}/track_update`, { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
} catch(_) {}
 } catch(_) {}
            try { window.__bingoAllowTrackUpdates = true; } catch(_) {}
            try { await window.__bingoFlushTrackState(); } catch(_) {}
            try { window.__bingoSettleTrackState(); } catch(_) {}
            setSdkStatus("Game playlist started ✅");
          } catch (e) {
            try { window.__bingoEmbeddedPlaylistStarted = false; } catch(_) {}
            setSdkStatus("Start playlist failed: " + String((e && e.message) ? e.message : e));
          }
        } else {
          try { window.__bingoAllowTrackUpdates = false; } catch(_) {}
        }
      } catch(e) {
        setMsg(String((e && e.message) ? e.message : e));
      }
    });
  }

  // ---- Transport buttons ----
  async function requireSdk(){
    if (!player || !sdkReady) throw new Error("The embedded player isn't running. Click Play to start it.");
  }
  

  const shuffleBtn = document.getElementById("shuffleBtn");
  if (shuffleBtn) {
    shuffleBtn.addEventListener("click", async () => {
      if (!(window.__bingoGameStarted)) { setMsg(""); }
      try { await postJson(`/host/game/${CODE}/spotify/shuffle_on`); setMsg("Shuffle enabled ✅"); }
      catch(e){ setMsg(String((e && e.message) ? e.message : e)); }
    });
  }
  const playBtn = document.getElementById("playBtn");
  if (playBtn) {
    playBtn.addEventListener("click", async () => {
      // Guard: do not start Spotify playback before the game has started.
      try {
        if (!(window.__bingoGameStarted)) {
          setTransportMsg("Start the game first to play music.");
          return;
        }
      } catch(_) {}
      // Ignore extra clicks while a Play request is in flight (the server call takes ~2s, and a
      // second start used to restart the playlist at a different random song).
      if (window.__bingoPlayInFlight) return;
      window.__bingoPlayInFlight = true;
      try { playBtn.disabled = true; } catch(_) {}
      try {

      if (!(window.__bingoGameStarted)) { setMsg(""); }
        try { setTransportMsg(""); } catch(_) {}
      try {
          const usingExternal = (typeof window.__bingoChosenDeviceId === "string" && window.__bingoChosenDeviceId) ? true : false;
          if (!usingExternal && !(player && sdkReady)) {
            setMsg(""); setTransportMsg("Starting the embedded player…");
            try { await __ensureEmbeddedPlayerReady(15000); }
            catch (e) { setTransportMsg(""); throw new Error("Couldn't start the embedded player (" + String((e && e.message) ? e.message : e) + "). Click Play to try again."); }
            setTransportMsg("");
          }
        // Do NOT allow track updates until host-initiated playback is underway.
        try { window.__bingoAllowTrackUpdates = false; } catch(_) {}

        // IMPORTANT: Ensure each new game starts fresh (does not resume mid-song from a prior game/device session).
        // We do a server-side /spotify/play with position_ms=0 against the chosen device (if available),
        // then resume the SDK player as a fallback.
        try {
          const targetDeviceId = (typeof window.__bingoChosenDeviceId === "string" && window.__bingoChosenDeviceId)
            ? window.__bingoChosenDeviceId
            : (typeof sdkDeviceId === "string" ? sdkDeviceId : "");
          // Do not call /api/spotify/transfer from Play; it can interrupt playback when repeated.
          // Start Game already starts the playlist fresh (server play sets shuffle + position_ms=0).
          // Hitting Play should NOT start a new Spotify session again. Only start server play if not started yet.
          if (!(window.__bingoEmbeddedPlaylistStarted)) {
            const qp = targetDeviceId ? ("?device_id=" + encodeURIComponent(targetDeviceId)) : ("");
            await postJson(`/host/game/${CODE}/spotify/play` + qp, {});
            try { window.__bingoEmbeddedPlaylistStarted = true; } catch(_) {}
          }
        } catch (e) {
          // If server play fails, we still try to resume via SDK
        }
          if (!usingExternal) {
            try { await player.resume(); } catch(_) {}
          }
        // Enable live track updates only after host-initiated Play has occurred.
        try { window.__bingoAllowTrackUpdates = true; } catch(_) {}
        try { await window.__bingoFlushTrackState(); } catch(_) {}
        try { window.__bingoSettleTrackState(); } catch(_) {}
        setTransportMsg("Play ✅");
      } catch (e) {
        setMsg(String((e && e.message) ? e.message : e));
      }
      } finally {
        window.__bingoPlayInFlight = false;
        try { playBtn.disabled = false; } catch(_) {}
      }
    });
  }
  const pauseBtn = document.getElementById("pauseBtn");
  if (pauseBtn) {
    pauseBtn.addEventListener("click", async () => {

      if (!(window.__bingoGameStarted)) { setMsg(""); }
        try { setTransportMsg(""); } catch(_) {}
      try {
        // Prefer server-side pause (works for external devices too).
        await postJson(`/host/game/${CODE}/spotify/pause${window.__gameDeviceQuery ? window.__gameDeviceQuery() : ""}`, {});

        // Best-effort: if SDK player exists, pause it too (no-op for external devices).
        try { await requireSdk(); } catch(_) {}
        try { if (typeof player !== "undefined" && player) { await player.pause(); } } catch(_) {}

        try { window.__bingoSettleTrackState(); } catch(_) {}
        setTransportMsg("Pause ✅");
      } catch (e) {
        setMsg(String((e && e.message) ? e.message : e));
      }

    });
  }

  const nextBtn = document.getElementById("nextBtn");
  if (nextBtn) {
    
    // Option A test-only: add ?force_eop=1 to the URL to simulate end-of-playlist UI without playing through the full playlist.
    try {
      const __qs = new URLSearchParams(location.search || "");
      window.__bingoForceEOP = (__qs.get("force_eop") === "1");
      if (window.__bingoForceEOP) {
        try { setTransportMsg("End of playlist ✅ (paused) [forced]"); } catch(_) {}
        try { if (nextBtn) nextBtn.disabled = true; } catch(_) {}
      }
    } catch(_) { try { window.__bingoForceEOP = false; } catch(__) {} }

      // Next can't be spammed: after a press it is off for 2 seconds (the server call and the song change take about that long)
      let __nextCooling = false;
      nextBtn.addEventListener("click", async () => {
      if (__nextCooling || nextBtn.disabled) return;
      __nextCooling = true;
      nextBtn.disabled = true;
      setTimeout(() => {
        __nextCooling = false;
        if (!window.__bingoEnded && !window.__bingoEndOfPlaylist && !window.__bingoForceEOP) nextBtn.disabled = false;
      }, 2000);

      if (!(window.__bingoGameStarted)) { setMsg(""); }
        try { setTransportMsg(""); } catch(_) {}
      try {
        // Server-side Next controls playback for both embedded and external devices.
        const j = await postJson(`/host/game/${CODE}/spotify/next${window.__gameDeviceQuery ? window.__gameDeviceQuery() : ""}`, {});
          if (j && j.throttled) return;
          try {
            if (j && (j.end_of_playlist || j.ended)) {
              setTransportMsg("End of playlist ✅ (paused)");
              window.__bingoEndOfPlaylist = true;
              try { nextBtn.disabled = true; } catch(_) {}
              return;
            }
          } catch(_) {}

        setTransportMsg("Next ✅");
      } catch (e) {
        setMsg(String((e && e.message) ? e.message : e));
      }

    });
  }

  // ---- Host websocket updates ----
  // Reconnects with backoff (server restarts, Wi-Fi blips, proxies closing idle sockets) and refreshes
  // the lists after a reconnect so claims/players that arrived during the gap still show up.
  // A keep-alive ping every 30s stops Cloudflare closing the socket after ~100s of silence.
  let __hostWsRetry = 0;
  let __hostWsEverOpened = false;
  function __connectHostWS(){
  try {
    const hostWS = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/host/game/" + CODE);
    let pingTimer = null;
    hostWS.onopen = () => {
      if (__hostWsEverOpened) {
        try { __scheduleRefresh("all"); } catch(_) {}  // any other value refreshes claims, played and players together
      }
      __hostWsEverOpened = true;
      __hostWsRetry = 0;
      pingTimer = setInterval(() => { try { if (hostWS.readyState === 1) hostWS.send("ping"); } catch(_) {} }, 30000);
    };
    hostWS.onclose = () => {
      try { clearInterval(pingTimer); } catch(_) {}
      const delay = Math.min(15000, 1000 * Math.pow(2, __hostWsRetry++));
      setTimeout(__connectHostWS, delay);
    };
    hostWS.onmessage = (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data); } catch(_) { return; }

      if (data && data.type === "pattern") { try { window.PatternBadge.update(data); } catch(_) {} return; }



      // Server signals end-of-playlist (we pause to prevent Spotify drifting into recommendations).
      if (data && data.type === "end_of_playlist") {
        try { setTransportMsg("End of playlist ✅ (paused)"); } catch(_) {}
        try {
          const nb = document.getElementById('nextBtn');
          if (nb) nb.disabled = true;
        } catch(_) {}
        return;
      }
      // track updates
      if (data.type === "track") {
        // (was a bare identifier: threw ReferenceError on every track message)
          const tRaw = data.title || "";
          const t = __bingoCleanTitle(tRaw);
        const a = data.artist || "";
        const tEl = document.getElementById("hostNpTitle");
        const aEl = document.getElementById("hostNpArtist");
        if (tEl) tEl.textContent = t;
        if (aEl) aEl.textContent = a;
        // Music playing somewhere other than this page's own player (e.g. the room screen): keep the timer in step too
        try {
          if (typeof data.position_ms === "number") {
            const age = data.paused ? 0 : Math.max(0, Date.now() - (Number(data.server_ts_ms) || Date.now()));
            __npPosMs = data.position_ms + Math.min(age, 5000);
            __npPaused = !!data.paused;
            __renderNpTimer();
            if (__npPaused) __stopNpTicker(); else __startNpTicker();
          }
        } catch(_) {}
        // If server says this track was a duplicate for the game, do NOT append it to the Played list.

        // (We still update Now Playing text/counters.)

        if (!(data && data.duplicate_ignored)) {

          addPlayedTrack(t, a, (data && (data.track_id || data.id)) ? (data.track_id || data.id) : "");

        }

        __updateCounters();
return;
      }


      const t = String((data && data.type) || "").toLowerCase();
      if (t.indexOf("player") !== -1) { __scheduleRefresh("players"); return; }
      if (t.indexOf("played")  !== -1) { __scheduleRefresh("played");  return; }
      if (t.indexOf("claim")   !== -1) { __scheduleRefresh("claims");  return; }
    };
  } catch(_) {
    setTimeout(__connectHostWS, 5000);
  }
  }
  __connectHostWS();

  // initial counters
  __updateCounters();
})();
