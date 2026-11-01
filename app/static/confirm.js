/* Forms with data-confirm="message" ask before they submit (replaces inline onsubmit handlers). */
document.addEventListener('submit', function (e) {
  var msg = e.target && e.target.getAttribute && e.target.getAttribute('data-confirm');
  if (msg && !window.confirm(msg)) e.preventDefault();
}, true);
