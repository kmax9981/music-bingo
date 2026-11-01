(function(){
  const codeInput = document.getElementById('code');
  if (codeInput) {
    codeInput.addEventListener('input', () => { codeInput.value = (codeInput.value || '').toUpperCase(); });
  }
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', () => {
      if (codeInput) codeInput.value = (codeInput.value || '').toUpperCase();
    });
  }
})();
