/* Phone player's bingo card: dabbing, claims, live updates from the host, hints. Needs window.BINGO_PLAYER = {code, number, status, hintMode} (set in player_card.html). */
try { document.body.classList.add('playerPage'); } catch(_) {}

/*
   Fixes:
   - Restore square dab/undab (localStorage persisted)
   - Auto-reveal card on WS "admitted" (no manual refresh)
   - Handle server messages: type="overlay" overlay="bingo_accepted", and type="claim_status"
   - Keep overlay lock behavior (blocks taps only while overlay shown)
*/

(function(){
  const CODE = window.BINGO_PLAYER.code;
  const PLAYERNO = String(window.BINGO_PLAYER.number);

  const waitingMsg = document.getElementById("waitingMsg");
  const cardPanel  = document.getElementById("cardPanel");
  const cardGrid   = document.getElementById("cardGrid");

  const bingoBtn = document.getElementById("bingoBtn");
  const claimMsg = document.getElementById("claimMsg");
  const rejectionMsg = document.getElementById("rejectionMsg");

  
  /*
   Reveal now-playing on the player card only after the current track reaches 10 seconds.

   Fixes:
   - Clear now-playing immediately when a *different* track starts (pos < 10s), so the old song doesn't linger.
   - Persist last-revealed now-playing in localStorage, so page refresh does NOT blank it.
   - Refresh-safe during the pre-10s window: if a refresh happens while the next song is still <10s,
     we clear the old saved song as soon as we see the new track_id, then reveal at 10s.
   Source of truth: WS messages broadcast by the server: {"type":"track","title","artist","track_id","position_ms","paused"}.
*/
  const npTitleEl  = document.getElementById("npTitle");
  const npArtistEl = document.getElementById("npArtist");

  const NP_KEY = `bingo_now_playing_${CODE}_${PLAYERNO}`; // JSON: {trackId,title,artist}
  let __shownTrackId = "";        // trackId currently shown in the UI (persisted)
  let __pendingTrack = null;      // {trackId,title,artist}
  let __revealTimer  = null;

  function __setNowPlaying(title, artist){
    try { if (npTitleEl)  npTitleEl.textContent  = String(title  || ""); } catch(e){}
    try { if (npArtistEl) npArtistEl.textContent = String(artist || ""); } catch(e){}
  }
  function __clearRevealTimer(){
    try { if (__revealTimer) { clearTimeout(__revealTimer); } } catch(e){}
    __revealTimer = null;
  }

  // Visual countdown over the now-playing box while a new song is hidden. Display only:
  // the reveal itself is still driven by __revealTimer below.
  const REVEAL_MS = 10000;
  const npcEl = document.getElementById("npCountdown");
  const npcNum = document.getElementById("npcNum");
  const npcLabel = document.getElementById("npcLabel");
  const npcSub = document.getElementById("npcSub");
  const npcFill = document.getElementById("npcFill");
  const npcSr = document.getElementById("npcSr");
  let __cdTick = null;

  function __stopCountdown(){
    try { if (__cdTick) clearInterval(__cdTick); } catch(e){}
    __cdTick = null;
    try { if (npcEl) { npcEl.hidden = true; npcEl.classList.remove("isPaused"); } } catch(e){}
  }
  function __setFill(fraction, durationMs){
    if (!npcFill) return;
    npcFill.style.transition = "none";
    npcFill.style.width = (Math.max(0, Math.min(1, fraction)) * 100) + "%";
    if (durationMs > 0) {
      void npcFill.offsetWidth;  // commit the start width before animating
      npcFill.style.transition = `width ${durationMs}ms linear`;
      npcFill.style.width = "100%";
    }
  }
  function __startCountdown(remainingMs){
    if (!npcEl) return;
    const end = Date.now() + remainingMs;
    const wasHidden = npcEl.hidden;
    npcEl.classList.remove("isPaused");
    npcLabel.textContent = "Song revealed in";
    npcSub.textContent = "Guess it by ear";
    npcEl.hidden = false;
    __setFill(1 - remainingMs / REVEAL_MS, remainingMs);
    const tick = () => {
      const left = Math.max(0, end - Date.now());
      npcNum.textContent = String(Math.ceil(left / 1000));
      if (left <= 0) { try { clearInterval(__cdTick); } catch(e){} __cdTick = null; }
    };
    try { if (__cdTick) clearInterval(__cdTick); } catch(e){}
    tick();
    __cdTick = setInterval(tick, 200);
    if (wasHidden && npcSr) npcSr.textContent = `New song playing. Title shows in ${Math.ceil(remainingMs / 1000)} seconds.`;
  }
  function __pauseCountdown(remainingMs){
    if (!npcEl) return;
    try { if (__cdTick) clearInterval(__cdTick); } catch(e){}
    __cdTick = null;
    npcEl.classList.add("isPaused");
    npcLabel.textContent = "Paused";
    npcNum.textContent = "";
    npcSub.textContent = "Resumes with the music";
    npcEl.hidden = false;
    __setFill(1 - remainingMs / REVEAL_MS, 0);
    if (npcSr) npcSr.textContent = "Song paused.";
  }
  function __saveNP(trackId, title, artist){
    try {
      const obj = { trackId: String(trackId||""), title: String(title||""), artist: String(artist||"") };
      if (!obj.trackId && !obj.title && !obj.artist) localStorage.removeItem(NP_KEY);
      else localStorage.setItem(NP_KEY, JSON.stringify(obj));
    } catch(e){}
  }
  function __loadNP(){
    try {
      const raw = localStorage.getItem(NP_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);

      const which = String((obj && obj.type) || "");
      if (which === "game_state") {
        const sv = (obj && typeof obj.continue_seq !== "undefined") ? obj.continue_seq : 0;
        clearAcceptedIfSeqAdvanced(sv);
      }
      if (which === "continue") {
        const sv = (obj && typeof obj.continue_seq !== "undefined") ? obj.continue_seq : (getContinueSeq() + 1);
        setContinueSeq(sv);
        setClaimState("");
        setClaimId("");
        setClaimUI("");
        hideOverlay();
        return;
      }

      if (!obj || typeof obj !== "object") return null;
      const trackId = (obj.trackId !== undefined && obj.trackId !== null) ? String(obj.trackId) : "";
      const title   = (obj.title   !== undefined && obj.title   !== null) ? String(obj.title)   : "";
      const artist  = (obj.artist  !== undefined && obj.artist  !== null) ? String(obj.artist)  : "";
      if (!trackId && !title && !artist) return null;
      return { trackId, title, artist };
    } catch(e){
      return null;
    }
  }

  // On page load: restore last revealed now-playing (do NOT clear on refresh).
  try {
    const saved = __loadNP();
    if (saved) {
      __shownTrackId = saved.trackId || "";
      __setNowPlaying(saved.title, saved.artist);
    }
  } catch(e){}

  

  // Immediately fetch last known track state so an F5 during the pre-10s window still reveals at ~10s
  // (even if the server only posts /track_update every ~30s).
  try {
    fetch(`/game/${CODE}/last_track_state`, { credentials: 'same-origin', cache: 'no-store' })
      .then(r => r.json().catch(()=>null))
      .then(j => {
        // Endpoint returns the cached WS 'track' message ({} if none); it has no 'ok' field.
        if (!j || j.type !== "track") return;
        try { __handleTrackMsg(j); } catch(e){}
      })
      .catch(()=>{});
  } catch(e){}
  // ---- Bingo hints: the host turns them on for everyone or lets each player choose ----
  let __hintMode = window.BINGO_PLAYER.hintMode;
  let __hintLast = null;
  const __hintChk = document.getElementById("hintChk"), __hintWrap = document.getElementById("hintToggleWrap");
  const __HINT_KEY = `bingo_hint_${CODE}`;
  function __hintOn(){ return __hintMode === "all" || (__hintMode === "optin" && !!(__hintChk && __hintChk.checked)); }
  function __applyHint(){
    try {
      if (!window.BingoHint) return;
      if (__hintOn() && __hintLast) window.BingoHint.show(cardGrid, __hintLast.title, CODE + ":" + PLAYERNO + ":" + __hintLast.trackId);
      else window.BingoHint.clear(cardGrid);
    } catch(e){}
  }
  function __syncHintUI(){ try { if (__hintWrap) __hintWrap.hidden = (__hintMode !== "optin"); } catch(e){} }
  try { if (__hintChk) __hintChk.checked = localStorage.getItem(__HINT_KEY) === "1"; } catch(e){}
  if (__hintChk) __hintChk.addEventListener("change", () => {
    try { localStorage.setItem(__HINT_KEY, __hintChk.checked ? "1" : "0"); } catch(e){}
    __applyHint();
  });
  __syncHintUI();

function __handleTrackMsg(data){
    const title  = (data && typeof data.title  === "string") ? data.title  : "";
    const artist = (data && typeof data.artist === "string") ? data.artist : "";
    const trackId = (data && (data.track_id || data.id)) ? String(data.track_id || data.id) : "";
    let posMs = (data && typeof data.position_ms === "number") ? data.position_ms : 0;
    const paused = !!(data && data.paused);
    // Cached messages (sent on page load/refresh) carry the position from when they were sent;
    // add the time since then so a refresh doesn't restart the 10s reveal wait.
    if (!paused && data && typeof data.server_ts_ms === "number") {
      const age = Date.now() - data.server_ts_ms;
      if (age > 0 && age < 15 * 60 * 1000) posMs += age;
    }

    if (!trackId) return;
    // The hint lights as soon as the song starts, without waiting for the title to be revealed
    if (!__hintLast || __hintLast.trackId !== trackId) { __hintLast = { title, trackId }; __applyHint(); }

    // If a *different* track starts and we're in the pre-10s window:
    // clear immediately AND clear persisted shown track so refresh won't get stuck showing the old song.
    if (__shownTrackId && trackId !== __shownTrackId && posMs < 10000) {
      __setNowPlaying("", "");
      __saveNP("", "", "");
      __shownTrackId = "";
    }

    // Track pending state for reveal.
    if (!__pendingTrack || __pendingTrack.trackId !== trackId) {
      __pendingTrack = { trackId, title, artist };
      __clearRevealTimer();
    } else {
      // Keep freshest strings if server re-sends them
      __pendingTrack.title = title || __pendingTrack.title || "";
      __pendingTrack.artist = artist || __pendingTrack.artist || "";
    }

    // If already >= 10s, show immediately and persist.
    if (posMs >= 10000) {
      __setNowPlaying(__pendingTrack.title, __pendingTrack.artist);
      __saveNP(trackId, __pendingTrack.title, __pendingTrack.artist);
      __shownTrackId = trackId;
      __pendingTrack = null;
      __clearRevealTimer();
      __stopCountdown();
      return;
    }

    // Otherwise schedule reveal (only while playing).
    __clearRevealTimer();
    const showCountdown = (trackId !== __shownTrackId);
    if (!paused) {
      const delay = Math.max(0, 10000 - posMs);
      if (showCountdown) { try { __startCountdown(delay); } catch(e){} }
      __revealTimer = setTimeout(() => {
        try {
          if (__pendingTrack && __pendingTrack.trackId === trackId) {
            __setNowPlaying(__pendingTrack.title, __pendingTrack.artist);
            __saveNP(trackId, __pendingTrack.title, __pendingTrack.artist);
            __shownTrackId = trackId;
            __pendingTrack = null;
          }
        } catch(e){}
        try { __stopCountdown(); } catch(e){}
      }, delay + 50);
    } else if (showCountdown) {
      try { __pauseCountdown(Math.max(0, 10000 - posMs)); } catch(e){}
    }
  }


  try { window.__bingoHandleTrackMsg = __handleTrackMsg; } catch(e){}   // lets the tests feed the page track messages

  // ---- Dab persistence (client-side) ----

  const DAB_KEY = `bingo_dabs_${CODE}_${PLAYERNO}`; // JSON array of pos strings

  function _loadDabs(){
    try {
      const raw = localStorage.getItem(DAB_KEY);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return new Set();
      return new Set(arr.map(x => String(x)));
    } catch(e){
      return new Set();
    }
  }
  function _saveDabs(setObj){
    try {
      const arr = Array.from(setObj.values());
      localStorage.setItem(DAB_KEY, JSON.stringify(arr));
    } catch(e){}
  }
  function _applyDabs(){
    if (!cardGrid) return;
    const dabs = _loadDabs();
    const btns = cardGrid.querySelectorAll("button.sq");
    btns.forEach(btn => {
      const pos = String(btn.getAttribute("data-pos") || "");
      const isFree = btn.getAttribute("data-free") === "true";
      if (isFree) {
        btn.classList.add("marked");
        btn.setAttribute("aria-pressed", "true");
        return;
      }
      if (dabs.has(pos)) {
        btn.classList.add("marked");
        btn.setAttribute("aria-pressed", "true");
      } else {
        btn.classList.remove("marked");
        btn.setAttribute("aria-pressed", "false");
      }
    });
  }
  function _toggleDab(btn){
    const isFree = btn.getAttribute("data-free") === "true";
    if (isFree) return;
    const pos = String(btn.getAttribute("data-pos") || "");
    if (!pos) return;
    const dabs = _loadDabs();
    if (dabs.has(pos)) dabs.delete(pos);
    else dabs.add(pos);
    _saveDabs(dabs);
    _applyDabs();
  }

  // Attach dab handler (event delegation)
  if (cardGrid) {
    cardGrid.addEventListener("click", (ev) => {
      try {
        if (document.body && document.body.classList.contains("overlayActive")) return;
      } catch(e){}
      const btn = ev.target && ev.target.closest ? ev.target.closest("button.sq") : null;
      if (!btn) return;
      _toggleDab(btn);
    });
  }

  // ---- Claim state (localStorage) ----
  const CLAIM_KEY = `bingo_claim_state_${CODE}_${PLAYERNO}`; // "pending" | "accepted" | ""
  const CLAIM_ID_KEY = `bingo_claim_id_${CODE}_${PLAYERNO}`;

  const CONTINUE_SEQ_KEY = `bingo_continue_seq_${CODE}_${PLAYERNO}`;
  function getContinueSeq(){ try { return parseInt(localStorage.getItem(CONTINUE_SEQ_KEY) || "0", 10) || 0; } catch(e){ return 0; } }
  function setContinueSeq(v){ try { localStorage.setItem(CONTINUE_SEQ_KEY, String(parseInt(String(v||0),10)||0)); } catch(e){} }
  function clearAcceptedIfSeqAdvanced(serverSeq){
    try {
      const st = getClaimState();
      const localSeq = getContinueSeq();
      const sv = parseInt(String(serverSeq||0),10) || 0;
      if (st === "accepted" && sv > localSeq) {
        setContinueSeq(sv);
        setClaimState("");
        setClaimId("");
        setClaimUI("");
        hideOverlay();
      }
    } catch(e){}
  }
  function getClaimState(){ try { return String(localStorage.getItem(CLAIM_KEY) || ""); } catch(e){ return ""; } }
  function setClaimState(v){ try { if (!v) localStorage.removeItem(CLAIM_KEY); else localStorage.setItem(CLAIM_KEY, String(v)); } catch(e){} }
  function setClaimId(v){ try { if (!v) localStorage.removeItem(CLAIM_ID_KEY); else localStorage.setItem(CLAIM_ID_KEY, String(v)); } catch(e){} }
  function getClaimId(){ try { return String(localStorage.getItem(CLAIM_ID_KEY) || ""); } catch(e){ return ""; } }

  // ---- Overlay helpers ----
  const overlayRoot = document.getElementById("bingoOverlay");
  const overlayTitle = document.getElementById("bingoOverlayTitle");
  const overlaySub = document.getElementById("bingoOverlaySub");

  function setOverlayLock(active){
    try { document.body.classList.toggle("overlayActive", !!active); } catch(e){}
  }
  function showOverlay(title, sub){
    if (!overlayRoot) return;
    try { overlayTitle.textContent = title || ""; } catch(e){}
    try { overlaySub.textContent = sub || ""; } catch(e){}
    overlayRoot.classList.remove("hidden");
    overlayRoot.setAttribute("aria-hidden", "false");
    setOverlayLock(true);
  }
  function hideOverlay(){
    if (!overlayRoot) return;
    try { __fireworks.stop(); } catch(e){}
    try { overlayRoot.classList.remove("winnerMode"); } catch(e){}
    overlayRoot.classList.add("hidden");
    overlayRoot.setAttribute("aria-hidden", "true");
    setOverlayLock(false);
  }

  // Winner fireworks (static/fireworks.js); stopped by hideOverlay()
  const __fireworks = window.createBingoFireworks(document.getElementById("fireworksCanvas"));
  window.__bingoFireworks = __fireworks;  // handy for testing from the console

  function setClaimUI(state){
    if (!bingoBtn) return;
    if (state === "pending"){
      bingoBtn.disabled = true;
      bingoBtn.classList.add("disabled");
      if (claimMsg) claimMsg.textContent = "Bingo submitted — awaiting host verification";
    } else if (state === "accepted"){
      bingoBtn.disabled = true;
      bingoBtn.classList.add("disabled");
      if (claimMsg) claimMsg.textContent = "Bingo accepted.";
    } else {
      bingoBtn.disabled = false;
      bingoBtn.classList.remove("disabled");
      if (claimMsg) claimMsg.textContent = "";
    }
  }

  // Init UI from localStorage + apply dabs
  try { setClaimUI(getClaimState()); } catch(e){}
  try { _applyDabs(); } catch(e){}

  // ---- Admit reveal (host -> player) ----
  function onAdmitted(){
    try { if (waitingMsg) waitingMsg.style.display = "none"; } catch(e){}
    try { if (cardPanel) cardPanel.style.display = ""; } catch(e){}
    try { _applyDabs(); } catch(e){}
  }
  // show the "not accepted" message for a moment
  function flashRejection(){
    if (!rejectionMsg) return;
    rejectionMsg.style.display = "";
    setTimeout(() => { rejectionMsg.style.display = "none"; }, 2500);
  }

  // ---- BINGO click ----
    // ---- BINGO click (v5: stable + mirrors solo marked payload) ----
  function __collectMarked(){
    const marked = [];
    try {
      document.querySelectorAll("#cardGrid .sq.marked").forEach((el) => {
        const pos = parseInt(el.getAttribute("data-pos") || "", 10);
        if (!Number.isNaN(pos) && pos >= 0 && pos <= 24) marked.push(pos);
      });
    } catch(e) {}
    return marked;
  }

  async function __postClaim(marked){
    return await fetch(`/player/${encodeURIComponent(CODE)}/${encodeURIComponent(PLAYERNO)}/claim_bingo`, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ marked: marked || [] }),
      credentials: "same-origin",
      cache: "no-store"
    });
  }

  if (bingoBtn){
    bingoBtn.addEventListener("click", async function(){
      if (bingoBtn.disabled) return;

      // Clear any old rejection flash
      try { if (rejectionMsg) rejectionMsg.style.display = "none"; } catch(e){}

      // Optimistic pending immediately (prevents double clicks)
      try { setClaimUI("pending"); } catch(e){}
      try { setClaimState("pending"); } catch(e){}
      try { setClaimId(""); } catch(e){}

      try {
        const marked = __collectMarked();
        const resp = await __postClaim(marked);
        const j = await resp.json().catch(() => ({}));

        // Always store claim_id if present
        try {
          if (j && j.claim_id !== undefined && j.claim_id !== null) setClaimId(String(j.claim_id));
        } catch(e){}

        if (!resp.ok){
          // Request failed -> clear optimistic pending
          try { setClaimState(""); } catch(e){}
          try { setClaimUI(""); } catch(e){}
          try {
            if (claimMsg) claimMsg.textContent = `Claim failed (${resp.status}): ${
              (j && (j.error || j.detail || j.message)) ? (j.error || j.detail || j.message) : "error"
            }`;
          } catch(e){}
          return;
        }

        const st = String((j && j.status) || "").toLowerCase();

        if (st === "pending"){
          try { setClaimState("pending"); } catch(e){}
          try { setClaimUI("pending"); } catch(e){}
          try { if (claimMsg) claimMsg.textContent = (j && j.message) ? String(j.message) : "Bingo submitted — awaiting host verification"; } catch(e){}
          return;
        }

        if (st === "accepted"){
          try { setClaimState("accepted"); } catch(e){}
          try { setClaimUI("accepted"); } catch(e){}
          try { if (claimMsg) claimMsg.textContent = (j && j.message) ? String(j.message) : "Bingo accepted."; } catch(e){}
          return;
        }

        if (st === "rejected"){
          try { setClaimState(""); } catch(e){}
          try { setClaimUI(""); } catch(e){}
          flashRejection();
          return;
        }

        // Fallback: if server doesn't send status for some reason, use auto_valid
        const ok = !!(j && j.auto_valid);
        if (ok){
          try { setClaimState("pending"); } catch(e){}
          try { setClaimUI("pending"); } catch(e){}
          try { if (claimMsg) claimMsg.textContent = (j && j.message) ? String(j.message) : "Bingo submitted — awaiting host verification"; } catch(e){}
        } else {
          try { setClaimState(""); } catch(e){}
          try { setClaimUI(""); } catch(e){}
          flashRejection();
        }

      } catch(e){
        // Network/parse error -> clear optimistic pending and show message
        try { setClaimState(""); } catch(e2){}
        try { setClaimUI(""); } catch(e2){}
        try { if (claimMsg) claimMsg.textContent = "Claim failed: " + (e && e.message ? e.message : e); } catch(e2){}
      }
    });
  }

  // Rebuilt WS connect + onmessage handler (fixes missing ws/which/data + stray brace/semicolon syntax errors)
  function connectWS(){
    const proto = (location && location.protocol === "https:") ? "wss" : "ws";
    const wsUrl = `${proto}://${location.host}/ws/game/${CODE}`;


    function showGameOverOverlay(){
      const el = document.getElementById("gameOverOverlay");
      if (!el) return;
      try { el.classList.remove("hidden"); } catch(e){}
      try { el.setAttribute("aria-hidden", "false"); } catch(e){}
      try { document.body.classList.add("overlayActive"); } catch(e){}
    }
    try {
      const el = document.getElementById("gameOverOverlay");
      if (el) el.addEventListener("click", function(){ window.location.href = "/"; });
    } catch(e){}
    try {
      const st = String(window.BINGO_PLAYER.status || "").toLowerCase();
      if (st === "ended") showGameOverOverlay();
    } catch(e){}

    let ws;
    try {
      ws = new WebSocket(wsUrl);
    } catch(e) {
      try { console.warn("WS create failed", e); } catch(_e){}
      return;
    }

    ws.onmessage = function(evt){
      let data;
      try {
        data = JSON.parse(evt.data);
      } catch(e) {
        return;
      }

      const which = String((data && data.type) || "");
      if (which === "claims_updated" || which === "overlay" || which === "continue" || which === "end_game") {
        try { window.refreshWinners && window.refreshWinners(); } catch(e){}
      }


        if (which === "end_game") {
          try { showGameOverOverlay(); } catch(e){}
          return;
        }

      // Clear accepted state when host continues to next round.
      if (which === "game_state") {
        const sv = (data && typeof data.continue_seq !== "undefined") ? data.continue_seq : 0;
        try { clearAcceptedIfSeqAdvanced(sv); } catch(e){}
      }
      if (which === "continue") {
        const sv = (data && typeof data.continue_seq !== "undefined") ? data.continue_seq : (function(){
          try { return (getContinueSeq() + 1); } catch(e){ return 1; }
        })();
        try { setContinueSeq(sv); } catch(e){}
        try { setClaimState(""); } catch(e){}
        try { setClaimId(""); } catch(e){}
        try { setClaimUI(""); } catch(e){}
        try { hideOverlay(); } catch(e){}
        return;
      }

      if (which === "track") {
        try { __handleTrackMsg(data); } catch(e){}
        return;
      }

      if (which === "pattern") {
        try { window.PatternBadge.update(data); } catch(e){}
        return;
      }

      if (which === "hint_mode") {
        __hintMode = String((data && data.mode) || "off");
        __syncHintUI();
        __applyHint();
        return;
      }

      // The host removed this player from the game
      if (which === "removed") {
        if (String(data.number) === String(window.BINGO_PLAYER.number)) {
          try { ws.close(); } catch(e){}
          const box = document.createElement("div");
          box.className = "panel removedNotice";
          const h = document.createElement("h2"); h.textContent = "You were removed from this game";
          const p = document.createElement("p"); p.className = "muted"; p.textContent = "The host took you out of the game. You can join again, for example with a different name.";
          const a = document.createElement("a"); a.className = "btn btnPrimary"; a.href = "/game/" + encodeURIComponent(CODE); a.textContent = "Join again";
          box.append(h, p, a);
          const c = document.querySelector(".container");
          if (c) { c.textContent = ""; c.appendChild(box); }
        }
        return;
      }

      // The host started a new session of this game (Play again): this player was cleared, so join again
      if (which === "game_reset") {
        try { location.href = "/game/" + encodeURIComponent(CODE); } catch(e){}
        return;
      }

      if (which === "admitted"){
        try { onAdmitted(); } catch(e){}
        return;
      }

      // Server sends: {"type":"overlay","overlay":"bingo_accepted", "winner_name":..., "winner_playerno":...}
      if (which === "overlay"){
        const overlay = String((data && data.overlay) || "").toLowerCase();

          if (overlay === "game_over") {
            try { showGameOverOverlay(); } catch(e){}
            return;
          }

        if (overlay === "clear") {
          try { hideOverlay(); } catch(e){}
          try { setClaimState(""); } catch(e){}
          try { setClaimId(""); } catch(e){}
          try { setClaimUI(""); } catch(e){}
          return;
        }

        if (overlay === "bingo_accepted"){
          const winnerNo = (data && data.winner_playerno !== undefined && data.winner_playerno !== null) ? String(data.winner_playerno) : "";
          const winnerName = String((data && data.winner_name) || "A player");

          // If it's me, mark accepted; otherwise show notification overlay.
          if (winnerNo && String(PLAYERNO) === winnerNo) {
            try { setClaimState("accepted"); } catch(e){}
            try { setClaimUI("accepted"); } catch(e){}
            try { showOverlay("WINNER!", "Bingo accepted by the host."); } catch(e){}
            try { overlayRoot.classList.add("winnerMode"); __fireworks.start(10000); } catch(e){}
          } else {
            try { showOverlay(`${winnerName} got BINGO!`); } catch(e){}
          }
        }
        return;
      }

      // Server sends: {"type":"claim_status","status":"rejected|accepted|pending","claim_id":...}
      if (which === "claim_status"){
        const st = String((data && data.status) || "").toLowerCase();
        if (st === "rejected"){
          const incoming = (data && data.claim_id !== undefined && data.claim_id !== null) ? String(data.claim_id) : "";
          let mine = "";
          try { mine = getClaimId(); } catch(e){}
          if (!incoming || !mine || incoming === mine) {
            try { setClaimState(""); } catch(e){}
            try { setClaimId(""); } catch(e){}
            try { setClaimUI(""); } catch(e){}
            try { hideOverlay(); } catch(e){}
            flashRejection();
          }
        } else if (st === "accepted"){
          try { setClaimState("accepted"); } catch(e){}
          try { setClaimUI("accepted"); } catch(e){}
        } else if (st === "pending"){
          try { setClaimState("pending"); } catch(e){}
          try { setClaimUI("pending"); } catch(e){}
        }
        return;
      }

      // If a new round/reset/continue message is introduced later, clear claim state safely.
      if (which.indexOf("continue") !== -1 || which.indexOf("reset") !== -1 || which.indexOf("next") !== -1 || which.indexOf("round") !== -1) {
        try { setClaimState(""); } catch(e){}
        try { setClaimId(""); } catch(e){}
        try { setClaimUI(""); } catch(e){}
        try { hideOverlay(); } catch(e){}
        return;
      }
    };

    // Keep-alive: Cloudflare closes websockets after ~100s without traffic (e.g. while the host is paused).
    let __pingTimer = null;
    ws.onopen = function(){
      __pingTimer = setInterval(function(){ try { if (ws.readyState === 1) ws.send("ping"); } catch(e){} }, 30000);
    };
    ws.onclose = function(){ try { clearInterval(__pingTimer); } catch(e){} setTimeout(connectWS, 1200); };
  }

  connectWS();

  // Ensure overlay lock is correct on first load
  try { if (overlayRoot && !overlayRoot.classList.contains("hidden")) setOverlayLock(true); } catch(e){}

  // If server rendered as already admitted, make sure dabs are active.
  try { if (!waitingMsg) onAdmitted(); } catch(e){}

})();
