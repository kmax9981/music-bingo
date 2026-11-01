/*
   Inject a user dropdown into any host topbar that has .topActions.
   Avoids editing every host template.
*/
(function(){
  function el(tag, attrs, children){
    const n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(k => {
        if (k === "class") n.className = attrs[k];
        else if (k === "text") n.textContent = attrs[k];
        else if (k.startsWith("on") && typeof attrs[k] === "function") n.addEventListener(k.slice(2), attrs[k]);
        else n.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(c => n.appendChild(c));
    return n;
  }

  function closeAll(){
    document.querySelectorAll(".userMenu.open").forEach(m => m.classList.remove("open"));
  }

  async function whoami(){
    try {
      const r = await fetch("/host/whoami", { credentials: "same-origin" });
      if (!r.ok) return null;
      return await r.json();
    } catch(e) {
      return null;
    }
  }

  function mount(menuData){
    const topActions = document.querySelector(".topbar .topActions");
    if (!topActions) return;

    if (document.getElementById("hostUserMenu")) return;

    // Hide existing logout form/button if present (we'll provide our own)
    try {
      topActions.querySelectorAll('form[action="/host/logout"]').forEach(f => { f.style.display = "none"; });
    } catch(_) {}

    const uname = (menuData && menuData.username) ? menuData.username : "Host";

    const btn = el("button", { type:"button", class:"userMenuBtn", id:"hostUserMenuBtn" }, [
      el("span", { class:"userMenuName", text: uname }),
      el("span", { class:"userMenuCaret", text: "▾" }),
    ]);

    // Account, Themes, Saved Games, Game History and Manage Playlists are the pages of Options (a menu down the left side of each)
    const optionsLink = el("a", { class:"userMenuItem", href:"/host/options" }, [
      el("span", { class:"userMenuItemIcon", text:"⚙️" }),
      el("span", { text:"Options" }),
    ]);

    const helpLink = el("a", { class:"userMenuItem", href:"/help" }, [
      el("span", { class:"userMenuItemIcon", text:"❓" }),
      el("span", { text:"Getting Started" }),
    ]);

    const adminLink = el("a", { class:"userMenuItem", href:"/host/admin/users" }, [
      el("span", { class:"userMenuItemIcon", text:"🛠️" }),
      el("span", { text:"Admin" }),
    ]);

    const homeLink = el("a", { class:"userMenuItem", href:"/home" }, [
      el("span", { class:"userMenuItemIcon", text:"🏠" }),
      el("span", { text:"Home" }),
    ]);

    // Back: go to previous page, then refresh once on arrival
    const backLink = el("a", { class:"userMenuItem", href:"#", id:"bingoBackNav" }, [
      el("span", { class:"userMenuItemIcon", text:"⬅️" }),
      el("span", { text:"Back" }),
    ]);
    backLink.addEventListener("click", function(ev){
      try { ev.preventDefault(); ev.stopPropagation(); } catch(_) {}
      try { sessionStorage.setItem("__bingo_back_refresh__", "1"); } catch(_) {}
      try { history.back(); } catch(_) {}
      closeAll();
    });

    // Refresh-on-arrival (once) after a history navigation
    try {
      if (!window.__bingoBackRefreshInstalled) {
        window.__bingoBackRefreshInstalled = true;
        window.addEventListener("pageshow", function(){
          try {
            const v = sessionStorage.getItem("__bingo_back_refresh__");
            if (v === "1") {
              sessionStorage.removeItem("__bingo_back_refresh__");
              location.reload();
            }
          } catch(_) {}
        });
      }
    } catch(_) {}


    const logoutLink = el("a", { class:"userMenuItem userMenuLogoutBtn", href:"/host/logout" }, [
      el("span", { class:"userMenuItemIcon", text:"🚪" }),
      el("span", { text:"Logout" }),
    ]);

    const menu = el("div", { class:"userMenuDropdown", id:"hostUserMenuDropdown" }, []);
    menu.appendChild(homeLink);
    menu.appendChild(backLink);
    menu.appendChild(optionsLink);
    menu.appendChild(helpLink);
    if (menuData && menuData.is_admin) menu.appendChild(adminLink);
    menu.appendChild(el("div", { class:"userMenuSep" }));
    menu.appendChild(logoutLink);

    const wrap = el("div", { class:"userMenu", id:"hostUserMenu" }, [btn, menu]);

    btn.addEventListener("click", function(ev){
      ev.preventDefault();
      ev.stopPropagation();
      const isOpen = wrap.classList.contains("open");
      closeAll();
      if (!isOpen) wrap.classList.add("open");
    });

    document.addEventListener("click", function(){ closeAll(); });

    topActions.appendChild(wrap);
  }

  document.addEventListener("DOMContentLoaded", async function(){
    try {
      const __p = (location.pathname || "");
      // Host pages, Play Alone, the help page, and the /home chooser (only shown when logged in, see whoami below)
      if (!__p || (__p !== "/home" && __p !== "/help" && !__p.startsWith("/host") && !__p.startsWith("/play"))) return;
      if (!document.querySelector(".topbar .topActions")) return;

      const data = await whoami();
      if (!data || !data.authed) return;

      mount(data);
    } catch(_) {}
  });
})();
