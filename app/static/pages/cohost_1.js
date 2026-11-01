// The co-host page: bingo calls to accept or reject, kept up to date by the host's messages (and a slow refresh as a backup).
(function () {
  var CODE = document.body.getAttribute("data-code"), TOKEN = document.body.getAttribute("data-token");
  var BASE = "/cohost/" + encodeURIComponent(CODE) + "/" + encodeURIComponent(TOKEN);
  var claimsEl = document.getElementById("claims"), playedEl = document.getElementById("played"), msg = document.getElementById("msg");
  var roundNo = document.getElementById("roundNo"), patternName = document.getElementById("patternName");

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

  function decide(id, action, btns) {
    btns.forEach(function (b) { b.disabled = true; });
    fetch(BASE + "/claim/" + id, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: action }) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) { msg.textContent = x.ok ? (action === "accept" ? "Accepted. The host can now continue or end the game." : "Rejected.") : (x.j.error === "link_off" ? "This link was turned off." : (x.j.error || "That didn't work.")); load(); })
      .catch(function () { msg.textContent = "No connection. Try again."; btns.forEach(function (b) { b.disabled = false; }); });
  }

  function renderClaim(c) {
    var box = el("div", "claim");
    var head = el("div", "head"), who = el("span", "who");
    var av = el("span", "avatar sm avc-" + c.pic.color, c.pic.emoji); av.setAttribute("role", "img"); av.setAttribute("aria-label", c.pic.label);
    who.appendChild(av); who.appendChild(document.createTextNode(" " + c.name)); head.appendChild(who);
    head.appendChild(el("span", "badge " + (c.auto_valid ? "ok" : "bad"), c.auto_valid ? "Auto-check: valid" : "Auto-check: not valid"));
    box.appendChild(head);
    if (c.why) box.appendChild(el("div", "why", c.why));
    if (c.status === "pending") {
      var actions = el("div", "actions"), no = el("button", "", c.auto_valid ? "Reject" : "Reject"), yes = el("button", "yes", c.auto_valid ? "Accept" : "Accept anyway");
      no.type = yes.type = "button";
      no.addEventListener("click", function () { decide(c.id, "reject", [no, yes]); });
      yes.addEventListener("click", function () { decide(c.id, "accept", [no, yes]); });
      actions.appendChild(no); actions.appendChild(yes); box.appendChild(actions);
    } else {
      box.appendChild(el("div", "done", c.status === "accepted" ? "Accepted" : "Rejected"));
    }
    return box;
  }

  function render(s) {
    roundNo.textContent = s.round; document.getElementById("roundPart").hidden = s.round <= 1; patternName.textContent = s.pattern.label;
    claimsEl.textContent = "";
    var pending = s.claims.filter(function (c) { return c.status === "pending"; }), decided = s.claims.filter(function (c) { return c.status !== "pending"; });
    if (!s.claims.length) claimsEl.appendChild(el("div", "muted", "No bingo calls yet."));
    pending.concat(decided).forEach(function (c) { claimsEl.appendChild(renderClaim(c)); });
    playedEl.textContent = "";
    if (!s.played.length) playedEl.appendChild(el("li", "muted", "Nothing played yet."));
    s.played.forEach(function (t) { var li = el("li", "", t.title + " "); li.appendChild(el("span", "a", "— " + t.artist)); playedEl.appendChild(li); });
    if (s.status === "ended") msg.textContent = "The game has ended.";
  }

  function load() {
    fetch(BASE + "/state", { credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) { if (x.ok) render(x.j); else msg.textContent = "This co-host link is not working. Ask the host for a new one."; })
      .catch(function () {});
  }
  load();
  setInterval(load, 20000);
  function connect(retry) {
    var ws;
    try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/cohost/" + encodeURIComponent(CODE) + "/" + encodeURIComponent(TOKEN)); } catch (e) { return; }
    ws.onmessage = function (ev) {
      var d; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d && (d.type === "claims_updated" || d.type === "claims" || d.type === "pattern" || d.type === "track" || d.type === "room")) load();
    };
    ws.onclose = function () { setTimeout(function () { connect(retry + 1); load(); }, Math.min(15000, 1000 * Math.pow(2, retry))); };
  }
  connect(0);
})();
