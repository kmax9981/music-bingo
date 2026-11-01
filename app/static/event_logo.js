// Advice about a chosen event logo, shown before it is saved: its size, and a gentle warning when it is very small
// or very wide/tall (the logo sits in a square about an inch across on a paper card). Never blocks saving.
(function () {
  window.EventLogo = {
    advice: function (w, h) {
      var size = w + " × " + h + " px.";
      if (Math.max(w, h) < 120) return size + " That is small, so it may look blurry on paper. Use a larger image (200 px or more) if you can.";
      var ratio = Math.max(w, h) / Math.max(1, Math.min(w, h));
      if (ratio > 2) return size + " That is quite " + (w > h ? "wide" : "tall") + ", so it will print small in the square center. A roughly square logo works best.";
      return size + " Looks good.";
    }
  };
})();
