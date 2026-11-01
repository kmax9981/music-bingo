// Choosing a theme previews it on this page straight away; nothing is saved until "Save theme" is pressed.
// "Custom" shows three color pickers: the server works out every other color from them (/theme/custom.json), and the
// page applies those values here, so the preview cards and the page itself show exactly what players will get.
(function () {
  var form = document.getElementById("themeForm");
  if (!form) return;
  var root = document.documentElement;
  var savedTheme = root.getAttribute("data-theme"), savedTone = root.getAttribute("data-tone");
  var editor = document.getElementById("customEditor");
  var previews = document.getElementById("customPreviews");
  var swatch = form.querySelector('.themeCard[data-theme="custom"]');
  var inputs = ["customBg", "customAccent", "customHighlight"].map(function (id) { return document.getElementById(id); });
  var applied = [];   // variable names currently set on the page element

  function colors() {
    return inputs.map(function (i) { return (i && i.value ? i.value : "#000000").replace("#", ""); }).join("-");
  }
  function setVars(el, vars) { Object.keys(vars).forEach(function (k) { el.style.setProperty(k, vars[k]); }); }
  function clearVars(el, names) { names.forEach(function (k) { el.style.removeProperty(k); }); }
  function customChosen() { var r = form.querySelector('input[name="theme"]:checked'); return !!r && r.value === "custom"; }

  var seq = 0, timer = null;
  function refresh() {
    if (!editor || !inputs[0]) return;
    var mine = ++seq;
    fetch("/theme/custom.json?c=" + encodeURIComponent(colors()), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || mine !== seq) return;
        if (previews) setVars(previews, d.vars);
        if (swatch) setVars(swatch, d.vars);
        if (customChosen()) {
          clearVars(root, applied);
          setVars(root, d.vars);
          applied = Object.keys(d.vars);
          root.setAttribute("data-tone", d.tone === "light" ? "light" : "dark");
          if (d.tone !== "light") root.removeAttribute("data-tone");
        }
      })
      .catch(function () {});
  }
  function later() { clearTimeout(timer); timer = setTimeout(refresh, 120); }

  function showTheme(value) {
    root.setAttribute("data-theme", value);
    clearVars(root, applied); applied = [];
    if (value === "custom") { if (editor) editor.hidden = false; refresh(); return; }
    if (editor) editor.hidden = true;
    if (value === "light") root.setAttribute("data-tone", "light"); else root.removeAttribute("data-tone");
  }

  form.addEventListener("change", function (e) {
    if (e.target && e.target.name === "theme") showTheme(e.target.value);
  });
  inputs.forEach(function (i) { if (i) { i.addEventListener("input", later); i.addEventListener("change", later); } });
  form.addEventListener("reset", function () {
    root.setAttribute("data-theme", savedTheme);
    clearVars(root, applied); applied = [];
    if (savedTone) root.setAttribute("data-tone", savedTone); else root.removeAttribute("data-tone");
  });
  if (editor) refresh();   // the swatch and the previews start in the current custom colors
})();
