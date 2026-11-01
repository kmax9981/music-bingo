  const mode = document.getElementById("playlist_mode");
  const pasteBlock = document.getElementById("pasteBlock");
  const savedBlock = document.getElementById("savedBlock");
  function sync() {
    if (!mode) return;
    const v = mode.value;
    pasteBlock.style.display = (v === "paste") ? "block" : "none";
    savedBlock.style.display = (v === "saved") ? "block" : "none";
  }
  if (mode) mode.addEventListener("change", sync);
  sync();

  // paper options, and the event picker (events are set up under Options > Events)
  (function(){
    const toggle = document.getElementById("paperToggle"), opts = document.getElementById("paperOptions");
    const createBtn = document.getElementById("createBtn");
    const sel = document.getElementById("eventSelect"), picked = document.getElementById("eventPicked");
    const pickedLogo = document.getElementById("eventPickedLogo");
    if (toggle && opts && createBtn) {
      const syncPaper = () => {
        opts.style.display = toggle.checked ? "" : "none";
        createBtn.textContent = toggle.checked ? "Create Game and print cards" : "Create Game";
      };
      toggle.addEventListener("change", syncPaper);
      syncPaper();
    }
    if (sel && picked && pickedLogo) {
      const syncEvent = () => {
        const logo = sel.selectedOptions[0] ? sel.selectedOptions[0].dataset.logo : "";
        picked.style.display = (sel.value && logo) ? "" : "none";
        pickedLogo.style.display = logo ? "" : "none";
        if (logo) pickedLogo.src = logo;
      };
      sel.addEventListener("change", syncEvent);
      syncEvent();
    }
  })();
