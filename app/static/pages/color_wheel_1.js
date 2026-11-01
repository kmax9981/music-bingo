// Color wheel for the Custom theme: round = hue, distance from the middle = strength, slider = brightness.
// It edits one of three hidden inputs (#customBg, #customAccent, #customHighlight) and fires an "input" event on
// that input, which is what makes the preview (host_account_theme_1.js) update. Typing a code or setting an input's
// value from elsewhere (and firing "input") moves the wheel too.
(function () {
  var canvas = document.getElementById("wheelCanvas");
  var vInput = document.getElementById("wheelV"), hexInput = document.getElementById("wheelHex");
  var picks = Array.prototype.slice.call(document.querySelectorAll("#customPickers .customPick"));
  if (!canvas || !vInput || !hexInput || !picks.length) return;

  var ctx = canvas.getContext("2d");
  var W = canvas.width, R = W / 2 - 3;
  var target = picks[0];
  var hsv = { h: 0, s: 0, v: 1 };
  var syncing = false;

  function hsvToRgb(h, s, v) {
    var c = v * s, hp = (h % 360) / 60, x = c * (1 - Math.abs(hp % 2 - 1)), m = v - c, r = 0, g = 0, b = 0;
    if (hp < 1) { r = c; g = x; } else if (hp < 2) { r = x; g = c; } else if (hp < 3) { g = c; b = x; }
    else if (hp < 4) { g = x; b = c; } else if (hp < 5) { r = x; b = c; } else { r = c; b = x; }
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
  }
  function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn, h = 0;
    if (d) {
      if (mx === r) h = ((g - b) / d) % 6; else if (mx === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    return { h: h, s: mx ? d / mx : 0, v: mx };
  }
  function toHex(rgb) { return "#" + rgb.map(function (n) { return ("0" + n.toString(16)).slice(-2); }).join(""); }
  function parseHex(t) {
    var m = /^#?([0-9a-f]{6})$/i.exec((t || "").trim());
    return m ? [0, 2, 4].map(function (i) { return parseInt(m[1].substr(i, 2), 16); }) : null;
  }
  function targetInput() { return document.getElementById(target.getAttribute("data-target")); }

  function drawWheel() {
    var img = ctx.createImageData(W, W), d = img.data;
    for (var y = 0; y < W; y++) {
      for (var x = 0; x < W; x++) {
        var dx = x + 0.5 - W / 2, dy = y + 0.5 - W / 2, r = Math.sqrt(dx * dx + dy * dy), i = (y * W + x) * 4;
        if (r > R) { d[i + 3] = 0; continue; }
        var h = Math.atan2(dy, dx) * 180 / Math.PI; if (h < 0) h += 360;
        var c = hsvToRgb(h, Math.min(1, r / R), hsv.v);
        d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    var a = hsv.h * Math.PI / 180, px = W / 2 + Math.cos(a) * hsv.s * R, py = W / 2 + Math.sin(a) * hsv.s * R;
    ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 2); ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; ctx.stroke();
    ctx.beginPath(); ctx.arc(px, py, 10.5, 0, Math.PI * 2); ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(0,0,0,0.6)"; ctx.stroke();
  }

  function paintSwatches() {
    picks.forEach(function (p) {
      var sw = p.querySelector(".customSwatch"), inp = document.getElementById(p.getAttribute("data-target"));
      if (sw && inp) sw.style.background = inp.value;
    });
  }
  function showCurrent() {
    var hex = toHex(hsvToRgb(hsv.h, hsv.s, hsv.v));
    hexInput.value = hex; vInput.value = Math.round(hsv.v * 100);
    drawWheel();
    return hex;
  }
  // push the wheel's color into the chosen input
  function commit() {
    var hex = showCurrent(), inp = targetInput();
    if (!inp || inp.value === hex) { paintSwatches(); return; }
    inp.value = hex; paintSwatches();
    syncing = true; inp.dispatchEvent(new Event("input", { bubbles: true })); syncing = false;
  }
  // load the chosen input's color into the wheel
  function load() {
    var inp = targetInput(), rgb = parseHex(inp && inp.value);
    if (rgb) { var keepH = hsv.h; hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]); if (!hsv.s) hsv.h = keepH; }
    showCurrent(); paintSwatches();
  }

  function select(p) {
    target = p;
    picks.forEach(function (q) { var on = q === p; q.classList.toggle("active", on); q.setAttribute("aria-pressed", on ? "true" : "false"); });
    var label = document.getElementById("wheelEditing"), name = p.querySelector("b");
    if (label && name) label.textContent = name.textContent;
    load();
  }
  picks.forEach(function (p) { p.addEventListener("click", function () { select(p); }); });

  function fromPointer(e) {
    var box = canvas.getBoundingClientRect(), k = W / box.width;
    var dx = (e.clientX - box.left) * k - W / 2, dy = (e.clientY - box.top) * k - W / 2;
    var h = Math.atan2(dy, dx) * 180 / Math.PI; if (h < 0) h += 360;
    hsv.h = h; hsv.s = Math.min(1, Math.sqrt(dx * dx + dy * dy) / R);
    commit();
  }
  var dragging = false;
  canvas.addEventListener("pointerdown", function (e) { dragging = true; try { canvas.setPointerCapture(e.pointerId); } catch (_) {} fromPointer(e); e.preventDefault(); });
  canvas.addEventListener("pointermove", function (e) { if (dragging) fromPointer(e); });
  canvas.addEventListener("pointerup", function () { dragging = false; });
  canvas.addEventListener("pointercancel", function () { dragging = false; });
  canvas.addEventListener("keydown", function (e) {
    var step = e.shiftKey ? 10 : 3, used = true;
    if (e.key === "ArrowLeft") hsv.h = (hsv.h - step + 360) % 360;
    else if (e.key === "ArrowRight") hsv.h = (hsv.h + step) % 360;
    else if (e.key === "ArrowUp") hsv.s = Math.min(1, hsv.s + step / 100);
    else if (e.key === "ArrowDown") hsv.s = Math.max(0, hsv.s - step / 100);
    else used = false;
    if (used) { e.preventDefault(); commit(); }
  });

  vInput.addEventListener("input", function () { hsv.v = (parseInt(vInput.value, 10) || 0) / 100; commit(); });
  hexInput.addEventListener("input", function () {
    var rgb = parseHex(hexInput.value);
    if (!rgb) return;
    var keepH = hsv.h; hsv = rgbToHsv(rgb[0], rgb[1], rgb[2]); if (!hsv.s) hsv.h = keepH;
    var inp = targetInput(), hex = toHex(rgb);
    drawWheel(); vInput.value = Math.round(hsv.v * 100);
    if (inp && inp.value !== hex) { inp.value = hex; paintSwatches(); syncing = true; inp.dispatchEvent(new Event("input", { bubbles: true })); syncing = false; }
  });

  // a value set from elsewhere (and an "input" event fired on the hidden input) moves the wheel and the swatch
  picks.forEach(function (p) {
    var inp = document.getElementById(p.getAttribute("data-target"));
    if (inp) inp.addEventListener("input", function () { if (syncing) return; paintSwatches(); if (p === target) load(); });
  });

  select(picks[0]);
})();
