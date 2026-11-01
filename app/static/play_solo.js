/* Play Alone: Spotify player, card dabbing, bingo calls, played tracks. Needs window.BINGO_SOLO (set in play_solo.html). */
(() => {
  const code = window.BINGO_SOLO.code;
  const playerno = window.BINGO_SOLO.playerno;

    // legacy fallbacks some blocks used historically
    try { window.code = String(code||''); } catch(_) {}
    try { window.playerno = String(playerno||''); } catch(_) {}

    const GAME_ENDED = window.BINGO_SOLO.gameEnded;

  const PLAYER_NAME = window.BINGO_SOLO.playerName;

    const GAME_STATUS = window.BINGO_SOLO.gameStatus;
/* SOLO_SEPARATION_GUARD_V1 */

  const grid = document.getElementById("soloCardGrid");
  const urlToggle = `/play/solo/${code}/${playerno}/toggle`;

    // SOLO pages must NOT rely on a global window.__spotifyAccessToken.
    // Always obtain a fresh token from the server (host session) and retry on 401.
    let __soloToken = (typeof token !== "undefined" && token) ? String(token) : "";
    async function __soloEnsureToken(force=false){
      try{
        if (!force && __soloToken) return __soloToken;
        const r = await fetch("/api/spotify/token", { credentials: "same-origin", cache: "no-store" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !j || !j.access_token) throw new Error((j && j.error) ? j.error : ("token_http_" + r.status));
        __soloToken = String(j.access_token || "");
          try { token = __soloToken; } catch(_) {}  // keep legacy token in sync
        return __soloToken;
      } catch(e){
        // Leave token as-is; callers can surface the error
        throw e;
      }
    }
  const statusEl = document.getElementById("playStatus");
  const bingoEl  = document.getElementById("bingoResult");

  function __soloClearBingoMsg(ev){
    try {
      // Not on the Bingo click itself, or the result would be wiped as soon as it's shown
      if (ev && ev.target && ev.target.closest && ev.target.closest("#btnBingo")) return;
      const el = document.getElementById("bingoResult");
      if (el && el.textContent && el.textContent.trim()) el.textContent = "";
    } catch(_) {}
  }
  // Clear on any user interaction (click/tap/keyboard) so stale messages don't linger
  try {
    const root = document.getElementById("soloRoot") || document.body;
    ["pointerdown","click","touchstart","keydown"].forEach(evt => {
      root.addEventListener(evt, __soloClearBingoMsg, {passive:true});
    });
  } catch(_) {}
const btnPlay  = document.getElementById("btnPlay");
  const btnPause = document.getElementById("btnPause");
  const btnNext  = document.getElementById("btnNext");
  const btnBingo = document.getElementById("btnBingo");
  const gameOverEl = document.getElementById("soloGameOver");

      function __soloShowEndedHeader(){
        try{
          const n = document.getElementById("soloHeaderNormal");
          const e = document.getElementById("soloHeaderEnded");
          if (n) n.style.display = "none";
          if (e) e.style.display = "block";
        }catch(_){ }
      }
const overlayRoot = document.getElementById("bingoOverlay");

  try { if (overlayRoot) overlayRoot.style.pointerEvents = "none"; } catch(_){ }
const overlayTitle = document.getElementById("bingoOverlayTitle");
  const overlaySub = document.getElementById("bingoOverlaySub");

  var token = window.BINGO_SOLO.token;
  var playlistId = window.BINGO_SOLO.playlistId;
  var EXPECTED_CONTEXT_URI = ("spotify:playlist:" + String(playlistId || "").trim());

  try { window.token = token; } catch(_) {}
  try { window.playlistId = playlistId; } catch(_) {}
  try { window.EXPECTED_CONTEXT_URI = EXPECTED_CONTEXT_URI; } catch(_) {}
  try { window.__soloToken = token; } catch(_) {}

  // Prevent the previous game's last track from being added to THIS game's Played Tracks.
  // Only allow addPlayed() once we have switched/confirmed playback on EXPECTED_CONTEXT_URI.
  let __soloAllowTrackAdds = false;
    // Track URI playing BEFORE we start THIS game (late SDK events can report it).
    // We'll block it from being added to Played Tracks for this new game.
    let __soloBlockedTrackUri = null;
    try { window.__soloBlockedTrackUri = __soloBlockedTrackUri; } catch(_) {}

  try { window.__soloAllowTrackAdds = __soloAllowTrackAdds; } catch(_) {}

    /*
       Purpose:
         - Keep bingo UI text shorter/cleaner by removing common suffixes:
           "- Remastered", "- Remastered 2011", "- Edit", "- Version", "- Live", "- Mix", "- Radio Edit", etc.
         - Provide a stable normalization key for de-duping across versions.
       Scope: SOLO ONLY (play_solo.html)
    */
    function __soloCleanTitleForDisplay(title){
      try{
        let t = String(title || "").normalize("NFKC");
        t = t.replace(/[\u200B-\u200D\uFEFF]/g, "");
        t = t.replace(/[‐-‒–—−]/g, "-");
        t = t.replace(/\s+/g, " ").trim();

        // Version tags off, same rules as clean_song_title() in app/util.py (squares + hosted display):
        // a trailing " - ..." part or (...)/[...] part containing a version word. "Clear - Original 1983 Mix",
        // "Pump Up The Volume (UK 12" Remix)", "Smooth Criminal - Re-Recorded"; keeps "My Own Summer (Shove It)".
        const VW = '(?:remaster(?:ed)?|re-?record(?:ed|ing)?|re-?mix(?:ed)?|mix|edit|version|live|mono|stereo|' +
                   'feat\\.?|featuring|from|demo|instrumental|acoustic|bonus\\s+track|deluxe|explicit|clean|' +
                   'anniversary|extended|single|radio|12"|7"|12”|7”|12 inch|7 inch)(?![A-Za-z])';
        const dashRe = new RegExp('\\s+-\\s+(?=(?:(?!\\s-\\s).)*?\\b' + VW + ')(?:(?!\\s-\\s).)*$', 'i');
        const brRe = new RegExp('\\s*(?:\\((?=[^)]*\\b' + VW + ')[^)]*\\)|\\[(?=[^\\]]*\\b' + VW + ')[^\\]]*\\])\\s*$', 'i');
        for (let i = 0; i < 4; i++) {  // tags can stack: "Song (Remix) - 2011 Remaster"
          const t2 = t.replace(dashRe, "").replace(brRe, "").trim();
          if (t2 === t || !t2) break;
          t = t2;
        }
        /*
           Strip common soundtrack suffixes:
             - From "Movie"
             – From "Movie"
             (From "Movie")
        */
        try{
            // hyphen or en-dash variants, straight or curly quotes
            // Handles:
            // From "Movie"
            // From "Movie"/Soundtrack...
            // From "Movie" / Soundtrack...
            //   (From "Movie"/Soundtrack...)
            t = t.replace(/\s*[-–]\s*From\s+["“][^"”]+["”](?:\s*\/\s*[^)]*)?\s*$/i, "");
            t = t.replace(/\s*\(\s*From\s+["“][^"”]+["”](?:\s*\/\s*[^)]*)?\s*\)\s*$/i, "");
            // Extra: if Spotify appends /Soundtrack Version (or similar) without spaces
            t = t.replace(/\s*[-–]\s*From\s+["“][^"”]+["”]\s*\/\s*.*$/i, "");
            t = t.replace(/\s*\(\s*From\s+["“][^"”]+["”]\s*\/\s*.*\)\s*$/i, "");
            t = t.replace(/\s+/g, " " ).trim();
          }catch(_){}

        return t.trim();
      }catch(_){
        try { return String(title||"").trim(); } catch(__){ return ""; }
      }
    }
    /*
       Clean displayed card titles (DOM only) to remove soundtrack suffixes like:
         - From "Frozen"
       Does NOT affect server data / URIs / playlist logic.
    */
    function __soloCleanCardTitlesOnce(){
      try{
        if (window.__soloCleanedCardTitlesOnce) return;
        window.__soloCleanedCardTitlesOnce = true;
        const nodes = document.querySelectorAll(".sqText");
        for (const el of nodes){
          try{
            const raw = (el && el.textContent) ? String(el.textContent) : "";
            const clean = __soloCleanTitleForDisplay(raw);
            if (clean && clean !== raw) el.textContent = clean;
          }catch(_){}
        }
      }catch(_){}
    }
    try{
      if (document.readyState === "loading"){

  async function __soloNextRobustV14(){
    try{
      if (window.__soloNextInFlight) return;
      window.__soloNextInFlight = true;

      // Ensure device/context is active (best-effort)
      try{ if (typeof __soloEnsureActiveDeviceAndContext === "function") { __soloEnsureActiveDeviceAndContext({ensureContext:false}).catch(()=>{}); } }catch(_){}

      // Snapshot current track id so we can verify an actual advance
      let beforeId = null;
      try{
        const pb0 = await spJson("https://api.spotify.com/v1/me/player");
        beforeId = pb0 && pb0.item && pb0.item.id ? pb0.item.id : null;
      }catch(_){}

      // Issue next
      let didNext = false;
      try{
        if (player && typeof player.nextTrack === "function"){
           await player.nextTrack();
          didNext = true;
        }
      }catch(_){}
      if (!didNext){
        try{
          const url = "https://api.spotify.com/v1/me/player/next" + (__soloDeviceId ? ("?device_id=" + encodeURIComponent(__soloDeviceId)) : "");
          await spFetch(url, { method:"POST" });
        }catch(_){}
      }

      // Wait for track id to change (race: UI advances but playback doesn't)
      let afterId = beforeId;
      for (let i=0; i<14; i++){
        try{
          const pb = await spJson("https://api.spotify.com/v1/me/player");
          afterId = pb && pb.item && pb.item.id ? pb.item.id : afterId;
        }catch(_){}
        if (afterId && beforeId && afterId !== beforeId) break;
        try{ await __soloSleep(250); }catch(_){ await new Promise(r=>setTimeout(r,250)); }
      }

      // Force start at 0ms on the *current* track
      try{
        // We intentionally do NOT call seek(0)+play() after /next.
        // Doing so causes the new track to 'blip' and then restart from 0.
        // The /next call already advances playback.
      }catch(_){}

      // UI refresh
      try{ setTimeout(sync, 250); }catch(_){}
      try{ setTimeout(sync, 1200); }catch(_){}
    }catch(e){
      try{ __soloStatus("Next failed: " + (e && e.message ? e.message : e)); }catch(_){}
    }finally{
      try{ window.__soloNextInFlight = false; }catch(_){}
    }
  }

/*
   Replaces the older debounce/guard blocks that leaked `await` into non-async scopes.
   Goal: make Next deterministic and avoid "playlist advances but old song keeps playing".
*/
async function __soloNextV21(){
  try{
    if (window.__soloNextInFlightV21) return;
    window.__soloNextInFlightV21 = true;

    if (typeof __soloNextRobustV14 === "function"){
      await __soloNextRobustV14();
      return;
    }

    if (typeof __soloNextFallback === "function"){
      const r = __soloNextFallback();
      if (r && typeof r.then === "function") await r;
      return;
    }

    // Last resort: Web API next + force seek/play
    const url = "https://api.spotify.com/v1/me/player/next" + (__soloDeviceId ? ("?device_id=" + encodeURIComponent(__soloDeviceId)) : "");
    await spFetch(url, { method:"POST" });
    try{ await __soloSleep(200); }catch(_){ await new Promise(r=>setTimeout(r,200)); }
    // Do not seek+play after /next; it causes audible blips and restarts.

    try{ setTimeout(sync, 250); }catch(_){}
    try{ setTimeout(sync, 1200); }catch(_){}
  }catch(e){
    try{ __soloStatus("Next failed: " + (e && e.message ? e.message : e)); }catch(_){}
  }finally{
    try{ window.__soloNextInFlightV21 = false; }catch(_){}
  }
}
  try{ window.__soloNextV21 = __soloNextV21; }catch(_){ }

  try{
    if (!window.__soloTrackZeroGuardInstalled){
      window.__soloTrackZeroGuardInstalled = true;
      let __lastId = null;
      let __lastChangeAt = 0;
      if (player && typeof player.addListener === "function"){
        player.addListener("player_state_changed", async (st) => {
          try{
            const cur = st && st.track_window && st.track_window.current_track ? st.track_window.current_track.id : null;
            if (cur && cur !== __lastId){
              __lastId = cur;
              __lastChangeAt = Date.now();
            }
            if (cur && (Date.now() - __lastChangeAt) < 4000){
              const pos = typeof st.position === "number" ? st.position : 0;
              if (pos > 1500){
                try{
                  const did = __soloDeviceId || (typeof deviceId !== "undefined" ? deviceId : null);
                  const url = "https://api.spotify.com/v1/me/player/seek?position_ms=0" + (did ? ("&device_id=" + encodeURIComponent(did)) : "");
                  await spFetch(url, { method:"PUT" });
                }catch(_){}
              }
            }
          }catch(_){}
        });
      }
    }
  }catch(_){}

document.addEventListener("DOMContentLoaded", __soloCleanCardTitlesOnce);
      }else{
        __soloCleanCardTitlesOnce();
      }
    }catch(_){}

    function __soloNormKey(v){
      try{
        return String(v||"")
          .normalize("NFKC")
          .replace(/[\u200B-\u200D\uFEFF]/g, "")
          .replace(/[‐-‒–—−]/g, "-")
          .replace(/\s+/g, " ")
          .trim()
          .toLowerCase();
      }catch(_){ return ""; }
    }

  /*
     Clean song titles rendered in the bingo card (display only).
     Strips "- Remastered/Edit/Version/etc" to match played list display. */
  function __soloCleanAllCardSquareTitles(){
    try{
      const nodes = document.querySelectorAll("#soloCardGrid .sqText");
      nodes.forEach((el) => {
        try{
          const raw = String(el.textContent || "").trim();
          if (!raw) return;
          const clean = (typeof __soloCleanTitleForDisplay === "function") ? __soloCleanTitleForDisplay(raw) : raw;
          if (clean && clean !== raw) el.textContent = clean;
        }catch(_){}
      });
    }catch(_){}
  }
  try { __soloCleanAllCardSquareTitles(); } catch(_){}

      function __soloMaybeAddPlayed(title, artist, uri){
      try{
        // Guard: only record after we explicitly allow it.
        if (!__soloAllowTrackAdds) return;

        let t = String(title || "").trim();
        let a = String(artist || "").trim();
        let u = String(uri || "").trim();
        if (!t && !a) return;
        if (!u) return;

        // Block the "pre-start" track URI captured on new game load (prevents blip/late events).
        try{
          const bu = (typeof __soloBlockedTrackUri !== "undefined" && __soloBlockedTrackUri) ? String(__soloBlockedTrackUri) : "";
          if (bu && u === bu) return;
        }catch(_){}
          // (patched v4) Removed duplicate inner cleaner/dedupe block. Use global helpers + single dedupe path below.
        // Dedupe: prevent the same URI from being added twice in the same game.
        // This survives refreshes via sessionStorage.
        try{
          const key = (typeof playedUriStoreKey !== "undefined" && playedUriStoreKey) ? String(playedUriStoreKey) : "";
          if (key){
            let arr = [];
            try { arr = JSON.parse(sessionStorage.getItem(key) || "[]"); } catch(_){ arr = []; }
            if (Array.isArray(arr) && arr.indexOf(u) !== -1) return;
            if (!Array.isArray(arr)) arr = [];
            arr.push(u);
            // keep bounded
            if (arr.length > 200) arr = arr.slice(arr.length - 200);
            try { sessionStorage.setItem(key, JSON.stringify(arr)); } catch(_){}
          } else {
            // Fallback: last-added URI only
            if (u && u === __soloLastAddedTrackUri) return;
          }
        }catch(_){}

        // Update last-added (helps suppress rapid double events)
        try { __soloLastAddedTrackUri = u; } catch(_){}
          // Store display text (cleaned) + de-dupe across versions by (cleanTitle + artist).
          try{
            let ct = t;
            try { ct = (typeof __soloCleanTitleForDisplay === "function") ? __soloCleanTitleForDisplay(t) : t; } catch(_){ ct = t; }
            if (!ct) ct = t;

            // De-dupe across versions using normalized key (cleaned title + artist).
            try{
              const kkey = `soloPlayedKeys:${code}:${playerno}`;
              const k = (typeof __soloNormKey === "function" ? __soloNormKey(ct) : String(ct||"").toLowerCase()) + "||" +
                        (typeof __soloNormKey === "function" ? __soloNormKey(a)  : String(a ||"").toLowerCase());
              let keys = [];
              try { keys = JSON.parse(sessionStorage.getItem(kkey) || "[]"); } catch(_){ keys = []; }
              if (Array.isArray(keys) && keys.indexOf(k) !== -1) return;
              if (!Array.isArray(keys)) keys = [];
              keys.unshift(k);
              if (keys.length > 300) keys = keys.slice(0,300);
              try { sessionStorage.setItem(kkey, JSON.stringify(keys)); } catch(_){}
            }catch(_){}

            try { (function(){
              try{
                const __text = ct + (a ? (" — " + a) : "");
                const __uri =
                  ((typeof curUri === "string" && curUri) ? curUri :
                  ((typeof currentUri === "string" && currentUri) ? currentUri :
                  ((typeof trackUri === "string" && trackUri) ? trackUri :
                  ((typeof uri === "string" && uri) ? uri : ""))));
                addPlayed(__text, {title: ct, artist: a, uri: __uri});
try { __soloPostPlayedTrackResetV1({ title: ct, artist: a, uri: __uri }); } catch(_){ }

              }catch(_){
                try{ addPlayed(ct + (a ? (" — " + a) : "")); }catch(__){}
              }
            })();
    } catch(_){ }
          }catch(_){}
      }catch(_){}
    }

  const playedStoreKey = `soloPlayed:${code}:${playerno}`;

    const playedUriStoreKey = `soloPlayedUris:${code}:${playerno}`;
  let __soloLastAddedTrackUri = null; // dedupe track additions (SDK + Web API fallback)
let gameOver = false;

    try{
      if (String(GAME_STATUS || "" ).toLowerCase() === "ended"){
        try{ disableGameplay(); }catch(_){ }
      }
    }catch(_){ }

  let statusPoller = null;
  let player = null;

    try{ window.__soloPlayer = null; }catch(_){ }

  function setStatus(t){
  // Existing truth source writes to #playStatus (hidden)
  try { if (statusEl) statusEl.textContent = (t || ""); } catch(_) {}

  // ALSO update the visible SOLO line: #soloPlayStatusText
  try{
    var raw = String(t || "").trim();
    var low = raw.toLowerCase();

    var out = null;
    // Common forms produced by existing code: "Playing: ..." / "Paused: ..."
    if (low.indexOf("playing") === 0) out = "Playing";
    else if (low.indexOf("paused") === 0) out = "Paused";
    else if (low.indexOf("is_playing=true") !== -1) out = "Playing";
    else if (low.indexOf("is_playing=false") !== -1) out = "Paused";

    if (out){
      var el = document.getElementById("soloPlayStatusText");
      if (el) el.textContent = out;
    }
  }catch(_){ }
}

    // If this solo session is already ended, do NOT show the winner overlay.
    // Disable all gameplay controls and show a clear finished message.
    if (String(GAME_STATUS || "").toLowerCase() === "ended") {
      try { setStatus("Game over — nice bingo! This solo session is finished."); } catch(_) {}
      try { if (bingoEl) bingoEl.textContent = ""; } catch(_) {}
      try { disableGameplay(); } catch(_) {}
    }

  function disableGameplay(){
    gameOver = true;

    try{ __soloShowEndedHeader(); }catch(_){ }
    try {
      var ht = document.getElementById("soloCardHeaderTitle");
      var hs = document.getElementById("soloCardHeaderSub");
      if (ht) ht.style.display = "none";
      if (hs) hs.style.display = "none";
    } catch(_){ }

      /*
         Allow vertical scrolling after game ends so bottom banner/buttons are reachable. */
      try { document.body.classList.add("soloEnded"); } catch(_){}
      try { document.documentElement.style.overflowY = "auto"; } catch(_){}
      try { document.body.style.overflowY = "auto"; } catch(_){}
      try { if (bingoEl) bingoEl.textContent = ""; } catch(_){}
      try {
        if (typeof endedBannerEl !== "undefined" && endedBannerEl && typeof endedBannerEl.scrollIntoView === "function") {
          endedBannerEl.scrollIntoView({block:"end", behavior:"smooth"});
        }
      } catch(_){}

      try{ if (overlayRoot) { overlayRoot.classList.remove("hidden"); overlayRoot.setAttribute("aria-hidden","false"); } }catch(_){ }
    try { if (btnPlay) btnPlay.disabled = true; } catch(_) {}
    try { if (btnPause) btnPause.disabled = true; } catch(_) {}
    try { if (btnNext) btnNext.disabled = true; } catch(_) {}
    try { if (btnBingo) btnBingo.disabled = true; } catch(_) {}
    try { if (gameOverEl) gameOverEl.style.display = ""; } catch(_) {}

    try { if (statusPoller) clearInterval(statusPoller); } catch(_) {}
    statusPoller = null;

    // stop interactions with squares
    try {
      document.querySelectorAll("#soloCardGrid .sq").forEach((el) => {
        try { el.disabled = true; } catch(_) {}
      });
    } catch(_) {}

    // pause playback best-effort
    try { if (player && typeof player.pause === "function") player.pause(); } catch(_) {}
    try {
      fetch("https://api.spotify.com/v1/me/player/pause", {
        method:"PUT",
        headers:{ "Authorization":"Bearer " + (__soloToken || (typeof token !== "undefined" ? token : "")) }
      }).catch(()=>{});
    } catch(_) {}
  }

    try{
      if (String(GAME_STATUS || "").toLowerCase() === "ended"){
        try{
          if (overlayRoot){
            overlayRoot.classList.add("hidden");
            overlayRoot.setAttribute("aria-hidden", "true");
            overlayRoot.style.display = "none";
          }
        }catch(_){}
        try{ __soloOverlayShown = false; }catch(_){}
        try{ disableGameplay(); }catch(_){}
      }
    }catch(_){}
    try{
      if (typeof GAME_ENDED !== 'undefined' && GAME_ENDED){
        setStatus('Ended');
              disableGameplay();
      }
    }catch(_){ }

  /*
     Fix: Solo bingo overlay uses __soloGetPlayerName() and a capture-phase dismiss hook.
     Some previous edits removed these helpers which breaks solo bingo claim.
     This block is SOLO-ONLY (play_solo.html) and does not affect hosted games. */
  let __soloOverlayShown = false;

  function __soloGetPlayerName(preferred){
    try{
      const p = (preferred !== undefined && preferred !== null) ? String(preferred).trim() : "";
      if (p && p !== "undefined" && p !== "None") return p;
    }catch(_){}
    try{
      const t = (typeof PLAYER_NAME !== "undefined" && PLAYER_NAME !== null) ? String(PLAYER_NAME).trim() : "";
      if (t && t !== "undefined" && t !== "None") return t;
    }catch(_){}
    try{
      // Parse from the subtitle line like: "Session ABC12 — Name"
      const wantPrefix = "Session " + String(code || "").trim();
      const els = Array.from(document.querySelectorAll("div,span,p")).slice(0, 600);
      for (const el of els){
        const txt = (el && el.textContent) ? String(el.textContent).trim() : "";
        if (!txt) continue;
        if (txt.indexOf(wantPrefix) === 0 && txt.indexOf("—") !== -1){
          const parts = txt.split("—");
          const nm = (parts.length >= 2) ? String(parts[1]).trim() : "";
          if (nm) return nm;
        }
      }
    }catch(_){}
    return "Player";
  }

  function __soloEnableOverlayDismissCapture(){
    try{
      if (window.__soloOverlayCaptureBound) return;
      window.__soloOverlayCaptureBound = true;

      document.addEventListener("click", (ev) => {
        try{
          if (typeof overlayRoot === "undefined" || !overlayRoot) return;

          try{
            // Only swallow clicks when overlay is truly visible and interactive.
            const disp = (overlayRoot && overlayRoot.style) ? overlayRoot.style.display : "";
            const hiddenClass = !!(overlayRoot && overlayRoot.classList && overlayRoot.classList.contains("hidden"));
            const ariaHidden = (overlayRoot && overlayRoot.getAttribute) ? overlayRoot.getAttribute("aria-hidden") : null;
            const visible = (!hiddenClass) && (ariaHidden != "true") && (disp !== "none") && (overlayRoot && overlayRoot.offsetParent !== null);
            if (!visible) return;
          }catch(_){ return; }

          if (overlayRoot.classList.contains("hidden")) return;
          if (ev){
            try{ ev.preventDefault(); }catch(_){}
            try{ ev.stopPropagation(); }catch(_){}
          }
          if (typeof dismissOverlayToGameOver === "function") dismissOverlayToGameOver();
        }catch(_){}
      }, true);
    }catch(_){}
  }

  // Winner fireworks (static/fireworks.js), same as the hosted card; stopped by hideOverlay()
  const __soloFireworks = window.createBingoFireworks(document.getElementById("fireworksCanvas"));
  try { window.__bingoFireworks = __soloFireworks; } catch(_) {}  // handy for testing from the console

  function showWinnerOverlay(winnerName){
    if (!overlayRoot) return;
    const nm = __soloGetPlayerName(winnerName);
    __soloOverlayShown = true;
    __soloEnableOverlayDismissCapture();
    overlayRoot.classList.remove("hidden");
    overlayRoot.style.display = "flex";
    overlayRoot.style.pointerEvents = "auto";
    overlayRoot.setAttribute("aria-hidden","false");
    overlayRoot.classList.add("winnerMode");
    overlayRoot.classList.remove("announceMode");
    overlayRoot.classList.remove("thanksMode");
    if (overlayTitle) overlayTitle.textContent = "WINNER!";
    if (overlaySub) overlaySub.textContent = `${nm} got BINGO!`;
    try { __soloFireworks.start(10000); } catch(_) {}
  }

  function hideOverlay(){
    if (!overlayRoot) return;
    try { __soloFireworks.stop(); } catch(_) {}
    __soloOverlayShown = false;
    overlayRoot.classList.add("hidden");
    overlayRoot.style.display = "none";
    overlayRoot.setAttribute("aria-hidden","true");
  }

  // overlay dismiss => game over
  function dismissOverlayToGameOver(){
    hideOverlay();
    disableGameplay();

  }

  try {
    if (overlayRoot) {
      overlayRoot.addEventListener("click", (e) => {
        try {
          // Click anywhere on overlay dismisses it
          dismissOverlayToGameOver();
        } catch(_) {}
        overlayRoot.style.pointerEvents = "none";
      });
    }

    // If server says the solo game is ended, immediately disable UI and stop initialization.
    if ((GAME_STATUS || "").toLowerCase() === "ended"){
      try { disableGameplay(); } catch(_) {}
      // (patched) do not return here; allow played history render
    }
    window.addEventListener("keydown", (e) => {
      try {
        if (e && e.key === "Escape" && overlayRoot && !overlayRoot.classList.contains("hidden")) {
          dismissOverlayToGameOver();
        }
      } catch(_) {}
    });
  } catch(_) {}

  function encodeForm(obj) {
    return Object.keys(obj)
      .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]))
      .join("&");
  }

  if (grid){
    grid.addEventListener("click", async (ev) => {
      if (gameOver) return;
      const btn = ev.target.closest(".sq");
      if (!btn) return;
      if (btn.dataset.free === "true") return;

      const pos = parseInt(btn.getAttribute("data-pos") || "", 10);
      if (isNaN(pos) || pos < 0 || pos > 24) return;

      const row = Math.floor(pos / 5);
      const col = pos % 5;

      // Mark or unmark straight away; the server is told in the background and only a failure undoes it
      const setMarked = (on) => { btn.classList.toggle("marked", on); btn.setAttribute("aria-pressed", on ? "true" : "false"); };
      const wasMarked = btn.classList.contains("marked");
      setMarked(!wasMarked);
      btn.__pending = (btn.__pending || 0) + 1;
      let serverState = null;
      try {
        const resp = await fetch(urlToggle, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json" },
          body: encodeForm({ pos: String(pos), row: String(row), col: String(col) }),
          credentials: "same-origin"
        });
        const text = await resp.text();
        let data = null;
        try { data = JSON.parse(text); } catch(_) { data = null; }
        if (resp.ok && data && data.ok) serverState = !!data.marked;
      } catch(e) {
        console.error("Solo toggle error:", e);
      } finally {
        btn.__pending -= 1;
        // With several quick taps in flight, only the last reply decides; a failed save puts the square back
        if (btn.__pending === 0) setMarked(serverState === null ? wasMarked : serverState);
      }
    });
  }

  // Played tracks
  const playedListEl = document.getElementById("playedList");
  const songsCountEl = document.getElementById("songsCount");

/*
   Reliable SOLO played_track reporting (best-effort, non-blocking).
   This is intentionally isolated and does not depend on any wrapper stacking.
*/
let __soloPlayedTrackResetLastKeyV1 = "";
async function __soloPostPlayedTrackResetV1(meta){
  try{
    meta = meta || {};
    const title  = (meta.title != null)  ? String(meta.title).trim()  : "";
    const artist = (meta.artist != null) ? String(meta.artist).trim() : "";
    const uri    = (meta.uri != null)    ? String(meta.uri).trim()    : "";

    if (!title && !uri) return;

    const key = uri ? ("uri:" + uri) : ("t:" + title.toLowerCase() + "|a:" + artist.toLowerCase());
    if (key && key === __soloPlayedTrackResetLastKeyV1) return;
    __soloPlayedTrackResetLastKeyV1 = key;

    const url = `/player/${encodeURIComponent(code)}/${encodeURIComponent(playerno)}/played_track`;
    await fetch(url, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      credentials: "same-origin",
      body: JSON.stringify({ title, artist, uri })
    }).catch(() => null);
  }catch(_){}
}

  function loadPlayed(){
    try {
      const raw = sessionStorage.getItem(playedStoreKey) || "[]";
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (_) { return []; }
  }

  function savePlayed(list){
    try {
      const arr = Array.isArray(list) ? list : [];
      const out = [];
      for (const it of arr){
        if (typeof it === "string"){
          const t = String(it || "").trim();
          if (t) out.push({ text: t, ts: Date.now() });
        } else if (it && typeof it.text === "string"){
          const t = String(it.text || "").trim();
          if (t) out.push({ text: t, ts: (typeof it.ts === "number") ? it.ts : Date.now() });
        }
      }
      sessionStorage.setItem(playedStoreKey, JSON.stringify(out.slice(0, 50)));
    } catch (_) {}
  }

          function renderPlayed(list){
            if (!playedListEl) return;
            const arr = Array.isArray(list) ? list : [];
            playedListEl.innerHTML = "";

            // Normalize mixed historical formats:
            // ["Title — Artist", ...]
            // [{text:"Title — Artist", ts:...}, ...]
            const norm = [];
            for (const it of arr){
              let txt = "";
              try{
                if (typeof it === "string") txt = it;
                else if (it && typeof it.text === "string") txt = it.text;
                else if (it && typeof it.title === "string" && typeof it.artist === "string") txt = it.title + " — " + it.artist;
                else if (it && typeof it.name === "string") txt = it.name;
              }catch(_){}
              txt = String(txt || "").trim();
              if (!txt) continue;
              norm.push({ text: txt, ts: (it && typeof it.ts === "number") ? it.ts : Date.now() });
            }

            if (!norm.length){
              const empty = document.createElement("div");
              empty.className = "muted";
              empty.textContent = "No tracks played yet.";
              playedListEl.appendChild(empty);
            } else {
              norm.slice(0,50).forEach((it) => {
                const chip = document.createElement("div");
                chip.className = "chip";

                const raw = String(it.text || "").trim();
                const parts = raw.split(" — ");
                const titleRaw = (parts[0] || "").trim();
                  const title = (typeof __soloCleanTitleForDisplay === "function") ? __soloCleanTitleForDisplay(titleRaw) : titleRaw;
                  const artist = parts.slice(1).join(" — ").trim();

                // SOLO Played Tracks: match host markup (title + artist spans)

                const titleSpan = document.createElement("span");

                titleSpan.className = "playedTrackTitle";

                titleSpan.textContent = title || raw;

                chip.appendChild(titleSpan);

                if (artist) {

                  const artistSpan = document.createElement("span");

                  artistSpan.className = "playedTrackArtist";

                  artistSpan.textContent = "— " + artist;

                  chip.appendChild(document.createTextNode(" "));

                  chip.appendChild(artistSpan);

                }
        playedListEl.appendChild(chip);
              });

    }

    try { if (songsCountEl) songsCountEl.textContent = norm.length ? `(${norm.length})` : ""; } catch(_) {}
  }

  const played = loadPlayed();
  renderPlayed(played);
  /* Opened in a new tab or on another device: this tab has no saved list, so rebuild it from the songs the
     server recorded for the game. */
  if (!played.length) {
    fetch(`/player/${encodeURIComponent(code)}/${encodeURIComponent(playerno)}/played_tracks`, { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null)
      .then(j => {
        if (!j || !j.ok || !Array.isArray(j.tracks) || !j.tracks.length || loadPlayed().length) return;
        const list = j.tracks.map(t => ({ text: t.artist ? (t.title + " — " + t.artist) : t.title, ts: Date.now() }));
        savePlayed(list);
        renderPlayed(list);
      })
      .catch(() => {});
  }
  /*
     Always derive played_titles from the same source as the UI list (localStorage),
     so server-side bingo validation matches what the player sees.
  */
  function __soloGetPlayedTitles(){
    try{
      const k = 'playedTracks_' + String(code || '');
      const raw = localStorage.getItem(k) || localStorage.getItem('playedTracks') || '[]';
      const arr = JSON.parse(raw);
      const out = [];
      if (Array.isArray(arr)){
        for (const it of arr){
          if (!it) continue;
          if (typeof it === 'string') { out.push(it); continue; }
          if (it.title) out.push(it.title);
          else if (it.track_title) out.push(it.track_title);
          else if (it.track_name) out.push(it.track_name);
          else if (it.name) out.push(it.name);
          else if (it.text) out.push(it.text);
        }
      }
      return out;
    }catch(e){
      return [];
    }
  }

  function addPlayed(text, meta){
    const t = String(text || "").trim();
    if (!t) return;
    const list = loadPlayed();

    function itemText(x){
      try{
        if (typeof x === "string") return String(x || "").trim();
        if (x && typeof x.text === "string") return String(x.text || "").trim();
        return "";
      }catch(_){ return ""; }
    }

    // newest first, de-dupe by exact text
    const exists = (list || []).some(x => itemText(x) === t);
    if (!exists) (list || []).unshift({ text: t, ts: Date.now() });

    savePlayed(list || []);
    renderPlayed(list || []);
  }

  // Bingo claim
  async function api(path, method, body){
    return await fetch(path, {
      method: method || "GET",
      headers: body ? {"Content-Type":"application/json"} : undefined,
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin"
    });
  }

  // Red outline on dabbed squares whose song hasn't played (set by claimBingo); cleared on the next tap
  function __soloClearNotPlayed(){
    try { document.querySelectorAll("#soloCardGrid .sq.sqNotPlayed").forEach(el => el.classList.remove("sqNotPlayed")); } catch(_) {}
  }
  document.addEventListener("click", (ev) => {
    try { if (!(ev.target && ev.target.closest && ev.target.closest("#btnBingo"))) __soloClearNotPlayed(); } catch(_) {}
  }, true);

  async function claimBingo(){
    if (gameOver) return;
    if (bingoEl) bingoEl.textContent = "Checking…";
    try{
      const marked = [];
      try {
        document.querySelectorAll("#soloCardGrid .sq.marked").forEach((el) => {
          const pos = parseInt(el.getAttribute("data-pos") || "", 10);
          if (!Number.isNaN(pos) && pos >= 0 && pos <= 24) marked.push(pos);
        });
      } catch(_) {}
      if (typeof GAME_ENDED !== "undefined" && GAME_ENDED){
        try{ if (__soloBingoResultEl) __soloBingoResultEl.textContent = "Game already ended."; }catch(_){ }
        try{ disableGameplay(); }catch(_){ }
        return;
      }

        /*
           Goal: prevent SOLO bingo claims that don't match Played Tracks.
           We compute the winning line from the marked squares, then ensure each non-FREE square's title
           appears (normalized) in the Played Tracks list (stored in localStorage via loadPlayed()).
        */
        function __soloNormTitle(s){
          try{
            s = String(s||"");
            s = s.replace(/\u2019/g, "'");
            s = s.toLowerCase();
            // remove bracketed qualifiers like (remaster...), [remastered], etc.
            s = s.replace(/\([^\)]*remaster[^\)]*\)/g, " ");
            s = s.replace(/\[[^\]]*remaster[^\]]*\]/g, " ");
            // collapse punctuation/spaces
            s = s.replace(/[^a-z0-9]+/g, " ");
            s = s.replace(/\s+/g, " ").trim();
            return s;
          }catch(_){ return ""; }
        }

        function __soloGetSquareTitleByPos(pos){
          try{
            const el = document.querySelector('#soloCardGrid .sq[data-pos="'+pos+'"] .sqText');
            if (!el) return "";
            return String(el.textContent||"").trim();
          }catch(_){ return ""; }
        }

        function __soloBingoLines(){
          // 5x5 with FREE center (pos 12) allowed implicitly.
          const L=[];
          // rows
          for (let r=0;r<5;r++){ L.push([r*5, r*5+1, r*5+2, r*5+3, r*5+4]); }
          // cols
          for (let c=0;c<5;c++){ L.push([c, c+5, c+10, c+15, c+20]); }
          // diags
          L.push([0,6,12,18,24]);
          L.push([4,8,12,16,20]);
          return L;
        }

        function __soloFindWinningLine(markedArr){
          try{
            const mk = new Set((markedArr||[]).map(x=>parseInt(x,10)).filter(x=>!Number.isNaN(x)));
            // FREE center always counts
            mk.add(12);
            for (const line of __soloBingoLines()){
              let ok = true;
              for (const pos of line){
                if (pos === 12) continue;
                if (!mk.has(pos)) { ok=false; break; }
              }
              if (ok) return line;
            }
          }catch(_){ }
          return null;
        }

        function __soloPlayedNormSet(){
          try{
            const list = (typeof loadPlayed === 'function') ? (loadPlayed()||[]) : [];
            const out = [];
            for (const it of list){
              let t = "";
              if (typeof it === 'string') t = it;
              else if (it && typeof it.text === 'string') t = it.text;
              t = String(t||"").trim();
              if (!t) continue;
              // played entries are like "Song — Artist"; we match on the song portion.
              const songPart = t.split('—')[0].trim();
              const n = __soloNormTitle(songPart);
              if (n) out.push(n);
            }
            return out;
          }catch(_){ return []; }
        }

        // Count a line only if every square in it has played. If none does, tell the player why: name the
        // dabbed squares whose song hasn't played (and outline them on the card), or say there's no line yet.
        // A stray wrong dab elsewhere doesn't spoil a real bingo; only played dabs are sent to the server,
        // which checks the line again against the songs it recorded.
        let claimMarked = marked;
        try{
          const played = __soloPlayedNormSet();
          const hasPlayed = (pos) => {
            const nt = __soloNormTitle(__soloGetSquareTitleByPos(pos));
            if (!nt) return false;
            // match if any played song contains the square's title or vice-versa (remasters, extra words)
            return played.some(p => p && (p.indexOf(nt) !== -1 || nt.indexOf(p) !== -1));
          };
          const wrong = marked.filter(pos => pos !== 12 && !hasPlayed(pos));
          claimMarked = marked.filter(pos => pos === 12 || hasPlayed(pos));
          if (!__soloFindWinningLine(claimMarked)){
            __soloClearNotPlayed();
            let msg;
            if (wrong.length){
              wrong.forEach(pos => {
                const el = document.querySelector('#soloCardGrid .sq[data-pos="' + pos + '"]');
                if (el) el.classList.add("sqNotPlayed");
              });
              const names = wrong.map(pos => "\u201c" + __soloGetSquareTitleByPos(pos) + "\u201d");
              msg = (wrong.length === 1)
                ? "No bingo yet: " + names[0] + " hasn't played. Tap it to un-dab."
                : "No bingo yet: " + names.slice(0, -1).join(", ") + " and " + names[names.length - 1] + " haven't played. Tap them to un-dab.";
            } else {
              msg = "No bingo yet: you need five in a row (across, down or diagonal).";
            }
            if (bingoEl) bingoEl.textContent = msg;
            return;
          }
        }catch(_){ claimMarked = marked; }
const r = await api(`/player/${code}/${playerno}/claim_bingo`, "POST", { marked: claimMarked, played_titles: __soloGetPlayedTitles() });
      const j = await r.json().catch(()=>({}));
      if (!r.ok){
        if (bingoEl) bingoEl.textContent = `Claim failed (${r.status}): ${j.error || "error"}`;
        return;
      }

      const ok = !!(j && j.auto_valid);
      if (ok) {
  if (bingoEl) bingoEl.textContent = "Bingo!";
} else {
  /*
     Purpose:
       - Always show a friendly "no bingo" message to the user.
       - Never display server diagnostic detail (e.g., "mk=...").
  */
  let msg = "Sorry, No Bingo Yet";
  try {
    const d = (j && typeof j.detail === "string") ? j.detail.trim() : "";
    // Anything that isn't an actual valid bingo should be treated as "no bingo yet"
    // (including: "No complete line found.", "Bingo line not yet played: ...", and mk diagnostics).
    if (d) { msg = "Sorry, No Bingo Yet"; }
    // The server names the line's songs it hasn't recorded as played ("missing=['A', 'B']"): show those
    const m = d.match(/missing=\[(.*?)\]\s*mk=/);
    if (m) {
      const names = (m[1].match(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g) || []).map(x => "\u201c" + x.slice(1, -1) + "\u201d");
      if (names.length) msg = "No bingo yet: " + names.join(", ") + (names.length === 1 ? " hasn't" : " haven't") + " played.";
    }
  } catch (_) {}
  if (bingoEl) bingoEl.textContent = msg;
}
      if (ok) {
        showWinnerOverlay(PLAYER_NAME);
        // NOTE: game ends after overlay dismiss (click/Esc)
      }
    } catch(e){
      if (bingoEl) bingoEl.textContent = "Claim failed: " + (e && e.message ? e.message : e);
    }
  }

  if (btnBingo) btnBingo.addEventListener("click", claimBingo);

  // Spotify SDK + controls (existing behavior can remain; minimal stable subset)
  function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

  // Define the global callback BEFORE loading the SDK.
  window.__soloSpotify = window.__soloSpotify || {
    attempts: 0,
    maxAttempts: 3,
    sdkLoaded: false,
    readyFired: false,
    lastError: ""
  };

  window.onSpotifyWebPlaybackSDKReady = function() {
    try { window.__soloSpotify.readyFired = true; } catch(_) {}
    try {
      if (window.__soloSpotify && typeof window.__soloSpotify._onReady === "function") {
        window.__soloSpotify._onReady();
      }
    } catch (e) {
      try { window.__soloSpotify.lastError = (e && e.message) ? e.message : String(e); } catch(_) {}
    }
  };

  function __soloSetStatus(msg){
    try { if (statusEl) statusEl.textContent = msg || ""; } catch(_) {}
  }

  function __soloRevealReturnButton(){
    try {
      const a = document.getElementById("null");
      if (a) a.style.display = "";
    } catch(_) {}
  }

  function __soloSdkFail(msg){
    __soloSetStatus(msg || "Spotify player failed to load.");
    __soloRevealReturnButton();
  }

  function __soloLoadSdkOnce(){
    try {
      if (document.querySelector('script[src="https://sdk.scdn.co/spotify-player.js"]')) return;
    } catch(_) {}

    const sc = document.createElement("script");
    sc.src = "https://sdk.scdn.co/spotify-player.js";
    sc.async = true;
    sc.onload = () => { try { window.__soloSpotify.sdkLoaded = true; } catch(_) {} };
    sc.onerror = () => { try { window.__soloSpotify.lastError = "SDK script failed to load"; } catch(_) {} };
    document.head.appendChild(sc);
  }

  async function __soloEnsureSdkReady(){
    const st = window.__soloSpotify || (window.__soloSpotify = {});
    st.attempts = 0;

    while (st.attempts < (st.maxAttempts || 3)) {
      st.attempts += 1;
      st.readyFired = false;
      __soloSetStatus(`Loading Spotify player… (attempt ${st.attempts}/3)`);

      // Remove existing SDK tag to retry cleanly.
      try {
        document.querySelectorAll('script[src="https://sdk.scdn.co/spotify-player.js"]').forEach(el => el.remove());
      } catch(_) {}

      __soloLoadSdkOnce();

      const deadline = Date.now() + 6000;
      while (Date.now() < deadline) {
        if (st.readyFired) return true;
        await sleep(150);
      }
    }

    __soloSdkFail("Spotify player failed to load after 3 attempts. Please refresh, or click Return to Play Alone.");
    return false;
  }

  // Minimal, robust Spotify Web Playback boot.
  // Ensures the SDK actually loads and creates Spotify.Player once.
  let __soloDeviceId = null;
  let __soloButtonsWired = false;

  function __soloStatus(msg){
    try { if (typeof setStatus === "function") setStatus(msg || ""); } catch(_) {}
    try { if (typeof __soloSetStatus === "function") __soloSetStatus(msg || ""); } catch(_) {}
  }

  async function __soloPlayFallback(){
      // On the FIRST user click of our Play button for a given solo game,
      // force the expected playlist to start at track 1 / position 0.
      try{
        const startedKey = `soloStarted:${code}:${playerno}`;
        let alreadyStarted = false;
        try { alreadyStarted = (sessionStorage.getItem(startedKey) === "1"); } catch(_) {}
        if (!alreadyStarted && __soloDeviceId && typeof startPlaylistFresh === "function"){
          await startPlaylistFresh(__soloDeviceId);
          return;
        }
      }catch(_){}

        /*
           If this solo game is "armed" (waiting for the user's first Play),
           do NOT resume whatever Spotify considers current playback (which can be mid-song).
           Instead, start the expected playlist explicitly and return.
        */
        try{
          if (window.__soloArmedNeedsStart && window.__soloArmedExpected && window.__soloArmedDeviceId){
            await __soloDoArmedStartFromUserPlay();
            return;
          }
        }catch(_){}

      try{
        // Prefer SDK resume if available, but first ensure embedded device + expected context.
        try { __soloEnsureActiveDeviceAndContext({ensureContext:true}).catch(()=>{}); } catch(_){}
        if (player && typeof player.resume === "function") { await player.resume(); return; }
      } catch(_) {}
      try {
        // Fallback to Web API play on embedded device; if EXPECTED_CONTEXT_URI exists, enforce it.
        try { __soloEnsureActiveDeviceAndContext({ensureContext:true}).catch(()=>{}); } catch(_){ }
const url = "https://api.spotify.com/v1/me/player/play" + (__soloDeviceId ? ("?device_id=" + encodeURIComponent(__soloDeviceId)) : "");
        // If we know the expected playlist, start it explicitly (prevents resume-loop).
        let expected = "";
        try { expected = (typeof EXPECTED_CONTEXT_URI !== "undefined") ? String(EXPECTED_CONTEXT_URI || "") : ""; } catch(_){ expected = ""; }
        const headers = { "Authorization":"Bearer " + (__soloToken || (typeof token !== "undefined" ? token : "")) };
        if (expected) {
          await spFetch(url, { method:"PUT", headers: { "Authorization": headers.Authorization, "Content-Type":"application/json" }, body: JSON.stringify({ context_uri: expected, position_ms: 0 }) });
        } else {
          await spFetch(url, { method:"PUT", headers });
        }
} catch(e) {
        __soloStatus("Play failed: " + (e && e.message ? e.message : e));
      }
    }

    async function __soloPauseFallback(){
    try {
      if (player && typeof player.pause === "function") { await player.pause(); return; }
    } catch(_) {}
    try {
      const url = "https://api.spotify.com/v1/me/player/pause" + (__soloDeviceId ? ("?device_id=" + encodeURIComponent(__soloDeviceId)) : "");
      await spFetch(url, { method:"PUT", headers:{ "Authorization":"Bearer " + (__soloToken || (typeof token !== "undefined" ? token : "")) } });
    } catch(e) {
      __soloStatus("Pause failed: " + (e && e.message ? e.message : e));
    }
  }

      function __soloWireButtonsOnce(){
    if (__soloButtonsWired) return;
    __soloButtonsWired = true;
    try { if (btnPlay)  btnPlay.addEventListener("click", () => { if (!gameOver) __soloPlayFallback(); }); } catch(_) {}
    try { if (btnPause) btnPause.addEventListener("click", () => { if (!gameOver) __soloPauseFallback(); }); } catch(_) {}
    try { if (btnNext)  btnNext.addEventListener("click", () => { if (!gameOver) { try{ if (typeof __soloNextV21 === "function") { __soloNextV21(); } else if (window.__soloNextV21) { window.__soloNextV21(); } }catch(_){} } }); } catch(_) {}
  }

  // Define init hook BEFORE we try to load the SDK.
  try {
    window.__soloSpotify = window.__soloSpotify || {};
    window.__soloSpotify._onReady = function(){
      try {
        if (player) { __soloWireButtonsOnce(); return; }
        if (!window.Spotify || !Spotify.Player) { __soloSdkFail("Spotify SDK loaded, but Spotify.Player is unavailable."); return; }

        __soloStatus("Initializing Spotify player…");

        player = new Spotify.Player({
          name: "Music Bingo Solo (" + String(code || "") + ")",
          getOAuthToken: (cb) => {
            try {
              Promise.resolve(__soloEnsureToken(false))
                .then((t) => { try { cb(t); } catch(_) {} })
                .catch(() => { try { cb(token); } catch(_) {} });
            } catch(_) { try { cb(token); } catch(_) {} }
          },          volume: 0.8
        });
        try{ window.__soloPlayer = player; }catch(_){ }

        player.addListener("ready", ({ device_id }) => {
          __soloDeviceId = device_id || null;

            // Device activation (transfer, play=false) happens inside startPlaylistFresh, in order. It used to
            // run here in parallel, and when it landed after the playlist started it paused the first song.
          __soloStatus("Spotify player ready.");
          try { startStatusPoller(); } catch(_) {}
          try { refreshStatusOnce(); } catch(_) {}
          if (__soloDeviceId) {
            startPlaylistFresh(__soloDeviceId).catch((e) => {
              __soloStatus("Spotify ready, but failed to start playlist: " + (e && e.message ? e.message : e));
            });
          }
        });

        player.addListener("not_ready", () => {
          __soloStatus("Spotify player went offline.");
        });

        player.addListener("initialization_error", ({ message }) => { __soloDisableAll("Spotify init error: " + (message || "unknown")); });
        player.addListener("authentication_error", ({ message }) => { __soloDisableAll("Spotify auth error: " + (message || "token invalid")); });
        player.addListener("account_error", ({ message }) => { __soloDisableAll("Spotify account error: " + (message || "account issue")); });
        player.addListener("playback_error", ({ message }) => { __soloStatus("Spotify playback error: " + (message || "unknown")); });

          // Instant UI updates: use Web Playback SDK state events (no 2.5s poll delay)
          player.addListener("player_state_changed", (s) => {
            try{
              if (!s) return;
              const title = s.track_window && s.track_window.current_track && s.track_window.current_track.name ? String(s.track_window.current_track.name) : "";
              const artist = (s.track_window && s.track_window.current_track && s.track_window.current_track.artists)
                ? ((s.track_window.current_track.artists[0] || {}).name || "")  // main artist only (like hosted games)
                : "";
              const uri = s.track_window && s.track_window.current_track && s.track_window.current_track.uri ? String(s.track_window.current_track.uri) : "";
                try{
                  const expected = (typeof EXPECTED_CONTEXT_URI !== "undefined") ? String(EXPECTED_CONTEXT_URI) : "";
                  const ctxNow = (s && s.context && s.context.uri) ? String(s.context.uri) : "";
                  if (expected && ctxNow && ctxNow !== expected) return;
                  const bu = (typeof __soloBlockedTrackUri !== "undefined" && __soloBlockedTrackUri) ? String(__soloBlockedTrackUri) : "";
                  if (bu && uri && String(uri) === bu) return;
                }catch(_){}
                try { __soloAllowTrackAdds = true; } catch(_) {}
                try { window.__soloAllowTrackAdds = true; } catch(_) {}

              const paused = !!s.paused;

              if (title || artist){
                try { setStatus((paused ? "Paused: " : "Playing: ") + title + (artist ? (" — " + artist) : "")); } catch(_) {}
                if (uri){
                    // Played Tracks gets the song once the now-playing box reveals it (10s in)
                    let shown = title;
                    try { shown = __soloCleanTitleForDisplay(title) || title; } catch(_) {}
                    try {
                      try { window.__soloHintTrack(title, uri); } catch(_) {}   // lights at once, not at the reveal
                      window.__soloReveal.update({ uri, title: shown, artist, posMs: s.position, paused,
                                                   onReveal: () => __soloMaybeAddPlayed(title, artist, uri) });
                    } catch(_) { try { __soloMaybeAddPlayed(title, artist, uri); } catch(__) {} }
                  }
              }
            }catch(_){}
          });

        __soloWireButtonsOnce();

        if (typeof __soloConnectWithRetry === "function") {
          __soloConnectWithRetry();
        } else {
          player.connect().then((ok) => {
            if (!ok) __soloDisableAll("Could not connect to Spotify player. Please refresh, or return to Play Alone.");
          }).catch(() => {
            __soloDisableAll("Could not connect to Spotify player. Please refresh, or return to Play Alone.");
          });
        }
      } catch(e) {
        __soloDisableAll("Spotify init crashed: " + (e && e.message ? e.message : e));
      }
    };
  } catch(_) {}

  // Boot: load SDK + wait for ready callback once.
  (async function __soloBoot(){
    try {
      if (!token || token === "None" || token === "undefined") { __soloDisableAll("Missing Spotify access token."); return; }
      const ok = await __soloEnsureSdkReady();
      if (!ok) return;
      try { if (window.__soloSpotify && typeof window.__soloSpotify._onReady === "function") window.__soloSpotify._onReady(); } catch(_) {}
    } catch(e) {
      __soloSdkFail("Spotify player failed to boot: " + (e && e.message ? e.message : e));
    }

      (function(){
        try{
          if (window.__soloPanelHeightSyncBound) return;
          window.__soloPanelHeightSyncBound = true;

          function __soloClearRightPanel(){
            const right = document.getElementById('soloPlayedPanel');
            if (!right) return;
            right.style.height = '';
            right.style.maxHeight = '';
            right.style.overflow = '';
          }

          function __syncSoloPanelHeights(){
            try{
              // On small screens the panels stack; syncing heights causes overlap.
              if (window.matchMedia && window.matchMedia('(max-width: 900px)').matches){
                __soloClearRightPanel();
                return;
              }

              const left  = document.getElementById('soloCardPanel');
              const right = document.getElementById('soloPlayedPanel');
              if (!left || !right) return;

              const h = left.offsetHeight || 0;
              if (!h) return;

              right.style.height = h + 'px';
              right.style.maxHeight = h + 'px';
              right.style.overflow = 'hidden';

              const list = document.getElementById('playedList');
              if (list){
                list.style.overflowY = 'auto';
                list.style.overflowX = 'hidden';
              }
            }catch(_){ }
          }

          window.addEventListener('load', __syncSoloPanelHeights);
          window.addEventListener('resize', () => { try{ __syncSoloPanelHeights(); }catch(_){ } });

          const list = document.getElementById('playedList');
          if (list && ('MutationObserver' in window)){
            try{
              const mo = new MutationObserver(() => { try{ __syncSoloPanelHeights(); }catch(_){ } });
              mo.observe(list, { childList:true, subtree:true });
            }catch(_){ }
          }

          try{ setTimeout(__syncSoloPanelHeights, 50); }catch(_){ }
        }catch(_){ }
      })();

  })();

async function spFetch(url, opts){
      // Ensure we have a token and an Authorization header for Spotify Web API calls.
      try {
        if (!__soloToken) { await __soloEnsureToken(false); }
      } catch(e) {
        // Let the request go through; caller will handle error messages.
      }
      opts = opts || {};
      opts.headers = opts.headers || {};
      // Normalize header key (Fetch will accept either; we set if missing).
      if (!opts.headers["Authorization"] && !opts.headers["authorization"]) {
        if (__soloToken) opts.headers["Authorization"] = "Bearer " + __soloToken;
        else if (typeof token !== "undefined" && token) opts.headers["Authorization"] = "Bearer " + token;
      }

      let r = await fetch(url, opts);
      if (r && r.status == 401) {
        try {
          await __soloEnsureToken(true);
          opts = opts || {};
          opts.headers = opts.headers || {};
          opts.headers["Authorization"] = "Bearer " + (__soloToken || token);
        } catch(_) {}
        r = await fetch(url, opts);
      }
    if (r.status === 204) return null;
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      throw new Error(`Spotify ${r.status} ${r.statusText} @ ${url} ${t ? ("- " + t.slice(0, 200)) : ""}`);
    }
    return r;
  }

    async function spJson(url){
      // Use spFetch() so GETs inherit token acquisition + 401 refresh/retry logic.
      const r = await spFetch(url, { method: "GET", cache: "no-store" });
      if (r === null) return null; // spFetch returns null on 204
      return await r.json().catch(() => null);
    }

/**
 * Transfer playback to deviceId.
 * Important: Spotify transfer endpoint accepts {"device_ids":[...], "play": true|false}
 * We default play=true so we do not accidentally pause on transfer.
 */
async function transferToDevice(deviceId, play){
  try{
    if (!deviceId) return false;
    const body = { device_ids: [deviceId], play: (typeof play === "boolean" ? play : true) };
    const r = await spFetch("https://api.spotify.com/v1/me/player", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    // 204 is success. 202 can occur. Ignore failures; callers handle fallback.
    return !!(r && (r.status === 204 || r.status === 202 || r.ok));
  }catch(_){
    return false;
  }
}

async function __soloSleep(ms){ return new Promise(r => setTimeout(r, ms)); }

  async function startPlaylistFresh(deviceId){
    try { window.__soloStartInFlight = window.__soloStartInFlight || false; } catch(_) {}
    if (window.__soloStartInFlight) return;
    window.__soloStartInFlight = true;

    const startedKey = `soloStarted:${code}:${playerno}`;
    let alreadyStarted = false;
    try { alreadyStarted = (sessionStorage.getItem(startedKey) === "1"); } catch(_) {}

    try{
      // Ensure we have a token for Web API calls.
      try { await __soloEnsureToken(false); } catch(_) {}

      const expected = String(EXPECTED_CONTEXT_URI || "");
      if (!deviceId || !expected) return;

      // If we've already started this game once in this tab/session, don't rewind.
      if (alreadyStarted){
        // Still make this tab's player the active device (as before), without starting or rewinding anything.
        try { await transferToDevice(deviceId, false); } catch(_) {}
        try { window.__soloReveal.playbackStarted(false); } catch(_) {}
        try { __soloAllowTrackAdds = true; } catch(_) {}
        try { window.__soloAllowTrackAdds = true; } catch(_) {}
        return;
      }

      // Prefer embedded device as the active device, but do NOT autoplay on transfer.
      try { await transferToDevice(deviceId, false); } catch(_) {}

      // Pause quickly to reduce "blip" from whatever was previously active.
      try{
        await spFetch("https://api.spotify.com/v1/me/player/pause?device_id=" + encodeURIComponent(deviceId), {
          method: "PUT",
          headers: { "Authorization": "Bearer " + (__soloToken || (typeof token !== "undefined" ? token : "")) }
        });
      }catch(_){}

      // Whatever the player holds now (the transfer brings over the previous game's last song) isn't ours
      try {
        const cur = window.__soloPlayer && window.__soloPlayer.getCurrentState ? await window.__soloPlayer.getCurrentState() : null;
        const left = cur && cur.track_window && cur.track_window.current_track ? cur.track_window.current_track.uri : "";
        window.__soloReveal.beginGame(left);
      } catch(_) { try { window.__soloReveal.beginGame(""); } catch(__) {} }

      // Start the playlist at a random song (like hosted games), from the beginning of that song.
      const authHdr = "Bearer " + (__soloToken || (typeof token !== "undefined" ? token : ""));
      let offset = 0;
      try {
        const pid = expected.split(":").pop();
        const meta = await spJson("https://api.spotify.com/v1/playlists/" + encodeURIComponent(pid) + "?fields=tracks.total");
        const total = Number(meta && meta.tracks && meta.tracks.total) || 0;
        if (total > 0) offset = Math.floor(Math.random() * total);
      } catch(_) {}
      const url = "https://api.spotify.com/v1/me/player/play?device_id=" + encodeURIComponent(deviceId);
      await spFetch(url, {
        method: "PUT",
        headers: { "Authorization": authHdr, "Content-Type": "application/json" },
        body: JSON.stringify({ context_uri: expected, offset: { position: offset }, position_ms: 0 })
      });
      try { window.__soloReveal.playbackStarted(true); } catch(_) {}

      // Shuffle and repeat must be set AFTER play (starting a context resets shuffle). Repeat = whole
      // playlist, so reaching the end wraps around instead of handing over to Spotify Autoplay.
      for (const q of ["shuffle?state=true", "repeat?state=context"]) {
        for (let i = 0; i < 3; i++) {
          try {
            await __soloSleep(i === 0 ? 400 : 800);
            // spFetch throws on an error status, so getting here means Spotify accepted it
            await spFetch("https://api.spotify.com/v1/me/player/" + q + "&device_id=" + encodeURIComponent(deviceId), {
              method: "PUT", headers: { "Authorization": authHdr }
            });
            break;
          } catch(_) {}
        }
      }

      try { sessionStorage.setItem(startedKey, "1"); } catch(_) {}

      // Enable played-track history now that we're on the right playlist.
      try { __soloAllowTrackAdds = true; } catch(_) {}
      try { window.__soloAllowTrackAdds = true; } catch(_) {}

      try { setStatus("Playing"); } catch(_) {}
    } catch(e){
      try { __soloStatus("Failed to start playlist fresh: " + (e && e.message ? e.message : e)); } catch(_) {}
    } finally {
      try { window.__soloStartInFlight = false; } catch(_) {}
    }
  }

    async function refreshStatusOnce(){
      try {
        const pb = await spJson("https://api.spotify.com/v1/me/player");
        const title = pb && pb.item && pb.item.name ? String(pb.item.name) : "";
        const artist = pb && pb.item && pb.item.artists && pb.item.artists[0] && pb.item.artists[0].name ? String(pb.item.artists[0].name) : "";
        const uri = pb && pb.item && pb.item.uri ? String(pb.item.uri) : "";
        const paused = pb && pb.is_playing === false;
        if (title || artist) {
          setStatus((paused ? "Paused: " : "Playing: ") + title + (artist ? (" — " + artist) : ""));
          if (uri) {
            let shown = title;
            try { shown = __soloCleanTitleForDisplay(title) || title; } catch(_) {}
            try {
              try { window.__soloHintTrack(title, uri); } catch(_) {}
                      window.__soloReveal.update({ uri, title: shown, artist, posMs: pb.progress_ms, paused,
                                           onReveal: () => __soloMaybeAddPlayed(title, artist, uri) });
            } catch(_) { try { __soloMaybeAddPlayed(title, artist, uri); } catch(__) {} }
          }
        }
      } catch(_) {}
    }

    function startStatusPoller(){
    if (statusPoller) return;
    statusPoller = setInterval(() => {
      if (gameOver) return;
      refreshStatusOnce();
    }, 15000);
  }

    // --- Spotify connect retry (solo) ---
    let __soloConnectInFlight = false;

    function __soloShowReturn(){
      try {
        const a = document.getElementById("null");
        if (a) a.style.display = "";
      } catch(_) {}
    }

    function __soloDisableAll(reason){
      try { if (typeof setStatus === "function") setStatus(reason || "Spotify unavailable."); } catch(_) {}
      try { __soloShowReturn(); } catch(_) {}

      try { if (btnPlay)  btnPlay.disabled = true; } catch(_) {}
      try { if (btnPause) btnPause.disabled = true; } catch(_) {}
      try { if (btnNext)  btnNext.disabled = true; } catch(_) {}
      try { if (btnBingo) btnBingo.disabled = true; } catch(_) {}

      try {
        document.querySelectorAll("#soloCardGrid .sq").forEach((el) => { try { el.disabled = true; } catch(_) {} });
      } catch(_) {}

      try { if (statusPoller) { clearInterval(statusPoller); statusPoller = null; } } catch(_) {}
      try { if (typeof gameOver !== "undefined") gameOver = true; } catch(_) {}
    }

    async function __soloConnectWithRetry(){
  try{
    if (window.__soloConnectInFlight) return;
    window.__soloConnectInFlight = true;

    let ok = false;
    for (let attempt = 1; attempt <= 3; attempt++){
      try{
        ok = await player.connect();
      }catch(_){
        ok = false;
      }

      if (ok){
        window.__soloConnectInFlight = false;
        try { setStatus("Spotify player connected."); } catch(_) {}
        return;
      }

      try { await sleep(900); } catch(_) {}
    }

    window.__soloConnectInFlight = false;
    __soloDisableAll("Could not connect to Spotify player after 3 attempts. Please refresh, or return to Play Alone.");
  }catch(_){
    try{ window.__soloConnectInFlight = false; }catch(__){}
    try{ __soloDisableAll("Could not connect to Spotify player. Please refresh, or return to Play Alone."); }catch(__){}
  }
}
// --- /Spotify connect retry (solo) ---

})();
