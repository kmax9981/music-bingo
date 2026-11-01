  // Make the form action dynamic based on user input
  const form = document.querySelector('form');
  const codeInput = document.querySelector('input[name="code"]');

  if (form && codeInput) {
    codeInput.addEventListener('input', () => {
      const code = codeInput.value.trim();
      form.action = `/game/${code}/join`;
    });
  }
