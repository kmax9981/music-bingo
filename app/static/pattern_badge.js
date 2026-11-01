// Keeps every win-pattern badge on the page in step with the host's choice: {key, label, squares}.
(function () {
  window.PatternBadge = {
    update: function (info) {
      document.querySelectorAll(".patternBadge").forEach(function (el) {
        el.setAttribute("data-pattern", info.key);
        var name = el.querySelector(".patternName"); if (name) name.textContent = info.label;
        var rn = el.querySelector(".roundNo"); if (rn && info.round) rn.textContent = info.round;
        var rp = el.querySelector(".roundPart"); if (rp && info.round) rp.hidden = info.round <= 1;
        el.querySelectorAll(".patternMini i").forEach(function (c, i) { c.classList.toggle("on", info.squares.indexOf(i) !== -1); });
      });
      document.querySelectorAll("select.patternSelect").forEach(function (s) { if (s.value !== info.key) s.value = info.key; });
      document.dispatchEvent(new CustomEvent("pattern:update", { detail: info }));
    }
  };
})();
