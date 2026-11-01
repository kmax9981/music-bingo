/*
   "Are the printed cards out of date?" notices. Any element with data-stale-check="<game code>" gets filled in:
   a green "cards match the playlist" line, or a warning that lists the songs that left the playlist and the cards
   that have them, with an "Update N cards" button that swaps only those songs on only those cards and opens
   a print page with just the changed cards. data-status is the game's status (cards can't change mid-game). */
(function () {
  function esc(t) { var d = document.createElement("div"); d.textContent = String(t); return d.innerHTML; }
  function some(arr, n) { return arr.slice(0, n).join(", ") + (arr.length > n ? ", …" : ""); }
  // The app rejects POSTs without a CSRF token, and the print page is a standalone page (no site-wide script
  // adding it), so send it from the page's meta tag. Empty (and ignored) where there is no CSRF protection.
  function csrfHeaders() { var m = document.querySelector('meta[name="csrf-token"]'); return m && m.content ? { "X-CSRF-Token": m.content } : {}; }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  async function check(el) {
    var code = el.dataset.staleCheck, status = (el.dataset.status || "").toLowerCase();
    var d;
    try {
      var r = await fetch("/host/game/" + encodeURIComponent(code) + "/paper/missing", { credentials: "same-origin", cache: "no-store" });
      d = await r.json();
    } catch (e) { el.innerHTML = ""; return; }
    if (!d || !d.paper_cards) { el.innerHTML = ""; return; }
    if (d.unchecked) { el.innerHTML = '<div class="muted small">Couldn\'t check the cards against the playlist just now.</div>'; return; }
    if (!d.missing.length) {
      el.innerHTML = '<div class="staleOk small">✓ Cards match the playlist</div>';
      return;
    }
    var n = d.affected_cards.length;
    var inGame = status === "started";
    el.innerHTML =
      '<div class="staleBanner" role="alert">' +
      '<div class="staleTitle">⚠ Cards out of date</div>' +
      '<div>' + plural(d.missing.length, "song on your paper cards is", "songs on your paper cards are") +
      " no longer in the playlist (" + esc(some(d.missing, 5)) + "). That affects " + n + " of " + d.total_cards +
      " cards (" + esc(some(d.affected_cards, 12)) + "): those squares can't be won.</div>" +
      (inGame ? '<div class="muted small mt6">A game is being played with these cards. Update them once it\'s finished (or use Play again).</div>'
              : '<button type="button" class="btn btnPrimary staleBtn">Update ' + plural(n, "card", "cards") + "</button>") +
      '<div class="staleMsg small"></div></div>';
    var btn = el.querySelector(".staleBtn"), msg = el.querySelector(".staleMsg");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      if (!confirm("Replace the removed songs on " + plural(n, "card", "cards") + " (" + some(d.affected_cards, 12) +
          ") with other songs from the playlist?\n\nYou'll need to reprint those cards; the old printed versions won't match any more. All other cards stay exactly as printed.")) return;
      btn.disabled = true; msg.textContent = "Updating…";
      try {
        var r = await fetch("/host/game/" + encodeURIComponent(code) + "/paper/update", { method: "POST", credentials: "same-origin", headers: csrfHeaders() });
        var j = await r.json().catch(function () { return {}; });
        if (!r.ok || !j.ok) { msg.textContent = j.error || "Couldn't update the cards."; btn.disabled = false; return; }
        if (j.failed && j.failed.length) { msg.textContent = "Cards " + j.failed.join(", ") + " couldn't be fully updated (not enough other songs in the playlist)."; }
        if (j.updated && j.updated.length) { location.href = "/host/game/" + encodeURIComponent(code) + "/paper?cards=" + j.updated.join(","); }
        else { btn.disabled = false; }
      } catch (e) { msg.textContent = "Couldn't update the cards. Check your connection."; btn.disabled = false; }
    });
  }

  // A button (data-stale-badge="<game code>"): marked with a warning when songs on the cards have left the playlist
  async function badge(el) {
    try {
      var r = await fetch("/host/game/" + encodeURIComponent(el.dataset.staleBadge) + "/paper/missing", { credentials: "same-origin", cache: "no-store" });
      var d = await r.json();
      if (d && d.paper_cards && !d.unchecked && d.missing && d.missing.length) {
        el.classList.add("stale");
        el.textContent = "⚠ " + el.textContent.trim();
        el.title = "Cards out of date: " + d.affected_cards.length + " of " + d.total_cards + " cards have songs that left the playlist. Open to update them.";
      }
    } catch (e) {}
  }

  function init() {
    document.querySelectorAll("[data-stale-check]").forEach(check);
    document.querySelectorAll("[data-stale-badge]").forEach(badge);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
