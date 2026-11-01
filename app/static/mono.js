// A player's own "Display" choice: Color (the host's theme), White on black, or Black on white. Kept on this device only
// (localStorage) and applied before the page is drawn, so it does not flash in color. Only the player pages load this.
(function () {
  var KEY = "bingo_display", html = document.documentElement, tone = html.getAttribute("data-tone");
  function stored() {
    try {
      var v = localStorage.getItem(KEY);
      if (v === "dark" || v === "light" || v === "color") return v;
      if (localStorage.getItem("bingo_mono") === "1") return "dark";
    } catch (e) {}
    return "color";
  }
  function apply(mode) {
    html.classList.toggle("mono", mode !== "color");
    html.classList.toggle("mono-dark", mode === "dark");
    html.classList.toggle("mono-light", mode === "light");
    if (mode === "light") html.setAttribute("data-tone", "light");        // the light-page status colors
    else if (mode === "dark" || tone === null) html.removeAttribute("data-tone");
    else html.setAttribute("data-tone", tone);
  }
  apply(stored());
  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.getElementById("displaySelect");
    if (!sel) return;
    sel.value = stored();
    sel.addEventListener("change", function () {
      try { localStorage.setItem(KEY, sel.value); } catch (e) {}
      apply(sel.value);
    });
  });
})();
