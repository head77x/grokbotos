"use strict";
// GrokBot app-data helper: <script src="/_grokbot/appdata.js"></script>
// Files live in ~/.local/share/grokbot/app-data/<app-id>/; paths are relative to it.
// No permission prompt for installed apps; other apps cannot read them.
(function () {
  let rid = 0;
  async function rpc(method, params) {
    const r = await fetch("/v1/rpc", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++rid, method, params: params || {} }) });
    const b = await r.json();
    if (b.error) { const e = new Error(b.error.message); e.code = b.error.code; throw e; }
    return b.result;
  }
  const notFound = (e) => /not found|No such|exist/i.test(e.message);
  window.GrokAppData = {
    rpc,
    list: (path) => rpc("appdata.list", { path: path || "/" }),
    read: async (path) => (await rpc("appdata.read", { path })).data,
    write: (path, data) => rpc("appdata.write", { path, data, overwrite: true }),
    mkdir: (path) => rpc("appdata.mkdir", { path }),
    remove: (path, recursive) => rpc("appdata.delete", { path, recursive: !!recursive }),
    async readJSON(path, fallback) {
      try { return JSON.parse(await this.read(path)); }
      catch (e) { if (notFound(e)) return fallback; throw e; }
    },
    writeJSON(path, value) { return this.write(path, JSON.stringify(value, null, 2)); },
  };
})();
