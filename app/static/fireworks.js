// Fireworks behind the WINNER! overlay, shared by the hosted player card and Play Alone. Plain canvas, no
// libraries: rockets rise and burst into sparks with gravity and fading trails for ~10s, then the last
// sparks finish. Callers stop it when the overlay closes; skipped entirely when the player prefers
// reduced motion.  Usage: const fw = createBingoFireworks(canvasEl); fw.start(10000); fw.stop();
window.createBingoFireworks = function(canvas){
  // the theme's two accent colors, plus festive gold, pink, green and white that suit every theme
  const css = getComputedStyle(document.documentElement);
  const A2 = css.getPropertyValue("--accent2").trim() || "#a78bfa", A1 = css.getPropertyValue("--accent").trim() || "#8b5cf6";
  const COLORS = [A2, A1, A2, "#fbbf24", "#f472b6", "#34d399", "#ffffff"];
  const MAX_SPARKS = 900;
  let ctx = null, raf = 0, rockets = [], sparks = [], spawnUntil = 0, nextSpawn = 0, w = 0, h = 0, last = 0;

  function resize(){
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function launch(){
    const x = w * (0.15 + Math.random() * 0.7);
    rockets.push({ x, y: h + 4, vx: (Math.random() - 0.5) * 60, vy: -(h * (0.9 + Math.random() * 0.45)),
                   targetY: h * (0.15 + Math.random() * 0.35), color: COLORS[(Math.random() * COLORS.length) | 0] });
  }
  function burst(x, y, color){
    const n = Math.min(70 + ((Math.random() * 50) | 0), MAX_SPARKS - sparks.length);
    const speed = Math.min(w, h) * (0.35 + Math.random() * 0.25);
    const second = COLORS[(Math.random() * COLORS.length) | 0];
    for (let i = 0; i < n; i++){
      const a = (i / n) * Math.PI * 2 + Math.random() * 0.2, s = speed * (0.4 + Math.random() * 0.6);
      sparks.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 1, decay: 0.55 + Math.random() * 0.5,
                    color: Math.random() < 0.25 ? second : color, size: 1.2 + Math.random() * 1.6 });
    }
  }
  function frame(t){
    const dt = Math.min(0.05, (t - (last || t)) / 1000); last = t;
    // Fade previous frame toward transparent (leaves short trails, keeps the overlay backdrop visible)
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,0.22)";
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";

    if (t < spawnUntil && t >= nextSpawn){ launch(); if (Math.random() < 0.35) launch(); nextSpawn = t + 350 + Math.random() * 450; }

    for (let i = rockets.length - 1; i >= 0; i--){
      const r = rockets[i];
      const px = r.x, py = r.y;
      r.vy += h * 0.35 * dt; r.x += r.vx * dt; r.y += r.vy * dt;
      // streak from last position (dots per frame looked like a dotted line)
      ctx.strokeStyle = r.color; ctx.lineWidth = 2.2; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(r.x, r.y); ctx.stroke();
      if (r.y <= r.targetY || r.vy >= 0){ burst(r.x, r.y, r.color); rockets.splice(i, 1); }
    }
    const g = h * 0.28;
    for (let i = sparks.length - 1; i >= 0; i--){
      const s = sparks[i];
      s.vx *= (1 - 1.2 * dt); s.vy = s.vy * (1 - 1.2 * dt) + g * dt;
      s.x += s.vx * dt; s.y += s.vy * dt; s.life -= s.decay * dt;
      if (s.life <= 0){ sparks.splice(i, 1); continue; }
      ctx.globalAlpha = Math.max(0, s.life);
      ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (t < spawnUntil || rockets.length || sparks.length){ raf = requestAnimationFrame(frame); }
    else { stop(); }
  }
  function start(durationMs){
    if (!canvas || !canvas.getContext) return;
    try { if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; } catch(e){}
    ctx = ctx || canvas.getContext("2d");
    if (!ctx) return;
    stop();
    resize();
    window.addEventListener("resize", resize);
    const now = performance.now();
    spawnUntil = now + (durationMs || 10000); nextSpawn = now; last = 0;
    launch(); launch();
    raf = requestAnimationFrame(frame);
  }
  function stop(){
    try { cancelAnimationFrame(raf); } catch(e){}
    raf = 0; rockets = []; sparks = []; spawnUntil = 0;
    window.removeEventListener("resize", resize);
    try { if (ctx) ctx.clearRect(0, 0, w, h); } catch(e){}
  }
  return { start, stop, isRunning: () => !!raf };
};
