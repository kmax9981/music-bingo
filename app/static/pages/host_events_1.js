// Options > Events: add, rename, change or remove the logo of, and delete the events used for paper cards.
// Logos are shrunk in the browser (max 600 px, PNG keeps transparency) like on the Create Game form.
(function () {
  var list = document.getElementById("eventList"), empty = document.getElementById("eventEmpty");
  var nameIn = document.getElementById("newEventName"), logoIn = document.getElementById("newEventLogo");
  var preview = document.getElementById("newEventPreview"), msg = document.getElementById("newEventMsg");
  if (!list || !nameIn) return;
  var newBlob = null;

  // data: URLs, not blob: ones: the site's security policy (img-src) only allows data: images
  function shrink(file, done, fail) {
    if (!/^image\/(png|jpeg)$/.test(file.type)) { fail("Choose a PNG or JPG image."); return; }
    if (file.size > 5 * 1024 * 1024) { fail("That image is over 5 MB. Choose a smaller one."); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, 600 / Math.max(img.width, img.height)), c = document.createElement("canvas");
        c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        var url = c.toDataURL("image/png");
        c.toBlob(function (b) { done(b, url, window.EventLogo ? window.EventLogo.advice(img.width, img.height) : ""); }, "image/png");
      };
      img.onerror = function () { fail("That image couldn't be read. Try another PNG or JPG."); };
      img.src = reader.result;
    };
    reader.onerror = function () { fail("That image couldn't be read. Try another PNG or JPG."); };
    reader.readAsDataURL(file);
  }
  function post(url, body) {
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function logoCell(v) {
    var t = document.createElement("div"); t.className = "eventThumb";
    if (v.logo_url) { var i = document.createElement("img"); i.src = v.logo_url + "?t=" + Date.now(); i.alt = (v.name || "Event") + " logo"; t.appendChild(i); }
    else { var s = document.createElement("span"); s.className = "muted small"; s.textContent = "No logo"; t.appendChild(s); }
    return t;
  }
  function button(cls, text) { var b = document.createElement("button"); b.type = "button"; b.className = "btn btnGhost " + cls; b.textContent = text; return b; }

  // build (or rebuild) one row from an event {id, name, logo_url}
  function renderRow(row, v) {
    row.innerHTML = ""; row.setAttribute("data-id", v.id);
    row.appendChild(logoCell(v));
    var inp = document.createElement("input"); inp.className = "input eventNameIn"; inp.value = v.name || ""; inp.maxLength = 80; inp.setAttribute("aria-label", "Event name");
    row.appendChild(inp);
    var btns = document.createElement("div"); btns.className = "eventBtns";
    btns.appendChild(button("eventRename", "Save name"));
    var lab = document.createElement("label"); lab.className = "btn btnGhost eventLogoBtn"; lab.textContent = v.logo_url ? "Change logo" : "Add logo";
    var f = document.createElement("input"); f.type = "file"; f.className = "eventLogoIn"; f.accept = "image/png,image/jpeg"; f.hidden = true; lab.appendChild(f);
    btns.appendChild(lab);
    if (v.logo_url) btns.appendChild(button("eventNoLogo", "Remove logo"));
    btns.appendChild(button("eventDel", "Delete"));
    row.appendChild(btns);
    var m = document.createElement("div"); m.className = "muted small eventRowMsg"; m.setAttribute("aria-live", "polite"); row.appendChild(m);
  }
  function rowMsg(row, t) { var m = row.querySelector(".eventRowMsg"); if (m) m.textContent = t; }

  logoIn.addEventListener("change", function () {
    newBlob = null; preview.hidden = true;
    var f = logoIn.files && logoIn.files[0];
    if (!f) return;
    shrink(f, function (blob, url, advice) { newBlob = blob; preview.src = url; preview.hidden = false; msg.textContent = (advice ? advice + " " : "") + "Click Save event."; }, function (t) { msg.textContent = t; });
  });
  document.getElementById("newEventSave").addEventListener("click", function () {
    var nm = (nameIn.value || "").trim();
    if (!nm) { msg.textContent = "Type the event name first. It is required (the logo is optional)."; nameIn.focus(); return; }
    var fd = new FormData(); fd.append("name", nm); if (newBlob) fd.append("logo", newBlob, "logo.png");
    msg.textContent = "Saving…";
    post("/host/events", fd).then(function (res) {
      if (!res.ok || !res.j.event) { msg.textContent = res.j.error || "Couldn't save the event."; return; }
      var row = document.createElement("div"); row.className = "eventRow"; renderRow(row, res.j.event);
      list.insertBefore(row, list.firstChild); if (empty) empty.hidden = true;
      nameIn.value = ""; logoIn.value = ""; newBlob = null; preview.hidden = true; msg.textContent = "Saved.";
    }).catch(function () { msg.textContent = "Couldn't save the event. Check your connection and try again."; });
  });

  list.addEventListener("click", function (e) {
    var row = e.target.closest ? e.target.closest(".eventRow") : null;
    if (!row) return;
    var id = row.getAttribute("data-id");
    if (e.target.classList.contains("eventRename")) {
      var fd = new FormData(); fd.append("name", row.querySelector(".eventNameIn").value);
      post("/host/events/" + encodeURIComponent(id) + "/rename", fd).then(function (res) { rowMsg(row, res.ok ? "Name saved." : (res.j.error || "Couldn't save the name.")); });
    } else if (e.target.classList.contains("eventNoLogo")) {
      var fd2 = new FormData(); fd2.append("remove", "1");
      post("/host/events/" + encodeURIComponent(id) + "/logo", fd2).then(function (res) {
        if (res.ok) { var typed = row.querySelector(".eventNameIn").value; res.j.event.name = typed || res.j.event.name; renderRow(row, res.j.event); rowMsg(row, "Logo removed."); }
        else rowMsg(row, res.j.error || "Couldn't remove the logo.");
      });
    } else if (e.target.classList.contains("eventDel")) {
      var nm = row.querySelector(".eventNameIn").value || "this event";
      if (!confirm("Delete the event “" + nm + "”? Games already made with it keep what they printed; new cards will show FREE.")) return;
      post("/host/events/" + encodeURIComponent(id) + "/delete", new FormData()).then(function (res) {
        if (res.ok) { row.remove(); if (empty && !list.querySelector(".eventRow")) empty.hidden = false; }
        else rowMsg(row, res.j.error || "Couldn't delete the event.");
      });
    }
  });
  list.addEventListener("change", function (e) {
    if (!(e.target.classList && e.target.classList.contains("eventLogoIn"))) return;
    var row = e.target.closest(".eventRow"), f = e.target.files && e.target.files[0];
    if (!row || !f) return;
    rowMsg(row, "Reading the image…");
    shrink(f, function (blob, url, advice) {
      var fd = new FormData(); fd.append("logo", blob, "logo.png");
      post("/host/events/" + encodeURIComponent(row.getAttribute("data-id")) + "/logo", fd).then(function (res) {
        if (res.ok) { var typed = row.querySelector(".eventNameIn").value; res.j.event.name = typed || res.j.event.name; renderRow(row, res.j.event); rowMsg(row, "Logo saved. " + (advice || "")); }
        else rowMsg(row, res.j.error || "Couldn't save the logo.");
      });
    }, function (t) { rowMsg(row, t); });
  });
})();
