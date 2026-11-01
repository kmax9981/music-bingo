// The player's "Winners so far" box and the final list on the game-over screen. player_card.js calls refreshWinners()
// whenever the host's messages say something changed.
(function () {
  var CODE = window.BINGO_PLAYER && window.BINGO_PLAYER.code;
  var box = document.getElementById("winnersBox"), count = document.getElementById("winnersCount"), list = document.getElementById("winnersList"), fin = document.getElementById("finalWinners");

  function pic(p) {
    var s = document.createElement("span"); s.className = "avatar sm avc-" + p.color; s.textContent = p.emoji; s.setAttribute("role", "img"); s.setAttribute("aria-label", p.label); return s;
  }
  function row(parts, picture) {
    var li = document.createElement("li");
    if (picture) { li.appendChild(pic(picture)); li.appendChild(document.createTextNode(" ")); }
    parts.forEach(function (p) { var e = document.createElement(p.tag || "span"); if (p.cls) e.className = p.cls; e.textContent = p.text; li.appendChild(e); li.appendChild(document.createTextNode(" ")); });
    return li;
  }
  function render(b) {
    var wins = b.wins || [];
    if (box) box.hidden = wins.length === 0;
    if (count) count.textContent = wins.length;
    if (list) { list.textContent = ""; wins.forEach(function (w) { list.appendChild(row([{ tag: "b", text: w.name }, { cls: "what", text: (b.round > 1 ? "round " + w.round + " · " : "") + w.pattern }], w.pic)); }); }
    if (fin) {
      fin.textContent = "";
      (b.standings || []).slice(0, 5).forEach(function (s) { fin.appendChild(row([{ tag: "b", text: s.name }, { cls: "what", text: s.wins + (s.wins === 1 ? " win" : " wins") }], s.pic)); });
    }
  }
  window.refreshWinners = function () {
    if (!CODE) return;
    fetch("/game/" + encodeURIComponent(CODE) + "/winners.json", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (b) { if (b) render(b); }).catch(function () {});
  };
  window.refreshWinners();
})();
