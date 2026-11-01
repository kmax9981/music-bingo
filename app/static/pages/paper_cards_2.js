  // Shrink each title until it fits its square (long titles, small squares), down to a readable minimum
  function fitAll(){
    document.querySelectorAll(".fit").forEach((el) => {
      const box = el.parentElement;
      const min = 11;          // px; about 8pt: the smallest a title may shrink to
      const comfortable = 16;  // px; about 12pt: below this, a bracketed part is dropped instead of shrinking the title further
      const maxLines = 3;      // a title with a bracketed part that needs more lines than this loses the bracketed part
      const tooBig = () => el.scrollHeight > box.clientHeight - 12 || el.scrollWidth > box.clientWidth - 12;
      const lines = () => {
        const cs = getComputedStyle(el);
        return Math.round(el.scrollHeight / (parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.12));
      };
      const shrink = (floor) => {
        el.style.fontSize = "";
        let size = parseFloat(getComputedStyle(el).fontSize);
        el.style.overflowWrap = "normal";
        while (size > floor && tooBig()) {
          size -= 1;
          el.style.fontSize = size + "px";
        }
      };
      const text = el.textContent;
      const withoutBrackets = text.replace(/\s*[\(\[][^\)\]]*[\)\]]\s*$/, "").trim();
      const hasBrackets = !!withoutBrackets && withoutBrackets !== text;
      el.style.fontSize = "";
      el.style.overflowWrap = "normal";
      // "Mambo No. 5 (a Little Bit of...)" takes four lines at the normal size: print just "Mambo No. 5"
      if (hasBrackets && lines() > maxLines) el.textContent = withoutBrackets;
      const kept = el.textContent === text;
      shrink(hasBrackets && kept ? comfortable : min);
      if (hasBrackets && kept && tooBig()) {
        // still doesn't fit at a comfortable size
        el.textContent = withoutBrackets;
        shrink(min);
      }
      // Still too wide at the smallest size: a single very long word may break across lines
      if (tooBig()) el.style.overflowWrap = "anywhere";
    });
  }
  window.fitPaperTitles = fitAll;
  window.addEventListener("load", fitAll);
  document.getElementById("printBtn").addEventListener("click", () => { fitAll(); window.print(); });
