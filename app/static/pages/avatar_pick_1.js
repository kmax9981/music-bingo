// The join page's picture picker: the preview shows the chosen animal and color beside the name being typed.
(function () {
  var COLORS = ["purple", "orange", "blue", "green", "pink", "yellow", "red", "teal", "indigo", "lime", "brown", "slate"];
  var preview = document.getElementById("previewAvatar"), nameOut = document.getElementById("previewName"), nameIn = document.getElementById("f_name");
  if (!preview) return;
  function sync() {
    var a = document.querySelector("input[name=avatar]:checked"), c = document.querySelector("input[name=avatar_color]:checked");
    if (a) preview.textContent = a.nextElementSibling.textContent;
    var color = c ? c.value : "purple";
    COLORS.forEach(function (k) { preview.classList.toggle("avc-" + k, k === color); });
    document.querySelectorAll("#avatarGrid .avatar").forEach(function (e) { COLORS.forEach(function (k) { e.classList.toggle("avc-" + k, k === color); }); });
    nameOut.textContent = (nameIn && nameIn.value.trim()) || "Your name";
  }
  document.querySelectorAll("input[name=avatar], input[name=avatar_color]").forEach(function (i) { i.addEventListener("change", sync); });
  if (nameIn) nameIn.addEventListener("input", sync);
})();
