  document.querySelectorAll("[data-qr]").forEach(function (el) {
    try { var q = qrcode(0, "M"); q.addData(el.dataset.qr); q.make(); el.innerHTML = q.createSvgTag({ scalable: true, margin: 0 }); } catch (_) {}
  });
