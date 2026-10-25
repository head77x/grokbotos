"""Web app installer: apps.install / list / uninstall / launch, the
grokbot-webapp launcher, the shipped System monitor and system.resources."""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile

import test_grokbotd as tg

SYSMON = os.path.join(tg.SF, "usr", "share", "grokbot", "webapps", "sysmon")
WEBAPP_BIN = os.path.join(tg.SF, "usr", "local", "bin", "grokbot-webapp")
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8"/></svg>')


def bundle(root, name="Jotter", gid=None, scopes=("audio",), extra=None):
    os.makedirs(root, exist_ok=True)
    man = {"name": name, "start_url": "/index.html", "icons": [{"src": "icon.svg", "sizes": "any"}],
           "grokbot": {"name_ko": "메모", "scopes": list(scopes)}}
    if gid:
        man["grokbot"]["id"] = gid
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(man, f)
    with open(os.path.join(root, "index.html"), "w") as f:
        f.write("<!doctype html><title>jotter</title><script src=app.js></script>")
    with open(os.path.join(root, "app.js"), "w") as f:
        f.write("console.log(1)")
    with open(os.path.join(root, "icon.svg"), "w") as f:
        f.write(ICON)
    for k, v in (extra or {}).items():
        with open(os.path.join(root, k), "w") as f:
            f.write(v)
    return root


