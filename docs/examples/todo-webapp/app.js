"use strict";
// Todo app: todos live in the app's own data folder
// (~/.local/share/grokbot/app-data/todo/todos.json) via /_grokbot/appdata.js. No permission prompt.
const FILE = "todos.json", AD = window.GrokAppData;
let todos = [];
const $ = (id) => document.getElementById(id);
async function load() { todos = ((await AD.readJSON(FILE, { todos: [] })).todos) || []; }
async function save() { await AD.writeJSON(FILE, { version: 1, saved: new Date().toISOString(), todos }); }
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
$("file").textContent = "~/.local/share/grokbot/app-data/todo/" + FILE;
load().then(render).catch((e) => { $("msg").textContent = e.message; });
