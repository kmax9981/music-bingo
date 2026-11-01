// type a paper card's code -> its card with played squares lit and the verdict;
// tap the squares the player marked to show which haven't played; Accept/Reject records a claim.
window.__bingoPaperCount = window.BINGO_HOST.paperCount;
(function(){
  const form = document.getElementById("paperCheckForm");
  if (!form) return;
  const CODE = window.BINGO_HOST.code;
  const $ = (id) => document.getElementById(id);
  const modal = $("paperModal"), grid = $("pmGrid"), verdict = $("pmVerdict"), msg = $("pmMsg"), formMsg = $("paperCheckMsg");
  let card = null, marked = new Set();

  function esc(t){ const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
  function names(list){
    const q = list.map(t => "\u201c" + t + "\u201d");
    return q.length <= 1 ? q.join("") : q.slice(0, -1).join(", ") + " and " + q[q.length - 1];
  }
  function render(){
    const inLine = new Set((card.valid_lines[0] || {}).positions || []);
    grid.innerHTML = "";
    card.squares.forEach((sq) => {
      const d = document.createElement("div");
      d.className = "pmSq" + (sq.free ? " free played" : (sq.played ? " played" : "")) + (inLine.has(sq.pos) ? " inLine" : "");
      if (marked.has(sq.pos)) d.classList.add(sq.played ? "marked" : "wrong");
      d.innerHTML = sq.free ? "FREE" : esc(sq.title);
      if (!sq.free) d.addEventListener("click", () => { marked.has(sq.pos) ? marked.delete(sq.pos) : marked.add(sq.pos); render(); });
      grid.appendChild(d);
    });
    const wrong = card.squares.filter(sq => marked.has(sq.pos) && !sq.played).map(sq => sq.title);
    if (!marked.size) msg.textContent = "";
    else if (wrong.length) msg.textContent = names(wrong) + (wrong.length === 1 ? " hasn't" : " haven't") + " played yet.";
    else msg.textContent = "Every square they marked has played.";
  }
  function show(c){
    card = c; marked = new Set();
    $("pmTitle").textContent = "Card " + c.card_number + " \u00b7 " + c.code;
    if (c.valid_lines.length) {
      verdict.className = "pmVerdict good";
      verdict.textContent = "Valid bingo: " + c.valid_lines.map(l => l.name).join(", ") + "." + (c.already_won ? " (This card has already won this round.)" : "");
    } else {
      verdict.className = "pmVerdict bad";
      const cl = c.closest;
      verdict.textContent = "No bingo yet." + (cl ? " Closest: " + cl.name + ", missing " + names(cl.missing) + "." : "");
    }
    render();
    modal.style.display = "";
    $("pmAccept").focus();
  }
  function hide(){ modal.style.display = "none"; card = null; }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const code = ($("paperCode").value || "").trim();
    if (!code) return;
    formMsg.textContent = "Checking…";
    try {
      const r = await fetch(`/host/game/${CODE}/paper/check?card=` + encodeURIComponent(code), { credentials: "same-origin", cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) { formMsg.textContent = j.error || "Couldn't check that card."; return; }
      formMsg.textContent = "";
      show(j);
    } catch (_) { formMsg.textContent = "Couldn't check that card. Check your connection."; }
  });

  async function decide(status){
    if (!card) return;
    msg.textContent = "Saving…";
    try {
      const r = await fetch(`/host/game/${CODE}/paper/claim`, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ card: card.code, status }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) { msg.textContent = j.error || "Couldn't save that."; return; }
      const label = "Card " + card.card_number;
      hide();
      if (status === "accepted") { const bar = document.getElementById("bingoDecisionBar"); if (bar) bar.classList.remove("hidden"); }
      $("paperCode").value = "";
      formMsg.textContent = label + (status === "accepted" ? " accepted" : " rejected") + ". It's in the claims list.";
    } catch (_) { msg.textContent = "Couldn't save that. Check your connection."; }
  }
  $("pmAccept").addEventListener("click", () => decide("accepted"));
  $("pmReject").addEventListener("click", () => decide("rejected"));
  $("pmClose").addEventListener("click", hide);
  modal.addEventListener("click", (ev) => { if (ev.target === modal) hide(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && card) hide(); });
})();
