/* bingo: force game code uppercase */
document.addEventListener("DOMContentLoaded", () => {
  const el = document.querySelector('input[name="code"], input#code');
  if (!el) return;
  el.addEventListener("input", () => {
    el.value = (el.value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  });
});
