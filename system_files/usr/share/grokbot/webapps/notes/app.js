// Notes: a Grok Bot web app that needs no OS permission at all. Notes live
// in this app's own IndexedDB (its own browser profile, its own origin), so
// nothing leaves the computer and it works offline.
(() => {
  "use strict";
  const T = {
    ko: { title: "메모", new: "새 메모", search: "검색", untitled: "제목 없음", write: "여기에 적으세요…", delete: "삭제",
      empty: "메모가 없습니다. \"새 메모\"를 눌러 시작하세요.", saved: "저장됨 %s", saving: "저장 중…", lang: "English",
      confirm: "이 메모를 지울까요? 되돌릴 수 없습니다.", where: "이 컴퓨터에만 저장 · %s개", nomatch: "찾는 메모가 없습니다" },
    en: { title: "Notes", new: "New note", search: "Search", untitled: "Untitled", write: "Write here…", delete: "Delete",
      empty: "No notes yet. Press \"New note\" to start.", saved: "Saved %s", saving: "Saving…", lang: "한국어",
      confirm: "Delete this note? This cannot be undone.", where: "Stored on this computer only · %s", nomatch: "No matching notes" }
  };
  let lang = localStorage.getItem("notes.lang") || "ko";
  const t = (k, ...a) => { let s = (T[lang] || T.ko)[k] || k; for (const x of a) s = s.replace("%s", x); return s; };
  const $ = (id) => document.getElementById(id);
  const when = (ms) => new Date(ms).toLocaleString(lang === "ko" ? "ko-KR" : "en-US", { dateStyle: "short", timeStyle: "short" });

  let db, notes = [], cur = null, timer = null;
  const open = () => new Promise((res, rej) => {
    const q = indexedDB.open("notes", 1);
    q.onupgradeneeded = () => q.result.createObjectStore("notes", { keyPath: "id" });
    q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error);
  });
  const all = () => new Promise((res) => { const q = db.transaction("notes").objectStore("notes").getAll(); q.onsuccess = () => res(q.result || []); });
  const put = (n) => new Promise((res) => { const tx = db.transaction("notes", "readwrite"); tx.objectStore("notes").put(n); tx.oncomplete = res; });
  const del = (id) => new Promise((res) => { const tx = db.transaction("notes", "readwrite"); tx.objectStore("notes").delete(id); tx.oncomplete = res; });

  function render() {
    document.documentElement.lang = lang;
    document.title = t("title");
    document.querySelectorAll("[data-t]").forEach((e) => { e.textContent = t(e.dataset.t); });
    document.querySelectorAll("[data-ph]").forEach((e) => { e.placeholder = t(e.dataset.ph); });
    $("lang").textContent = t("lang");
    $("where").textContent = t("where", notes.length);
    const q = $("q").value.trim().toLowerCase();
    notes.sort((a, b) => b.updated - a.updated);
    const ul = $("list"); ul.replaceChildren();
    const shown = notes.filter((n) => !q || (n.title + "\n" + n.body).toLowerCase().includes(q));
    for (const n of shown) {
      const li = document.createElement("li");
      const b = document.createElement("b"); b.textContent = n.title || firstLine(n.body) || t("untitled");
      const s = document.createElement("span"); s.textContent = when(n.updated) + " · " + (n.body.replace(/\s+/g, " ").slice(0, 60) || "…");
      li.append(b, s); li.tabIndex = 0;
      if (cur && n.id === cur.id) li.className = "on";
      li.addEventListener("click", () => select(n));
      li.addEventListener("keydown", (e) => { if (e.key === "Enter") select(n); });
      ul.append(li);
    }
    if (!shown.length && q) { const li = document.createElement("li"); li.className = "dim"; li.textContent = t("nomatch"); ul.append(li); }
    $("ed").classList.toggle("hidden", !cur);
    $("empty").classList.toggle("hidden", !!cur);
    if (!cur && window.GBMascot && !$("bit").firstChild) $("bit").append(GBMascot.create("idle", "Bit"));
    if (cur) $("saved").textContent = t("saved", when(cur.updated));
  }
  const firstLine = (s) => (s || "").split("\n").find((l) => l.trim()) || "";
  function select(n) { flush(); cur = n; $("title").value = n.title; $("body").value = n.body; render(); }
  async function create() {
    flush();
    const n = { id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())), title: "", body: "", created: Date.now(), updated: Date.now() };
    notes.push(n); await put(n); cur = n; $("title").value = ""; $("body").value = ""; render(); $("title").focus();
  }
  function edited() {
    if (!cur) return;
    cur.title = $("title").value; cur.body = $("body").value; cur.updated = Date.now();
    $("saved").textContent = t("saving");
    clearTimeout(timer); timer = setTimeout(() => { timer = null; put(cur).then(render); }, 400);
  }
  function flush() { if (timer && cur) { clearTimeout(timer); timer = null; put(cur); } }

  $("new").addEventListener("click", create);
  $("title").addEventListener("input", edited);
  $("body").addEventListener("input", edited);
  $("q").addEventListener("input", render);
  $("del").addEventListener("click", async () => {
    if (!cur || !confirm(t("confirm"))) return;
    clearTimeout(timer); timer = null;
    await del(cur.id); notes = notes.filter((n) => n.id !== cur.id); cur = notes.sort((a, b) => b.updated - a.updated)[0] || null;
    if (cur) select(cur); else render();
  });
  $("lang").addEventListener("click", () => { lang = lang === "ko" ? "en" : "ko"; localStorage.setItem("notes.lang", lang); render(); });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "n") { e.preventDefault(); create(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); flush(); render(); }
  });
  window.addEventListener("beforeunload", flush);

  (async () => {
    db = await open();
    notes = await all();
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    cur = notes.sort((a, b) => b.updated - a.updated)[0] || null;
    if (cur) select(cur); else render();
  })();
})();