class Site(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class InstallerTests(tg.Base):
    @classmethod
    def setUpClass(cls):
        cls.side = tempfile.TemporaryDirectory()
        fake = os.path.join(cls.side.name, "fake-webapp")
        with open(fake, "w") as f:
            f.write('#!/bin/bash\necho "$* sock=${SWAYSOCK:-none} wl=${WAYLAND_DISPLAY:-none}" >>"%s/launch.log"\n' % cls.side.name)
        os.chmod(fake, 0o755)
        os.environ["GROKBOT_WEBAPP_BIN"] = fake
        try:
            super().setUpClass()
        finally:
            del os.environ["GROKBOT_WEBAPP_BIN"]
        # a "remote" site on loopback: page + manifest + icon
        site = os.path.join(cls.side.name, "site")
        os.makedirs(site)
        with open(os.path.join(site, "index.html"), "w") as f:
            f.write('<html><head><title>Weather</title><link rel="manifest" href="/app.webmanifest"></head></html>')
        with open(os.path.join(site, "app.webmanifest"), "w") as f:
            json.dump({"name": "Weather Now", "short_name": "Weather", "start_url": "/?pwa=1",
                       "icons": [{"src": "/i.svg", "sizes": "any", "type": "image/svg+xml"}],
                       "grokbot": {"scopes": ["location"]}}, f)
        with open(os.path.join(site, "i.svg"), "w") as f:
            f.write(ICON)
        handler = lambda *a, **k: Site(*a, directory=site, **k)  # noqa: E731
        cls.site = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        cls.site_port = cls.site.server_address[1]
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()
        cls.site.server_close()
        super().tearDownClass()
        cls.side.cleanup()

    def setUp(self):
        for f in ("consent.log", "consent-answer", os.path.join("cfg", "grokbot", "api-grants.json")):
            try:
                os.unlink(os.path.join(self.tmp.name, f))
            except FileNotFoundError:
                pass

    def answer(self, a):
        with open(os.path.join(self.tmp.name, "consent-answer"), "w") as f:
            f.write(a + "\n")

    def prompts(self):
        try:
            with open(os.path.join(self.tmp.name, "consent.log")) as f:
                return [json.loads(x) for x in f if x.strip()]
        except FileNotFoundError:
            return []

    def data(self, *p):
        return os.path.join(self.tmp.name, "data", *p)

    def get(self, host, path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers={"Host": host})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def origin_rpc(self, origin, method, params=None):
        return self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                         {"Origin": origin})

    def install(self, **p):
        self.answer("once")
        return self.rpc_unix("apps.install", p)

    # ---- install a bundle ----

    def test_bundle_install_serve_launcher_and_no_grants(self):
        src = bundle(os.path.join(self.side.name, "jotter-src"))
        r = self.install(path=src)
        self.assertIn("result", r, r)
        a = r["result"]
        origin = "http://jotter.app.localhost:%d" % self.port
        self.assertEqual((a["id"], a["origin"], a["source"], a["scopes"]), ("jotter", origin, "bundle", ["audio"]))
        self.assertTrue(a["icon_data"].startswith("data:image/svg+xml;base64,"))
        p = self.prompts()[-1]
        self.assertEqual((p["scope"], p["method"], p["allow_always"]), ("apps", "apps.install", False))
        self.assertEqual(p["summary"]["origin"], origin)
        self.assertEqual(p["summary"]["requests_scopes"], "audio")
        self.assertIsNone(p["warning"])
        # files are copied, served on the app's own origin with the CSP
        code, h, body = self.get("jotter.app.localhost:%d" % self.port, "/")
        self.assertEqual(code, 200)
        self.assertIn(b"jotter", body)
        self.assertIn("worker-src 'self'", h["Content-Security-Policy"])
        self.assertIn("manifest-src 'self'", h["Content-Security-Policy"])
        self.assertTrue(os.path.isfile(self.data("grokbot", "webapps", "jotter", "app.js")))
        # launcher entry (launcher + dock), never the desktop
        with open(self.data("applications", "grokbot-webapp-jotter.desktop")) as f:
            d = f.read()
        self.assertIn("Exec=/usr/local/bin/grokbot-webapp jotter\n", d)
        self.assertIn("StartupWMClass=grokbot-webapp-jotter\n", d)
        self.assertIn("Name=메모\n", d)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "Desktop")))
        # nothing granted: the app is known for CORS but its calls are denied
        st, hd, body = self.origin_rpc(origin, "audio.status")
        self.assertEqual(body["error"]["code"], -32001)
        self.assertEqual(hd.get("Access-Control-Allow-Origin"), origin)
        n = len(self.prompts())
        st, hd, _ = self.http("/v1/rpc", None, {"Origin": origin, "Access-Control-Request-Method": "POST"}, "OPTIONS")
        self.assertEqual(st, 204)
        # per-scope grant through the prompt
        self.answer("always")
        r = self.origin_rpc(origin, "permissions.request", {"scope": "audio", "reason": "volume"})[2]
        self.assertEqual(r["result"]["mode"], "allow")
        self.assertEqual(len(self.prompts()), n + 1)
        self.assertIn("result", self.origin_rpc(origin, "audio.status")[2])
        self.assertEqual(self.origin_rpc(origin, "network.status")[2]["error"]["code"], -32001)
        # listed
        lst = self.rpc_unix("apps.list", {"include_launchers": False})["result"]["webapps"]
        self.assertIn("jotter", [x["id"] for x in lst])
        # uninstall removes files, launcher, profile and grants
        prof = self.data("grokbot", "webapp-profiles", "jotter")
        os.makedirs(prof)
        self.answer("once")
        r = self.rpc_unix("apps.uninstall", {"id": "jotter"})["result"]
        self.assertEqual(r["revoked"], ["audio"])
        for p in (self.data("applications", "grokbot-webapp-jotter.desktop"), prof,
                  self.data("grokbot", "webapps", "jotter"), self.data("grokbot", "installed", "webapp.jotter.json")):
            self.assertFalse(os.path.exists(p), p)
        self.assertEqual(self.get("jotter.app.localhost:%d" % self.port, "/")[0], 404)
        self.assertEqual(self.http("/v1/rpc", None, {"Origin": origin, "Access-Control-Request-Method": "POST"},
                                   "OPTIONS")[0], 403)

    def test_denied_install_writes_nothing(self):
        src = bundle(os.path.join(self.side.name, "deny-src"), name="Nope")
        self.answer("deny")
        r = self.rpc_unix("apps.install", {"path": src})
        self.assertEqual(r["error"]["code"], -32001)
        self.assertFalse(os.path.exists(self.data("grokbot", "webapps", "nope")))
        self.assertFalse(os.path.exists(self.data("applications", "grokbot-webapp-nope.desktop")))
        e = [x for x in self.audit() if x.get("method") == "apps.install"][-1]
        self.assertEqual((e["decision"], e.get("consent")), ("deny", "deny"))

    def test_zip_bundle_and_keep_data(self):
        src = bundle(os.path.join(self.side.name, "zip-src", "todo"), name="Todo", gid="todo2")
        z = os.path.join(self.side.name, "todo.zip")
        with zipfile.ZipFile(z, "w") as zf:
            for n in os.listdir(src):
                zf.write(os.path.join(src, n), "todo/" + n)
        r = self.install(path=z)
        self.assertEqual(r["result"]["id"], "todo2", r)
        self.answer("once")
        self.assertTrue(self.rpc_unix("apps.uninstall", {"id": "todo2", "keep_data": True})["result"]["data_kept"])

    def test_bad_bundles_are_refused(self):
        bad = {
            "dot": {".env": "x"},
            "ext": {"run.sh": "rm -rf ~"},
        }
        for n, extra in bad.items():
            src = bundle(os.path.join(self.side.name, "bad-" + n), name="Bad " + n, extra=extra)
            r = self.install(path=src)
            self.assertEqual(r["error"]["code"], -32000, (n, r))
        link = bundle(os.path.join(self.side.name, "bad-link"), name="Link")
        os.symlink("/etc/passwd", os.path.join(link, "p.txt"))
        self.assertEqual(self.install(path=link)["error"]["code"], -32000)
        z = os.path.join(self.side.name, "evil.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"name": "Evil"}))
            zf.writestr("../../escape.html", "x")
        self.assertIn("unsafe path", self.install(path=z)["error"]["message"])
        self.assertEqual(self.install(path=bundle(os.path.join(self.side.name, "sys"), gid="sysmon"))["error"]["code"],
                         -32000)  # cannot shadow a system app
        self.assertEqual(self.install(path=bundle(os.path.join(self.side.name, "set"), gid="settings"))["error"]["code"],
                         -32000)
        self.assertEqual(self.install(path=bundle(os.path.join(self.side.name, "sc"), name="Sc", scopes=["*"]))
                         ["error"]["code"], -32000)  # no blanket scope
        self.assertEqual(self.install(path=src, url="https://x")["error"]["code"], -32000)
        self.assertEqual(self.rpc_unix("apps.install", {"path": src, "id": "../x"})["error"]["code"], -32602)
        self.assertFalse(os.path.exists(os.path.join(self.side.name, "escape.html")))

    # ---- install a URL ----

    def test_url_install_reads_manifest_and_icon(self):
        url = "http://127.0.0.1:%d/" % self.site_port
        r = self.install(url=url)
        self.assertIn("result", r, r)
        a = r["result"]
        self.assertEqual((a["id"], a["name"], a["source"]), ("weather", "Weather Now", "url"))
        self.assertEqual(a["origin"], "http://127.0.0.1:%d" % self.site_port)
        self.assertEqual(a["start_url"], url + "?pwa=1")
        self.assertEqual(a["scopes"], ["location"])
        self.assertTrue(a["icon_data"])
        p = self.prompts()[-1]
        self.assertIn(a["origin"], p["description"][0])
        self.assertIn(a["origin"], p["warning"][0])
        self.assertIn("receives every permission", p["warning"][1])
        # the remote origin is now known for CORS, with no grants
        st, hd, body = self.origin_rpc(a["origin"], "system.info")
        self.assertEqual(body["error"]["code"], -32001)
        self.assertEqual(hd.get("Access-Control-Allow-Origin"), a["origin"])
        out = subprocess.run([WEBAPP_BIN, "weather"], env=dict(self.env, GROKBOT_WEBAPP_PRINT="1"),
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), url + "?pwa=1", out.stderr)
        self.answer("once")
        self.rpc_unix("apps.uninstall", {"id": "weather"})

    def test_url_rules(self):
        for u in ("http://example.com/", "file:///etc/passwd", "ftp://x/", "javascript:alert(1)"):
            self.assertEqual(self.install(url=u)["error"]["code"], -32000, u)

    # ---- system apps, launch, launcher script ----

    def test_sysmon_is_a_system_app(self):
        lst = {a["id"]: a for a in self.rpc_unix("apps.list", {"include_launchers": False})["result"]["webapps"]}
        s = lst["sysmon"]
        self.assertTrue(s["system"])
        self.assertEqual(s["name_ko"], "시스템 모니터")
        self.assertEqual(s["scopes"], ["audit", "network", "power", "system"])
        self.assertEqual(s["origin"], "http://sysmon.app.localhost:%d" % self.port)
        self.answer("once")
        self.assertEqual(self.rpc_unix("apps.uninstall", {"id": "sysmon"})["error"]["code"], -32000)
        self.assertEqual(self.prompts(), [])
        # shipped with no grants: it must ask per scope
        st, _, body = self.origin_rpc(s["origin"], "system.resources")
        self.assertEqual(body["error"]["code"], -32001)
        code, h, body = self.get("sysmon.app.localhost:%d" % self.port, "/sw.js")
        self.assertEqual((code, h["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        code, h, _ = self.get("sysmon.app.localhost:%d" % self.port, "/manifest.json")
        self.assertEqual(code, 200)
        with open(os.path.join(tg.SF, "usr", "share", "applications", "grokbot-webapp-sysmon.desktop")) as f:
            self.assertIn("Exec=/usr/local/bin/grokbot-webapp sysmon", f.read())

    def test_example_apps_are_system_apps(self):
        lst = {a["id"]: a for a in self.rpc_unix("apps.list", {"include_launchers": False})["result"]["webapps"]}
        want = {"files": ("파일", ["files", "files-write"]), "notes": ("메모", []),
                "player": ("미디어 플레이어", ["mediakeys"])}
        for gid, (ko, scopes) in want.items():
            a = lst[gid]
            self.assertTrue(a["system"], gid)
            self.assertEqual((a["name_ko"], sorted(a["scopes"])), (ko, scopes))
            host = "%s.app.localhost:%d" % (gid, self.port)
            for f in ("/", "/app.js", "/sw.js", "/style.css", "/%s.css" % gid, "/icon.svg"):
                self.assertEqual(self.get(host, f)[0], 200, (gid, f))
            with open(os.path.join(tg.SF, "usr", "share", "applications", "grokbot-webapp-%s.desktop" % gid)) as f:
                self.assertIn("Exec=/usr/local/bin/grokbot-webapp %s" % gid, f.read())
            # shipped with no grants
            body = self.origin_rpc(a["origin"], "files.list")[2]
            self.assertEqual(body["error"]["code"], -32001)

    def test_launch(self):
        log = os.path.join(self.side.name, "launch.log")
        # grokbotd starts before sway exports SWAYSOCK/WAYLAND_DISPLAY: the
        # launched app must still get the live session's sockets.
        run = self.env["XDG_RUNTIME_DIR"]
        sock = os.path.join(run, "sway-ipc.1000.42.sock")
        for p in (sock, os.path.join(run, "wayland-1"), os.path.join(run, "wayland-1.lock")):
            open(p, "w").close()
        self.addCleanup(lambda: [os.unlink(p) for p in (sock, os.path.join(run, "wayland-1"), os.path.join(run, "wayland-1.lock"))])
        r = self.rpc_unix("apps.launch", {"id": "sysmon"})
        self.assertEqual(r["result"]["app_id"], "grokbot-webapp-sysmon")
        for _ in range(50):
            if os.path.exists(log):
                break
            time.sleep(0.05)
        time.sleep(0.1)
        with open(log) as f:
            line = f.read()
        self.assertIn("sysmon", line)
        self.assertIn("sock=" + sock, line)
        self.assertIn("wl=wayland-1", line)
        self.assertEqual(self.rpc_unix("apps.launch", {"id": "nope"})["error"]["code"], -32000)

    def test_webapp_script_print_and_usage(self):
        env = dict(self.env, GROKBOT_WEBAPP_PRINT="1")
        out = subprocess.run([WEBAPP_BIN, "sysmon"], env=env, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "http://sysmon.app.localhost:%d/" % self.port)
        self.assertEqual(subprocess.run([WEBAPP_BIN, "../x"], env=env, capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([WEBAPP_BIN, "missing"], env=env, capture_output=True).returncode, 1)

    def test_cli_apps(self):
        rc, out, err = self.cli("apps")
        self.assertEqual(rc, 0, err)
        self.assertIn("sysmon", out)
        self.assertIn("시스템 모니터", out)
        rc, _, _ = self.cli("apps", "bogus")
        self.assertEqual(rc, 2)

    def test_system_resources(self):
        self.rpc_unix("system.resources")
        time.sleep(0.6)
        r = self.rpc_unix("system.resources")["result"]
        self.assertIsNotNone(r["cpu"]["percent"])
        self.assertGreater(r["memory"]["total_bytes"], 0)
        self.assertTrue(r["disks"] and r["disks"][0]["total_bytes"] > 0)
        self.assertIsInstance(r["network"], list)


if __name__ == "__main__":
    unittest.main()
