  var el = document.getElementById("qr");
  try { var q = qrcode(0, "M"); q.addData(el.dataset.qr); q.make(); el.innerHTML = q.createSvgTag({ scalable: true, margin: 2 }); } catch (_) { el.textContent = el.dataset.qr; }
