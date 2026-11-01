/*
   Live check on playlist link fields (inputs with data-playlist-input): as soon as the pasted link is a
   playlist made by Spotify (IDs start with 37i9dQZF1, same rule as _spotify_made_error() in main.py),
   show the reason under the field and disable the form's submit button. The server checks again on
   submit, and also catches spotify.link short links, whose playlist ID isn't visible here.

   Also: "Hide playlists with explicit songs" checkboxes (data-hide-explicit="<selector>") hide the flagged ones.
*/
(function(){
  const SPOTIFY_MADE_PREFIX = "37i9dQZF1";
  const MESSAGE = "That's a playlist made by Spotify, and Spotify doesn't let apps use those. To use it, " +
                  "open it in Spotify, choose ⋯ → Add to other playlist → New playlist, then paste the link to your copy.";

  function playlistId(value){
    const v = String(value || "").trim();
    if (/^[A-Za-z0-9]{22}$/.test(v)) return v;
    const m = v.match(/playlist[/:]([A-Za-z0-9]{22})/);
    return m ? m[1] : "";
  }

  function attach(input){
    const form = input.form;
    const submit = form ? form.querySelector('button[type="submit"], button:not([type])') : null;
    const note = document.createElement("div");
    note.className = "alert alertWarn playlistCheckNote";
    note.setAttribute("role", "alert");
    note.style.display = "none";  // not the hidden attribute: .alert's display rule overrides it
    note.textContent = MESSAGE;
    input.insertAdjacentElement("afterend", note);

    function check(){
      // A hidden field (e.g. "Use saved playlist" chosen) doesn't block the form
      const visible = input.offsetParent !== null;
      const bad = visible && playlistId(input.value).startsWith(SPOTIFY_MADE_PREFIX);
      note.style.display = bad ? "" : "none";
      input.setAttribute("aria-invalid", bad ? "true" : "false");
      if (submit) submit.disabled = bad;
    }
    ["input", "change", "paste"].forEach((ev) => input.addEventListener(ev, () => setTimeout(check, 0)));
    if (form) form.addEventListener("change", () => setTimeout(check, 0));  // e.g. switching playlist source
    check();
  }

  // "Hide playlists with explicit songs": hides the options (or rows) marked data-explicit="1"
  function attachHideExplicit(box){
    const KEY = "hideExplicitPlaylists";
    function apply(){
      document.querySelectorAll(box.dataset.hideExplicit).forEach((el) => {
        if (el.tagName === "SELECT") {
          Array.from(el.options).forEach((o) => {
            const flagged = o.dataset.explicit === "1" && box.checked;
            o.hidden = flagged; o.disabled = flagged;
          });
          if (el.selectedOptions[0] && el.selectedOptions[0].disabled) el.value = "";
        } else if (el.dataset.explicit === "1") {
          el.style.display = box.checked ? "none" : "";
        }
      });
    }
    try { box.checked = localStorage.getItem(KEY) === "1"; } catch (_) {}
    box.addEventListener("change", () => { try { localStorage.setItem(KEY, box.checked ? "1" : "0"); } catch (_) {} apply(); });
    apply();
  }

  // "Sort by": reorders the rows (or the menu options) using their data-name / data-songs / data-explicit-count /
  // data-order attributes; the choice is remembered in the browser
  function attachSort(sel){
    const KEY = "playlistSort";
    const key = {
      new: (e) => Number(e.dataset.order || 0),
      name: (e) => e.dataset.name || "",
      name_desc: (e) => e.dataset.name || "",
      songs: (e) => Number(e.dataset.songs || 0),
      songs_desc: (e) => Number(e.dataset.songs || 0),
      explicit_desc: (e) => Number(e.dataset.explicitCount || 0),
    };
    function apply(){
      const how = sel.value, k = key[how] || key.new, desc = how.endsWith("_desc");
      const cmp = (a, b) => {
        const x = k(a), y = k(b);
        const r = (typeof x === "string") ? x.localeCompare(y) : x - y;
        return (desc ? -r : r) || (Number(a.dataset.order || 0) - Number(b.dataset.order || 0));
      };
      document.querySelectorAll(sel.dataset.playlistSort).forEach((el) => {
        if (el.tagName === "SELECT") {
          const opts = Array.from(el.options).filter((o) => o.value !== "").sort(cmp);
          const chosen = el.value;
          opts.forEach((o) => el.appendChild(o));
          el.value = chosen;
        }
      });
      const rows = Array.from(document.querySelectorAll(sel.dataset.playlistSort)).filter((el) => el.tagName !== "SELECT");
      if (rows.length) {
        const parent = rows[0].parentElement;
        rows.sort(cmp).forEach((r) => parent.appendChild(r));
      }
    }
    try { const saved = localStorage.getItem(KEY); if (saved && key[saved]) sel.value = saved; } catch (_) {}
    sel.addEventListener("change", () => { try { localStorage.setItem(KEY, sel.value); } catch (_) {} apply(); });
    apply();
  }

  function init(){
    document.querySelectorAll("select[data-playlist-sort]").forEach(attachSort);
    document.querySelectorAll("input[data-playlist-input]").forEach(attach);
    document.querySelectorAll("input[data-hide-explicit]").forEach(attachHideExplicit);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
