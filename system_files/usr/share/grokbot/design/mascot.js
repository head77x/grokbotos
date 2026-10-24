// Bit, the Grok Bot OS character (same geometry as grokbot_mascot.py).
// A rounded-square head with two pill eyes; expressions are code:
// idle (blink, look around), thinking, listening, happy, alert, error,
// sleeping, sad. Usage: const m = GBMascot.create("idle"); el.append(m);
// m.setMood("happy"). DOM nodes and attributes only (CSP-safe).
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const MOODS = ["idle", "thinking", "listening", "happy", "alert", "error", "sleeping", "sad"];
  const COATS = { idle: "#4c8dff", thinking: "#8b6cf6", listening: "#3fc2a6", happy: "#3fc2a6",
    alert: "#f2b33d", error: "#ff6b5e", sleeping: "#6b7280", sad: "#8b9bb4" };
  const HEAD = [8, 10, 84, 80, 30], EYE_Y = 44, EYE_DX = 17, EYE_W = 11, EYE_H = 22;
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function face(mood, blink, look, t) {
    if (MOODS.indexOf(mood) < 0) mood = "idle";
    const lx = Math.max(-1, Math.min(1, look[0])), ly = Math.max(-1, Math.min(1, look[1]));
    const bob = reduce ? 0 : Math.sin(t * 2 * Math.PI / 3.2) * 1.2;
    const head = [HEAD[0], HEAD[1] + bob, HEAD[2], HEAD[3], HEAD[4]];
    let cx = 50 + lx * 7, cy = EYE_Y + ly * 5 + bob, ew = EYE_W, eh = EYE_H, mouth = null;
    if (mood === "thinking") { cy -= 6; cx += 5; eh *= 0.8; mouth = ["line", 44, 72 + bob, 54, 71 + bob]; }
    else if (mood === "listening") { ew *= 1.15; eh *= 1.12; mouth = ["o", 50, 72 + bob, 3.5 + 1.2 * Math.abs(Math.sin(t * 4))]; }
    else if (mood === "alert") { ew *= 1.2; eh *= 1.15; mouth = ["o", 50, 73 + bob, 3]; }
    else if (mood === "sad") { cy += 4; eh *= 0.75; mouth = ["arc", 50, 76 + bob, 14, -4]; }
    else if (mood === "sleeping") { blink = 1; cy += 4; }
    else if (mood === "happy") { mouth = ["arc", 50, 68 + bob, 18, 6]; }
    let eyes;
    if (mood === "happy") eyes = [["arc", cx - EYE_DX, cy, 14, -7], ["arc", cx + EYE_DX, cy, 14, -7]];
    else if (mood === "error") { eyes = [["x", cx - EYE_DX, cy, 9], ["x", cx + EYE_DX, cy, 9]]; mouth = ["line", 42, 73 + bob, 58, 73 + bob]; }
    else {
      const bh = Math.max(2.5, eh * (1 - Math.max(0, Math.min(1, blink))));
      eyes = [["pill", cx - EYE_DX, cy, ew, bh], ["pill", cx + EYE_DX, cy, ew, bh]];
    }
    return { mood: mood, head: head, eyes: eyes, mouth: mouth, coat: COATS[mood] };
  }

  function el(name, attrs) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function shape(s) {
    const k = s[0], f = (n) => n.toFixed(2);
    if (k === "pill") return el("rect", { x: f(s[1] - s[3] / 2), y: f(s[2] - s[4] / 2), width: f(s[3]), height: f(s[4]), rx: f(s[3] / 2), class: "ink" });
    if (k === "o") return el("circle", { cx: f(s[1]), cy: f(s[2]), r: f(s[3]), class: "ink" });
    let d;
    if (k === "x") { const h = s[3] / 2; d = `M${f(s[1] - h)} ${f(s[2] - h)}L${f(s[1] + h)} ${f(s[2] + h)}M${f(s[1] + h)} ${f(s[2] - h)}L${f(s[1] - h)} ${f(s[2] + h)}`; }
    else if (k === "line") d = `M${f(s[1])} ${f(s[2])}L${f(s[3])} ${f(s[4])}`;
    else { const w = s[3], c = s[1], y = s[2], dd = s[4]; d = `M${f(c - w / 2)} ${f(y)}C${f(c - w / 4)} ${f(y + dd)} ${f(c + w / 4)} ${f(y + dd)} ${f(c + w / 2)} ${f(y)}`; }
    return el("path", { d: d, class: "stroke" });
  }

  function Life() {
    const now = performance.now() / 1000, rnd = (a, b) => a + Math.random() * (b - a);
    let nextBlink = now + rnd(2, 6), nextLook = now + rnd(4, 9), lookUntil = 0, look = [0, 0], target = [0, 0];
    return function step(t) {
      let blink = 0;
      const dt = t - nextBlink;
      if (dt >= 0 && dt < 0.18) blink = 1 - Math.abs(dt - 0.09) / 0.09;
      else if (dt >= 0.18) nextBlink = t + rnd(2, 6);
      if (t >= nextLook) {
        target = [[-1, -0.6, 0.6, 1][Math.floor(Math.random() * 4)], rnd(-0.4, 0.3)];
        lookUntil = t + rnd(0.8, 1.6); nextLook = t + rnd(5, 11);
      }
      const goal = t < lookUntil ? target : [0, 0];
      look = [look[0] + (goal[0] - look[0]) * 0.25, look[1] + (goal[1] - look[1]) * 0.25];
      return [blink, look];
    };
  }

  function create(mood, label) {
    const svg = el("svg", { viewBox: "0 0 100 100", class: "gb-mascot", role: "img" });
    const title = el("title", {}); title.textContent = label || "Bit";
    svg.append(title);
    const head = el("rect", { class: "head" });
    const g = el("g", {});
    svg.append(head, g);
    const life = Life();
    let cur = mood || "idle", last = 0;
    function paint(t) {
      const [b, l] = reduce ? [0, [0, 0]] : life(t);
      const fc = face(cur, b, l, t);
      const h = fc.head;
      head.setAttribute("x", h[0]); head.setAttribute("y", h[1].toFixed(2));
      head.setAttribute("width", h[2]); head.setAttribute("height", h[3]);
      head.setAttribute("rx", h[4]); head.setAttribute("fill", fc.coat);
      g.replaceChildren(...fc.eyes.concat(fc.mouth ? [fc.mouth] : []).map(shape));
      svg.setAttribute("data-mood", fc.mood);
    }
    function loop(ms) {
      if (!svg.isConnected && last) return; // removed from the page: stop
      if (!document.hidden && ms - last > 50) { last = ms; paint(ms / 1000); }
      requestAnimationFrame(loop);
    }
    svg.setMood = (m) => { cur = MOODS.indexOf(m) >= 0 ? m : "idle"; paint(performance.now() / 1000); };
    svg.flash = (m, ms) => { const prev = cur; svg.setMood(m); setTimeout(() => svg.setMood(prev), ms || 1600); };
    paint(performance.now() / 1000);
    requestAnimationFrame(loop);
    return svg;
  }

  window.GBMascot = { create: create, face: face, MOODS: MOODS };
})();
