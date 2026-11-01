// Keeps the Spotify redirect address under the public address box in step with what is typed.
(function () {
  var url = document.getElementById("setupPublicUrl"), out = document.getElementById("setupRedirect");
  if (!url || !out) return;
  var over = document.getElementById("setupRedirectIn");
  function sync() {
    var o = over ? (over.value || "").trim() : "";
    var shown = o || (url.value || "").trim().replace(/\/+$/, "") + "/auth/spotify/callback";
    out.textContent = shown;
    var step = document.querySelector(".spotifyStepRedirect");
    if (step) step.textContent = shown;
  }
  url.addEventListener("input", sync);
  if (over) over.addEventListener("input", sync);
  sync();
})();
