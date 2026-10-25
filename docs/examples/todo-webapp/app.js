"use strict";
// Todo app: todos live in ~/Documents/Todo/todos.json through the grokbotd files API.
const DIR = "/Documents/Todo", FILE = DIR + "/todos.json";
let todos = [], rid = 0;
const $ = (id) => document.getElementById(id);
async function rpc(method, params) {
  const r = await fetch("/v1/rpc", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: params || {}, "x-client": "Todo" }) });
  const b = await r.json();
  if (b.error) { const e = new Error(b.error.message); e.code = b.error.code; throw e; }
  return b.result;
}
async function ask(scope, reason) {
  const r = await rpc("permissions.request", { scope, reason });
  if (r.mode === "deny") throw new Error("권한이 거부되었습니다: " + scope);
}
async function load() {
  try { const r = await rpc("files.read", { path: FILE }); todos = JSON.parse(r.data).todos || []; }
  catch (e) {
    if (e.code === -32001) { await ask("files", "할 일 앱: 할 일 파일(~/Documents/Todo/todos.json) 읽기"); return load(); }
    if (!/not found|No such|exist/i.test(e.message)) throw e; // never overwrite a file we could not read
    todos = []; // no file yet
  }
}
async function save() {
  const content = JSON.stringify({ version: 1, saved: new Date().toISOString(), todos }, null, 2);
  try { await rpc("files.write", { path: FILE, data: content, overwrite: true }); }
  catch (e) {
    if (e.code === -32001) { await ask("files-write", "할 일 앱: 할 일 파일(~/Documents/Todo/todos.json) 저장"); return save(); }
    if (/not found|No such|exist/i.test(e.message)) { for (const d of ["/Documents", DIR]) await rpc("files.mkdir", { path: d }).catch(() => {}); return rpc("files.write", { path: FILE, data: content, overwrite: true }); }
    throw e;
  }
}
function render() {
  const ul = $("list"); ul.textContent = "";
  todos.forEach((t, i) => {
    const li = document.createElement("li"); if (t.done) li.className = "done";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = t.done;
    cb.onchange = () => act(() => { t.done = cb.checked; });
    const s = document.createElement("span"); s.textContent = t.text;
    const del = document.createElement("button"); del.textContent = "삭제";
    del.onclick = () => act(() => { todos.splice(i, 1); });
    li.append(cb, s, del); ul.append(li);
  });
}
async function act(fn) { fn(); render(); try { await save(); $("msg").textContent = ""; } catch (e) { $("msg").textContent = e.message; } }
$("f").onsubmit = (ev) => { ev.preventDefault(); const v = $("t").value.trim(); if (!v) return;
  $("t").value = ""; act(() => todos.push({ text: v, done: false, at: Date.now() })); };
$("file").textContent = "~" + FILE;
load().then(render).catch((e) => { $("msg").textContent = e.message; });
