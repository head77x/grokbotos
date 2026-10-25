// The Grok Bot OS face (same geometry as grokbot_mascot.py), drawn in code
// after the x.ai/bot avatar guideline: a flat circle (viewBox 0 0 92 92,
// centre 46,46, r 27.6) with two vertical pill eyes cut in the background
// colour. No mouth, ever: states are told by eye shape/tilt and body motion.
// Usage: const m = GBMascot.create("idle"); el.append(m); m.setMood("thinking").
// The body uses currentColor-like tokens (.gb-mascot .body/.eye), so it
// inverts with the theme. DOM nodes and attributes only (CSP-safe).
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const MOODS = ["idle", "thinking", "listening", "happy", "alert", "error", "sleeping", "sad"];
  const CX = 46, CY = 46, R = 27.6, EYE_W = 6.9, EYE_H = 15.6, EYE_L = 37.45, EYE_R = 54.5, EYE_Y = 46;
  const BLINK_H = 3.2, BLINK_S = 0.25;
  const HERO_W = 10.7, HERO_H = 23.0, HERO_L = 36.85, HERO_R = 55.35; // large avatar
  const LABELS = { idle: "", thinking: "생각 중… / Thinking…", listening: "듣는 중… / Listening…",
    happy: "완료 / Done", alert: "확인이 필요합니다 / Needs you",
    error: "문제가 생겼습니다 / Something went wrong", sleeping: "절전 / Resting", sad: "연결 안 됨 / Offline" };
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const S = Math.sin, PI = Math.PI;

  function spring(age) {
    if (age == null || age >= 1.2) return 1;
    const a = Math.max(0, age);
    return 1 - 0.15 * Math.exp(-6 * a) * Math.cos(12 * a);
  }

  function face(mood, blink, look, t, age, hero) {
    if (MOODS.indexOf(mood) < 0) mood = "idle";
    let lx = clamp(look[0], -1, 1), ly = clamp(look[1], -1, 1);
    let sc = 1 + 0.03 * S(t * 2 * PI / 3.2), bx = 0.8 * S(t * 0.9) + lx * 2, by = 0.8 * S(t * 1.3);
    let ew = EYE_W, eh = EYE_H, edy = ly * 2, spread = 0, tilt = 0, rot = lx * 12, dim = 1;
    let el = EYE_L, er = EYE_R;
    if (hero) { ew = HERO_W; eh = HERO_H; el = HERO_L; er = HERO_R; }
    if (mood === "thinking") {
      lx = 0.8; ly = -0.7; rot = 12 + 3 * S(t * 1.1); edy = -3;
      bx = 2 + 1.2 * S(t * 0.7); sc = 1 + 0.02 * S(t * 2 * PI / 4.5);
    } else if (mood === "listening") {
      ew *= 1.12; eh *= 1.1; sc = 1 + 0.04 * S(t * 2 * PI * 1.2);
    } else if (mood === "alert") {
      ew *= 1.18; eh *= 1.12; sc = 1.05 + 0.025 * S(t * 2 * PI * 1.6); spread = 0.8;
    } else if (mood === "sleeping") {
      blink = 1; rot = 0; lx = 0; edy = 2; sc = 1 + 0.04 * S(t * 2 * PI / 4.5);
      bx = 0; by = 1.2 * S(t * 2 * PI / 4.5);
    } else if (mood === "sad" || mood === "error") {
      edy = 3; eh *= 0.82; tilt = 14; rot = 0; lx = 0; by += 1.5;
      dim = mood === "error" ? 0.55 : 0.7;
      if (mood === "error") bx = 1.2 * S(t * 14) * Math.max(0, Math.cos(t * 0.8));
    } else if (mood === "happy") {
      by = -4 * Math.abs(S(PI * t * 1.6)); eh *= 0.94;
    }
    sc *= spring(age);
    const closed = BLINK_H * (hero ? HERO_H / EYE_H : 1);
    if (mood !== "sleeping") eh = eh - (eh - closed) * clamp(blink, 0, 1);
    else eh = closed * 0.75;
    const ex = lx * 3.5;
    return { mood: mood, body: [CX + bx, CY + by, R], scale: sc, dim: dim, label: LABELS[mood],
      eyes: [[el - spread + ex, EYE_Y + edy, ew, eh, rot + tilt], [er + spread + ex, EYE_Y + edy, ew, eh, rot - tilt]] };
  }

  function blinkAt(dt) { return dt < 0 || dt >= BLINK_S ? 0 : S(PI * dt / BLINK_S); }

  function el(name, attrs) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function Life() {
    const now = performance.now() / 1000, rnd = (a, b) => a + Math.random() * (b - a);
    let nextBlink = now + rnd(2, 6), nextLook = now + rnd(4, 9), lookUntil = 0, look = [0, 0], target = [0, 0];
    return function step(t) {
      let blink = 0;
      const dt = t - nextBlink;
      if (dt >= 0 && dt < BLINK_S) blink = blinkAt(dt);
      else if (dt >= BLINK_S) nextBlink = t + rnd(2, 6);
      if (t >= nextLook) {
        target = [[-1, -0.6, 0.6, 1][Math.floor(Math.random() * 4)], rnd(-0.4, 0.3)];
        lookUntil = t + rnd(0.8, 1.6); nextLook = t + rnd(5, 11);
      }
      const goal = t < lookUntil ? target : [0, 0];
      look = [look[0] + (goal[0] - look[0]) * 0.25, look[1] + (goal[1] - look[1]) * 0.25];
      return [blink, look];
    };
  }

  function create(mood, label, opts) {
    const stateEl = opts && opts.labelEl; // optional text node next to the face
    const hero = !!(opts && opts.hero);    // large avatar proportions
    // Small faces use a tight viewport (FIT, same as Python) so the circle
    // fills the slot; the hero keeps the full 92 box with its margin.
    const svg = el("svg", { viewBox: hero ? "0 0 92 92" : "12 11 68 68", class: hero ? "gb-mascot lg" : "gb-mascot", role: "img" });
    const title = el("title", {});
    svg.append(title);
    const g = el("g", {});
    const body = el("circle", { r: R, class: "body" });
    const eyes = [el("rect", { class: "eye" }), el("rect", { class: "eye" })];
    g.append(body, eyes[0], eyes[1]);
    svg.append(g);
    const life = Life();
    let cur = mood || "idle", last = 0, since = performance.now() / 1000;
    const f2 = (n) => n.toFixed(2);
    function paint(t) {
      const [b, l] = reduce ? [0, [0, 0]] : life(t);
      const fc = reduce ? face(cur, 0, [0, 0], 0, null, hero) : face(cur, b, l, t, t - since, hero);
      const [cx, cy] = fc.body;
      g.setAttribute("transform", `translate(${f2(cx)} ${f2(cy)}) scale(${fc.scale.toFixed(4)}) translate(${f2(-cx)} ${f2(-cy)})`);
      g.setAttribute("opacity", fc.dim);
      body.setAttribute("cx", f2(cx)); body.setAttribute("cy", f2(cy));
      fc.eyes.forEach((e, i) => {
        const [x, y, w, h, deg] = e;
        eyes[i].setAttribute("x", f2(x - w / 2)); eyes[i].setAttribute("y", f2(y - h / 2));
        eyes[i].setAttribute("width", f2(w)); eyes[i].setAttribute("height", f2(h));
        eyes[i].setAttribute("rx", f2(w / 2));
        eyes[i].setAttribute("transform", `rotate(${f2(deg)} ${f2(x)} ${f2(y)})`);
      });
      title.textContent = fc.label || label || "Grok Bot";
      svg.setAttribute("data-mood", fc.mood);
    }
    function loop(ms) {
      if (!svg.isConnected && last) return; // removed from the page: stop
      if (!document.hidden && ms - last > 33) { last = ms; paint(ms / 1000); }
      requestAnimationFrame(loop);
    }
    svg.setMood = (m) => {
      const n = MOODS.indexOf(m) >= 0 ? m : "idle";
      if (n !== cur) { cur = n; since = performance.now() / 1000; }
      if (stateEl) stateEl.textContent = LABELS[cur];
      paint(performance.now() / 1000);
    };
    svg.flash = (m, ms) => { const prev = cur; svg.setMood(m); setTimeout(() => svg.setMood(prev), ms || 1600); };
    if (stateEl) stateEl.textContent = LABELS[cur];
    paint(performance.now() / 1000);
    if (!reduce) requestAnimationFrame(loop);
    return svg;
  }

  window.GBMascot = { create: create, face: face, MOODS: MOODS, LABELS: LABELS };
})();
