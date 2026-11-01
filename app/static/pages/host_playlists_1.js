  // Public switches: show Public/Private next to each, and save as soon as one is flipped
  document.querySelectorAll(".plVisForm").forEach((form) => {
    const box = form.querySelector('input[name="is_public"]');
    const text = form.querySelector(".plSwitchText");
    const sync = () => { if (text) text.textContent = box.checked ? "Public" : "Private"; };
    sync();
    box.addEventListener("change", () => { sync(); form.submit(); });
  });
  // Clean copies run in the background. Progress is a small line on the playlist's own row; when one finishes the
  // new playlist just appears in the list. Only a problem is shown (a short red line on the row).
  (function(){
    const box = document.getElementById("cleanJobs");
    const csrf = (document.querySelector('input[name="csrf_token"]') || {}).value || "";
    const esc = (v) => { const d = document.createElement("div"); d.textContent = String(v == null ? "" : v); return d.innerHTML; };
    let wasRunning = new Set(), timer = null;
    function dismiss(id){
      const body = new URLSearchParams({ job_id: id, csrf_token: csrf });
      return fetch("/host/playlist/clean_jobs/dismiss", { method: "POST", credentials: "same-origin", body }).catch(() => null);
    }
    function reconnectLink(j){ return j.reconnect ? ' <a class="link" href="/host/spotify/connect?next=/host/playlist">Reconnect Spotify</a>' : ""; }
    function show(jobs){
      document.querySelectorAll(".plJobStatus").forEach((el) => { el.hidden = true; el.innerHTML = ""; });
      document.querySelectorAll(".plCleanForm").forEach((f) => { f.hidden = false; });
      let orphan = "";
      jobs.forEach((j) => {
        const row = document.querySelector('.listRow[data-pl-id="' + j.playlist_id + '"]');
        const slot = row && row.querySelector(".plJobStatus");
        let html = "";
        if (j.state === "running") {
          const prog = j.total ? " " + Math.min(j.done + 1, j.total) + "/" + j.total : "";
          html = '<span class="plJobRunning">⏳ Making clean copy…' + prog + '</span>';
          const f = row && row.querySelector(".plCleanForm"); if (f) f.hidden = true;
        } else if (j.state === "error") {
          html = '<span class="plJobError">' + esc(j.error) + '</span>' + reconnectLink(j) + ' <button type="button" class="link plLinkBtn" data-dismiss="' + esc(j.id) + '">Dismiss</button>';
        }
        if (!html) return;
        if (slot) { slot.hidden = false; slot.innerHTML += html; }
        else if (box) { orphan += '<div class="small cleanJobLine">' + html + '</div>'; }
      });
      if (box) box.innerHTML = orphan;
    }
    async function poll(){
      let data = null;
      try { const r = await fetch("/host/playlist/clean_jobs", { credentials: "same-origin", cache: "no-store" }); data = await r.json(); } catch (_) {}
      timer = null;
      if (!data || !data.jobs) return;
      const finished = data.jobs.filter((j) => j.state === "done");
      const justFinished = finished.some((j) => wasRunning.has(j.id));
      if (finished.length) await Promise.all(finished.map((j) => dismiss(j.id)));    // nothing to announce: the row appears
      if (justFinished) { location.reload(); return; }
      wasRunning = new Set(data.jobs.filter((j) => j.state === "running").map((j) => j.id));
      show(data.jobs);
      if (wasRunning.size) timer = setTimeout(poll, 1500);
    }
    document.addEventListener("click", async (ev) => {
      const id = ev.target && ev.target.dataset && ev.target.dataset.dismiss;
      if (!id) return;
      await dismiss(id);
      poll();
    });
    poll();
  })();
  // Rename: swap the name for an edit box on the same row
  document.querySelectorAll(".plRenameBtn").forEach((btn) => {
    const row = btn.closest(".listRow");
    const form = row.querySelector(".plRenameForm");
    btn.addEventListener("click", () => { form.hidden = false; form.querySelector("input[name=name]").focus(); });
    row.querySelector(".plRenameCancel").addEventListener("click", () => { form.hidden = true; });
  });
  // "Show which songs": list the explicit titles under the playlist
  document.querySelectorAll(".plShowExplicit").forEach((a) => {
    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const box = a.closest(".plMain").querySelector(".plExplicitList");
      if (!box.hidden) { box.hidden = true; return; }
      box.hidden = false; box.textContent = "Loading…";
      try {
        const r = await fetch("/host/playlist/explicit?id=" + encodeURIComponent(a.dataset.id), { credentials: "same-origin" });
        const j = await r.json();
        box.textContent = (j && j.ok) ? ("Explicit songs: " + (j.titles.length ? j.titles.join(", ") : "none")) : "Couldn't read the playlist right now.";
      } catch (_) { box.textContent = "Couldn't read the playlist right now."; }
    });
  });
