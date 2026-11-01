/* Bingo hints: light the B/I/N/G/O tile of the column where the song now playing sits on this card.
   Shared by the phone card and the solo page. The card is matched in the browser: the song title is already
   known here, so nothing about other players' cards is ever sent. */
(function () {
  function norm(s) {
    s = String(s || "").toLowerCase();
    s = s.replace(/\s*[\(\[][^\)\]]*[\)\]]\s*/g, " ");              // (Remastered), [Live] ...
    s = s.replace(/\s+-\s+.*$/, " ");                                 // " - 2011 Remaster", " - Single Version"
    return s.replace(/[^a-z0-9]+/g, " ").trim();
  }
  function columnFor(grid, title) {
    var want = norm(title);
    if (!grid || !want) return -1;
    var sq = grid.querySelectorAll(".sq");
    for (var i = 0; i < sq.length; i++) {
      var el = sq[i];
      if (el.classList.contains("free") || el.getAttribute("data-free") === "true") continue;
      var t = el.querySelector(".sqText");
      var have = norm(el.getAttribute("data-title") || (t ? t.textContent : el.textContent));   // data-title: the full title, when the shown one is tidied
      if (have && have === want) {
        var pos = parseInt(el.getAttribute("data-pos"), 10);
        return isNaN(pos) ? (i % 5) : (pos % 5);
      }
    }
    return -1;
  }
  function hash(str) {                                // small stable hash: the same decoy every time for the same card and song
    var h = 5381;
    for (var i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
    return h;
  }
  function light(grid, col) {
    if (!grid) return;
    var L = grid.querySelectorAll(".cardLetter");
    for (var i = 0; i < L.length; i++) L[i].classList.toggle("lit", i === col);
  }
  window.BingoHint = {
    norm: norm,
    columnFor: columnFor,
    // If the song is on this card its column lights up; if not, a random (but fixed for this card and song) column
    // does, so a lit letter only ever means "if this song is on your card, look in this column".
    show: function (grid, title, seed) {
      var col = columnFor(grid, title);
      if (col < 0 && norm(title)) col = hash(String(seed || "") + "|" + norm(title)) % 5;
      light(grid, col);
    },
    clear: function (grid) { light(grid, -1); }
  };
})();
