/* CSRF: send the token (from <meta name="csrf-token">) with every same-site state-changing fetch(), and put it in every
   POST form. Forms can be added after the page loads, so the token goes in at submit time. */
(function () {
  var m = document.querySelector('meta[name="csrf-token"]'), tok = m ? m.content : "";
  if (!tok) return;
  var realFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      if (typeof input === "string" || input instanceof URL) {
        var url = new URL(String(input), location.href);
        var method = String((init && init.method) || "GET").toUpperCase();
        if (url.origin === location.origin && ["GET", "HEAD", "OPTIONS"].indexOf(method) < 0) {
          init = init || {};
          var h = new Headers(init.headers || {});
          if (!h.has("X-CSRF-Token")) h.set("X-CSRF-Token", tok);
          init.headers = h;
        }
      }
    } catch (e) {}
    return realFetch.call(this, input, init);
  };
  function addToken(f) {
    if (!f || (f.getAttribute("method") || "get").toLowerCase() !== "post" || f.querySelector('input[name="csrf_token"]')) return;
    var i = document.createElement("input"); i.type = "hidden"; i.name = "csrf_token"; i.value = tok; f.appendChild(i);
  }
  document.addEventListener("submit", function (e) { addToken(e.target); }, true);
  var realSubmit = HTMLFormElement.prototype.submit;   // form.submit() doesn't fire a submit event
  HTMLFormElement.prototype.submit = function () { addToken(this); return realSubmit.call(this); };
})();
