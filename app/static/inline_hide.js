/* Elements marked data-hide start hidden through CSS, then get display:none set from here so that page scripts can
   show them again with el.style.display (as they did when this was an inline style="display:none" attribute). */
document.querySelectorAll('[data-hide]').forEach(function (el) { el.style.display = 'none'; el.removeAttribute('data-hide'); });
