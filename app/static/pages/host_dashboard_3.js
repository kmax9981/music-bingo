/*
   If we arrived at /host?error=... via redirect, clean the address bar after render.
*/
(function(){
  try {
    const u = new URL(window.location.href);
    if (u.pathname === '/host' && u.searchParams.has('error')) {
      u.searchParams.delete('error');
      const qs = u.searchParams.toString();
      const clean = u.pathname + (qs ? ('?' + qs) : '') + u.hash;
      window.history.replaceState({}, '', clean);
    }
  } catch(e) {}
})();
