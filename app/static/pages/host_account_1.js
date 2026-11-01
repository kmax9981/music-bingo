  (function(){
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has('ok') || u.searchParams.has('error')) {
        u.searchParams.delete('ok');
        u.searchParams.delete('error');
        const qs = u.searchParams.toString();
        const clean = u.pathname + (qs ? ('?' + qs) : '') + u.hash;
        window.history.replaceState({}, '', clean);
      }
    } catch(_) {}
  })();
