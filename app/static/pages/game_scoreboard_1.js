// The scoreboard screen: the winner of each round and who has the most wins; follows the game as bingos are accepted.
(function () {
  var CODE = document.body.getAttribute("data-code");
  var winsList = document.getElementById("winsList"), standList = document.getElementById("standList"), roundNow = document.getElementById("roundNow");

  function pic(p) {
    var s = document.createElement("span"); s.className = "avatar sm avc-" + p.color; s.textContent = p.emoji; s.setAttribute("role", "img"); s.setAttribute("aria-label", p.label); return s;
  }
  function item(parts, picture) {
    var li = document.createElement("li");
    if (picture) { li.appendChild(pic(picture)); li.appendChild(document.createTextNode(" ")); }
    parts.forEach(function (p) { var e = document.createElement(p.tag || "span"); if (p.cls) e.className = p.cls; e.textContent = p.text; li.appendChild(e); li.appendChild(document.createTextNode(" ")); });
    return li;
  }
  function fill(list, rows, make) {
    list.textContent = "";
    if (!rows.length) { var li = document.createElement("li"); li.className = "muted"; li.textContent = "No winners yet."; list.appendChild(li); return; }
    rows.forEach(function (r) { list.appendChild(make(r)); });
  }
  function render(b) {
    roundNow.textContent = b.round > 1 ? "Round " + b.round : "";
    fill(winsList, b.wins, function (w) { return item([{ tag: "b", text: w.name }, { cls: "what", text: (b.round > 1 ? "round " + w.round + " · " : "") + w.pattern }], w.pic); });
    fill(standList, b.standings, function (s) { return item([{ tag: "b", text: s.name }, { cls: "what", text: s.wins + (s.wins === 1 ? " win" : " wins") }], s.pic); });
  }
  function load() {
    fetch("/host/game/" + encodeURIComponent(CODE) + "/scoreboard.json", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (b) { if (b) render(b); }).catch(function () {});
  }
  load();
  function connect(retry) {
    var ws;
    try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/host/game/" + encodeURIComponent(CODE)); } catch (e) { return; }
    ws.onmessage = function (ev) {
      var d; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d && (d.type === "claims_updated" || d.type === "claims" || d.type === "pattern" || (d.type === "room" && d.event === "bingo"))) load();
    };
    ws.onclose = function () { setTimeout(function () { connect(retry + 1); load(); }, Math.min(15000, 1000 * Math.pow(2, retry))); };
  }
  connect(0);
})();
