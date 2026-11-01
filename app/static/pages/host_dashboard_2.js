  (function(){
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has('error')) {
        u.searchParams.delete('error');
        const cleaned = u.pathname + (u.searchParams.toString() ? ('?' + u.searchParams.toString()) : '') + u.hash;
        window.history.replaceState({}, '', cleaned);
      }
    } catch(_) {}
  })();
