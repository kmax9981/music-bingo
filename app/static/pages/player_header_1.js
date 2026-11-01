// On an upright phone the header's left column has no room for the Hints switch, so it moves up into the centred strip
// (beside the win pattern); on wider screens it goes back beside the player's name.
(function () {
  var wrap = document.getElementById("hintToggleWrap"), strip = document.querySelector(".patternStrip"), home = wrap && wrap.parentNode, next = wrap && wrap.nextSibling;
  if (!wrap || !strip || !window.matchMedia) return;
  var mq = window.matchMedia("(max-width: 980px) and (orientation: portrait)");
  function place() { if (mq.matches) strip.appendChild(wrap); else home.insertBefore(wrap, next); }
  place();
  if (mq.addEventListener) mq.addEventListener("change", place);
})();
