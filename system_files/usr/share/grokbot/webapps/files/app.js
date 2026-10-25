// Files: a Grok Bot web app over the OS API. It sees only the home folder
// (no hidden files) and asks for two separate permissions: "files" to look
// and "files-write" to save, rename, create and trash.
(() => {
  "use strict";
  const T = {
    ko: { title: "파일", home: "홈", up: "위로", mkdir: "새 폴더", newfile: "새 텍스트 파일", filter: "이 폴더에서 찾기",
      name: "이름", size: "크기", modified: "수정한 날", open: "열기", rename: "이름 바꾸기", trash: "휴지통", save: "저장", close: "닫기",
      lang: "English", empty: "빈 폴더입니다", hidden: "숨김 항목 %s개는 보이지 않습니다", items: "항목 %s개",
      needread: "홈 폴더의 파일을 보려면 \"홈 폴더 파일 보기\" 권한이 필요합니다. 숨김 파일(설정, 키)은 이 권한으로도 보이지 않습니다.",
      needwrite: "저장, 이름 바꾸기, 휴지통은 \"홈 폴더 파일 바꾸기\" 권한이 필요합니다.", ask: "권한 요청", askw: "쓰기 권한 요청",
      denied: "거부되었습니다. 설정 > 권한에서 바꿀 수 있습니다.", asking: "확인 창에서 선택해 주세요…",
      ro: "보기만", rw: "보기 · 바꾸기", rwask: "보기 · 바꿀 때마다 확인", newname: "새 이름", foldername: "새 폴더 이름",
      filename: "새 파일 이름", confirmtrash: "\"%s\"을(를) 휴지통으로 옮길까요?", trashed: "휴지통으로 옮겼습니다", saved: "저장했습니다",
      big: "파일이 너무 커서 여기서 열 수 없습니다", binary: "미리 볼 수 없는 파일입니다 (%s)", offline: "grokbotd에 연결할 수 없습니다", dir: "폴더",
      needreadvol: "'%s' 드라이브의 파일을 보려면 \"파일 보기\" 권한이 필요합니다. 홈 폴더와 같은 권한입니다.", drives: "USB 드라이브", eject: "꺼내기", ejected: "꺼냈습니다. 이제 뽑아도 됩니다", opening: "드라이브를 여는 중…", unlock: "잠금 해제", unlocking: "암호 입력 창에서 암호를 입력하세요…", lock: "잠그기", locked: "드라이브를 잠갔습니다" },
    en: { title: "Files", home: "Home", up: "Up", mkdir: "New folder", newfile: "New text file", filter: "Find in this folder",
      name: "Name", size: "Size", modified: "Modified", open: "Open", rename: "Rename", trash: "Trash", save: "Save", close: "Close",
      lang: "한국어", empty: "This folder is empty", hidden: "%s hidden items are not shown", items: "%s items",
      needread: "Seeing files in your home folder needs the \"See files in your home folder\" permission. Hidden files (settings, keys) stay out of reach even with it.",
      needwrite: "Saving, renaming and trashing need the \"Change files in your home folder\" permission.", ask: "Ask for permission", askw: "Ask for write permission",
      denied: "Denied. You can change it in Settings > Permissions.", asking: "Answer the prompt…",
      ro: "View only", rw: "View · change", rwask: "View · confirm each change", newname: "New name", foldername: "Folder name",
      filename: "File name", confirmtrash: "Move \"%s\" to the trash?", trashed: "Moved to the trash", saved: "Saved",
      big: "Too large to open here", binary: "No preview for this file (%s)", offline: "Cannot reach grokbotd", dir: "Folder",
      needreadvol: "To see the files on '%s', Files needs the \"view files\" permission (the same one as for your home folder).", drives: "USB drives", eject: "Eject", ejected: "Ejected. Safe to remove", opening: "Opening the drive…", unlock: "Unlock", unlocking: "Type the passphrase in the secure prompt…", lock: "Lock", locked: "Drive locked" }
  };
  let lang = localStorage.getItem("files.lang") || "ko";
  const t = (k, ...a) => { let s = (T[lang] || T.ko)[k] || k; for (const x of a) s = s.replace("%s", x); return s; };
  const $ = (id) => document.getElementById(id);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null) el.append(c.nodeType ? c : String(c));
    return el;
  }
  const fmtB = (b) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i ? 1 : 0) + " " + u[i]; };
  const when = (s) => new Date(s * 1000).toLocaleString(lang === "ko" ? "ko-KR" : "en-US", { dateStyle: "medium", timeStyle: "short" });

  let rid = 0, vol = null, drives = [];
  // files.* calls go to the open USB drive when one is selected (volume = storage.list id).
  const withVol = (m, p) => (vol && m.startsWith("files.")) ? Object.assign({}, p, { volume: vol.id }) : p;
  class ApiError extends Error { constructor(e) { super(e.message); this.code = e.code; } }
  const bit = (mood) => (window.GBMascot ? GBMascot.create(mood, "Bit") : h("span", {}));
  async function rpc(method, params) {
    const r = await fetch("/v1/rpc", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: withVol(method, params || {}), "x-client": "Files" }) });
    const b = await r.json();
    if (b.error) throw new ApiError(b.error);
    return b.result;
  }
  function toast(msg) { const e = $("toast"); e.textContent = msg; e.classList.remove("hidden"); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.add("hidden"), 2600); }

  let modes = {}, cwd = localStorage.getItem("files.cwd") || "/", listing = null, sel = null, editing = null;
  async function loadModes() {
    try {
      const r = await rpc("api.methods");
      modes = {}; for (const m of r.methods) modes[m.name] = m.mode;
    } catch (e) { modes = null; }
  }
  const canRead = () => modes && modes["files.list"] === "allow";
  const writeMode = () => (modes && modes["files.write"]) || "deny";

  async function request(scope, box) {
    box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    const msg = h("span", { class: "dim" }, t("asking")); box.append(msg);
    const face = box.querySelector(".gb-mascot"), mood = (m) => face && face.setMood && face.setMood(m);
    mood("thinking");
    try {
      const r = await rpc("permissions.request", { scope, reason: lang === "ko" ? "파일 앱에서 홈 폴더를 보여 주고 바꾸기" : "Files app: browse and change your home folder" });
      await loadModes();
      if (r.mode === "deny") { msg.textContent = t("denied"); mood("sad"); } else return render(), go(vol ? "/" : cwd);
    } catch (e) { msg.textContent = e.message; mood("error"); }
    box.querySelectorAll("button").forEach((b) => { b.disabled = false; });
  }

  function crumbs() {
    const nav = $("crumbs"); nav.replaceChildren();
    const parts = cwd.split("/").filter(Boolean);
    nav.append(h("button", { type: "button", class: vol ? "" : "on", onclick: () => setVol(null) }, "🏠 " + t("home")));
    for (const d of drives) {
      nav.append(h("button", { type: "button", class: "drive" + (vol && vol.id === d.id ? " on" : ""), 
        title: (d.locked ? t("unlock") + " · " : "") + (d.device || d.id) + (d.fs ? " · " + d.fs : ""), onclick: () => openDrive(d) }, (d.locked ? "🔒 " : d.encrypted ? "🔓 " : "💾 ") + (d.label || d.id)));
      if (d.mounted) nav.append(h("button", { type: "button", class: "eject", title: t("eject"), onclick: () => eject(d) }, "⏏"));
    }
    if (modes && modes["storage.list"] !== "allow")
      nav.append(h("button", { type: "button", class: "drive", onclick: (ev) => askDrives(ev.target) }, "💾 " + t("drives")));
    nav.append(h("span", { class: "sep" }, "|"));
    parts.forEach((p, i) => {
      nav.append(h("span", { class: "sep" }, "›"));
      nav.append(h("button", { type: "button", onclick: () => go("/" + parts.slice(0, i + 1).join("/")) }, p));
    });
  }
  function permPill() {
    const p = $("perm");
    if (!modes) { p.textContent = t("offline"); p.className = "pill warn"; return; }
    if (!canRead()) { p.textContent = ""; p.className = "pill hidden"; return; }
    const w = writeMode();
    p.textContent = w === "allow" ? t("rw") : w === "ask" ? t("rwask") : t("ro");
    p.className = "pill " + (w === "deny" ? "warn" : "ok");
  }
  const icon = (e) => e.type === "dir" ? "📁" : /^image\//.test(e.mime) ? "🖼️" : /^audio\//.test(e.mime) ? "🎵" : /^video\//.test(e.mime) ? "🎬" : /^text\/|json|xml|javascript/.test(e.mime) ? "📄" : "📦";

  function render() {
    document.documentElement.lang = lang; document.title = t("title");
    document.querySelectorAll("[data-t]").forEach((e) => { e.textContent = t(e.dataset.t); });
    document.querySelectorAll("[data-ph]").forEach((e) => { e.placeholder = t(e.dataset.ph); });
    $("lang").textContent = t("lang");
    crumbs(); permPill();
    const main = $("main"); main.replaceChildren();
    const ro = writeMode() === "deny";
    $("mkdir").disabled = ro; $("newfile").disabled = ro; $("up").disabled = cwd === "/" || !canRead();
    if (!modes) { main.append(h("div", { class: "empty" }, bit("sad"), t("offline"))); return; }
    if (!canRead()) {
      const box = h("div", { class: "need" }, bit("alert"), h("div", {}, vol ? t("needreadvol", vol.label) : t("needread")));
      box.append(h("button", { type: "button", class: "primary", onclick: () => request("files", box) }, t("ask")));
      main.append(box); return;
    }
    if (ro) {
      const box = h("div", { class: "need" }, h("div", { class: "dim" }, t("needwrite")));
      box.append(h("button", { type: "button", onclick: () => request("files-write", box) }, t("askw")));
      main.append(box);
    }
    if (!listing) return;
    const q = $("q").value.trim().toLowerCase();
    const rows = listing.entries.filter((e) => !q || e.name.toLowerCase().includes(q));
    const tb = h("tbody");
    for (const e of rows) {
      const tr = h("tr", { class: "row" + (sel === e.path ? " sel" : ""), tabindex: "0" },
        h("td", { class: "name", title: e.name, onclick: () => openEntry(e) }, h("i", {}, icon(e)), e.name),
        h("td", { class: "dim" }, e.type === "dir" ? t("dir") : fmtB(e.size)),
        h("td", { class: "dim" }, when(e.mtime)),
        h("td", { class: "act" },
          ro ? null : h("button", { type: "button", onclick: () => rename(e) }, t("rename")),
          ro ? null : h("button", { type: "button", class: "danger", onclick: () => trash(e) }, t("trash"))));
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") openEntry(e); if (ev.key === "Delete" && !ro) trash(e); if (ev.key === "F2" && !ro) rename(e); });
      tb.append(tr);
    }
    main.append(h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("name")), h("th", {}, t("size")), h("th", {}, t("modified")), h("th", {}))), tb));
    if (!rows.length) main.append(h("div", { class: "empty" }, bit("idle"), t("empty")));
    main.append(h("p", { class: "dim" }, t("items", listing.entries.length) + (listing.hidden ? " · " + t("hidden", listing.hidden) : "")));
  }

  const driveKey = (ds) => JSON.stringify(ds.map((d) => [d.id, d.label, d.mounted, d.locked, d.encrypted]));
  async function loadDrives() {
    drives = [];
    if (!modes || modes["storage.list"] !== "allow") return;
    try { drives = (await rpc("storage.list")).volumes || []; } catch (e) { drives = []; }
    if (vol && !drives.some((d) => d.id === vol.id && d.mounted)) vol = null;
  }
  // Drives come and go (hotplug, eject elsewhere, Settings): poll while the
  // window is visible and redraw only when the list really changed.
  async function pollDrives() {
    if (document.hidden || !modes || modes["storage.list"] !== "allow") return;
    const before = driveKey(drives), hadVol = vol;
    await loadDrives();
    if (driveKey(drives) === before) return;
    if (hadVol && !vol) { closeView(); return go(localStorage.getItem("files.cwd") || "/"); }
    crumbs();
  }
  async function askDrives(btn) {
    btn.disabled = true;
    try { const r = await rpc("permissions.request", { scope: "storage", reason: lang === "ko" ? "파일 앱에서 USB 드라이브 열기" : "Files app: open USB drives" });
      await loadModes(); if (r.mode === "deny") toast(t("denied")); await loadDrives(); render();
    } catch (e) { toast(e.message); btn.disabled = false; }
  }
  async function openDrive(d) {
    try {
      if (d.locked) {
        toast(t("unlocking"));
        const u = await rpc("storage.unlock", { id: d.id, mount: true });
        await loadDrives(); d = drives.find((x) => x.id === u.id) || u;
      }
      if (!d.mounted) { toast(t("opening")); await rpc("storage.mount", { id: d.id }); await loadDrives(); d = drives.find((x) => x.id === d.id) || d; }
      vol = { id: d.id, label: d.label || d.id }; closeView(); go("/");
    } catch (e) { toast(e.message); }
  }
  async function eject(d) {
    try {
      if (vol && vol.id === d.id) { vol = null; closeView(); }
      await rpc("storage.unmount", { id: d.id, eject: true }); toast(t("ejected"));
    } catch (e) { toast(e.message); }
    await loadDrives(); go(vol ? cwd : (localStorage.getItem("files.cwd") || "/"));
  }
  function setVol(v) { vol = v; closeView(); go(v ? "/" : (localStorage.getItem("files.cwd") || "/")); }

  async function go(path) {
    if (!canRead()) return render();
    try {
      listing = await rpc("files.list", { path });
      cwd = listing.path; if (!vol) localStorage.setItem("files.cwd", cwd); sel = null;
    } catch (e) {
      if (vol && e.message && /drive|volume/i.test(e.message)) { vol = null; await loadDrives(); return go("/"); }
      if (path !== "/") return go("/");
      toast(e.message); listing = null;
    }
    $("q").value = ""; render();
  }
  const join = (name) => (cwd === "/" ? "" : cwd) + "/" + name;

  async function openEntry(e) {
    if (e.type === "dir") return go(e.path);
    sel = e.path; render();
    const body = $("vbody"); body.replaceChildren(); $("vname").textContent = e.name; $("save").classList.add("hidden"); editing = null;
    $("view").classList.remove("hidden");
    const isText = /^text\/|json|xml|javascript|x-sh|x-python|yaml|toml/.test(e.mime) || /\.(md|txt|log|conf|ini|csv)$/i.test(e.name);
    const isImg = /^image\/(png|jpeg|gif|webp|svg\+xml)$/.test(e.mime);
    if (e.size > (isText ? 2 : 16) * 1048576) { body.append(h("div", { class: "empty" }, t("big"))); return; }
    try {
      if (isText) {
        const r = await rpc("files.read", { path: e.path, encoding: "utf-8" });
        const ta = h("textarea", { spellcheck: "false" }); ta.value = r.data;
        ta.readOnly = writeMode() === "deny";
        body.append(ta); editing = { path: e.path, ta };
        if (!ta.readOnly) $("save").classList.remove("hidden");
      } else if (isImg) {
        const r = await rpc("files.read", { path: e.path, encoding: "base64" });
        body.append(h("img", { alt: e.name, src: "data:" + e.mime + ";base64," + r.data }));
      } else {
        body.append(h("div", { class: "empty" }, t("binary", e.mime)));
      }
    } catch (err) { body.append(h("div", { class: "empty" }, err.message)); }
  }
  async function act(fn, ok) {
    try { await fn(); if (ok) toast(ok); } catch (e) { toast(e.code === -32001 ? t("denied") : e.message); }
    await loadModes(); await go(cwd);
  }
  function rename(e) {
    const n = prompt(t("newname"), e.name);
    if (!n || n === e.name) return;
    act(() => rpc("files.move", { path: e.path, to: join(n) }));
  }
  function trash(e) {
    if (!confirm(t("confirmtrash", e.name))) return;
    if (editing && editing.path === e.path) closeView();
    act(() => rpc("files.trash", { path: e.path }), t("trashed"));
  }
  function closeView() { $("view").classList.add("hidden"); editing = null; sel = null; render(); }

  $("up").addEventListener("click", () => go(cwd.replace(/\/[^/]*$/, "") || "/"));
  $("mkdir").addEventListener("click", () => { const n = prompt(t("foldername")); if (n) act(() => rpc("files.mkdir", { path: join(n) })); });
  $("newfile").addEventListener("click", () => {
    const n = prompt(t("filename"), lang === "ko" ? "새 문서.txt" : "untitled.txt");
    if (n) act(async () => { await rpc("files.write", { path: join(n), data: "" }); openEntry({ path: join(n), name: n, type: "file", size: 0, mime: "text/plain" }); });
  });
  $("save").addEventListener("click", () => { if (editing) act(() => rpc("files.write", { path: editing.path, data: editing.ta.value, overwrite: true }), t("saved")); });
  $("close").addEventListener("click", closeView);
  $("q").addEventListener("input", render);
  $("lang").addEventListener("click", () => { lang = lang === "ko" ? "en" : "ko"; localStorage.setItem("files.lang", lang); render(); });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s" && editing) { e.preventDefault(); $("save").click(); }
    if (e.key === "Backspace" && e.altKey) $("up").click();
  });

  (async () => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    await loadModes(); await loadDrives(); render(); go(cwd);
    setInterval(pollDrives, 3000);
    document.addEventListener("visibilitychange", pollDrives);
  })();
})();
