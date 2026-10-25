"""System web apps served by grokbotd (the Settings app)."""
import json
import os
import re
import subprocess
import unittest
import urllib.request

import test_grokbotd as tg

SETTINGS = os.path.join(tg.SF, "usr", "share", "grokbot", "webapps", "settings")


class WebappTests(tg.Base):
    def get(self, host, path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers={"Host": host})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_serves_settings_with_csp(self):
        host = "settings.app.localhost:%d" % self.port
        code, h, body = self.get(host, "/")
        self.assertEqual(code, 200)
        self.assertIn(b"app.js", body)
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Frame-Options"], "DENY")
        code, h, _ = self.get(host, "/app.js")
        self.assertEqual((code, h["Content-Type"]), (200, "text/javascript; charset=utf-8"))

    def test_no_traversal_or_other_hosts(self):
        host = "settings.app.localhost:%d" % self.port
        for path in ("/../../../etc/passwd", "/..%2f..%2fetc/passwd", "/.hidden", "/nope.html", "/v1/x"):
            self.assertEqual(self.get(host, path)[0], 404, path)
        self.assertEqual(self.get("127.0.0.1:%d" % self.port, "/index.html")[0], 404)
        self.assertEqual(self.get("evil.app.localhost:%d" % self.port, "/")[0], 404)
        self.assertEqual(self.get("settings.example.com:%d" % self.port, "/")[0], 403)

    def test_shared_design_system_same_origin(self):
        for app in ("settings", "files", "notes"):
            host = "%s.app.localhost:%d" % (app, self.port)
            code, h, body = self.get(host, "/_grokbot/tokens.css")
            self.assertEqual((code, h["Content-Type"]), (200, "text/css; charset=utf-8"))
            self.assertIn(b"--gb-bg", body)
            self.assertIn("style-src 'self'", h["Content-Security-Policy"])
        host = "settings.app.localhost:%d" % self.port
        self.assertEqual(self.get(host, "/_grokbot/mascot.js")[0], 200)
        for path in ("/_grokbot/../webapps/settings/app.js", "/_grokbot/", "/_grokbot/.x.css", "/_grokbot/nope.css"):
            self.assertEqual(self.get(host, path)[0], 404, path)
        self.assertEqual(self.get("evil.app.localhost:%d" % self.port, "/_grokbot/tokens.css")[0], 404)

    def test_same_origin_fetch_without_origin_header(self):
        o = "http://settings.app.localhost:%d" % self.port
        self.grant({})
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump({"origins": {o: {"audio": "allow"}}}, f)
        try:
            code, _, body = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "audio.status"},
                                      {"Host": o[7:], "Sec-Fetch-Site": "same-origin",
                                       "Cookie": "gbt=" + self.app_token(o)})
            self.assertEqual(code, 200, body)
            # without the launcher's cookie the same request is anonymous
            code, _, _ = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "audio.status"},
                                   {"Host": o[7:], "Sec-Fetch-Site": "same-origin"})
            self.assertEqual(code, 403)
            # cross-site without Origin stays anonymous
            code, _, _ = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "audio.status"},
                                   {"Host": o[7:], "Sec-Fetch-Site": "cross-site"})
            self.assertEqual(code, 403)
        finally:
            self.grant({})


class SettingsStaticTests(unittest.TestCase):
    def test_system_grant_is_minimal(self):
        with open(os.path.join(tg.SF, "etc", "grokbot", "api-permissions.json")) as f:
            d = json.load(f)
        g = d["origins"]["http://settings.app.localhost:7311"]
        for s in ("camera", "microphone", "screen", "files", "location", "windows"):
            self.assertNotIn(s, g)
        # apps: list and open; install/uninstall always prompt (test_installer)
        self.assertEqual(g["apps"], "allow")
        self.assertEqual(g["power"], "ask")
        self.assertEqual(list(d["origins"]), ["http://settings.app.localhost:7311"])

    def test_only_public_api_and_no_inline_or_innerhtml(self):
        js = open(os.path.join(SETTINGS, "app.js"), encoding="utf-8").read()
        html = open(os.path.join(SETTINGS, "index.html"), encoding="utf-8").read()
        self.assertNotIn("innerHTML", js, "use text nodes")
        self.assertNotIn("eval(", js)
        self.assertIsNone(re.search(r"<script>(?!\s*</script>)", html))
        self.assertNotIn(" on", re.sub(r"<script[^>]*src[^>]*></script>", "", html).replace("\n", " ").split("<body")[1].split(">")[0])
        with open(tg.SCHEMA) as f:
            methods = set(json.load(f)["methods"])
        used = set(re.findall(r'rpc\("([a-z_.]+)"', js))
        self.assertTrue(used)
        self.assertEqual(used - methods, set())

    def test_i18n_keys_complete(self):
        src = open(os.path.join(SETTINGS, "i18n.js"), encoding="utf-8").read()
        js = open(os.path.join(SETTINGS, "app.js"), encoding="utf-8").read()
        html = open(os.path.join(SETTINGS, "index.html"), encoding="utf-8").read()
        en = set(re.findall(r"^\s{4}([a-z_]+):", src.split("ko: {")[0], re.M)) | set(
            re.findall(r"[,{]\s*([a-z_]+):", src.split("ko: {")[0]))
        ko = set(re.findall(r"[,{\n]\s*([a-z_]+):", src.split("ko: {")[1]))
        keys = set(re.findall(r'\bt\("([a-z_]+)"\)', js)) | set(re.findall(r'data-t="([a-z_]+)"', html))
        keys |= {p + "_title" for p in ("wifi", "sound", "display", "notif", "lock", "kbd", "perm", "audit")}
        self.assertEqual(keys - en, set(), "missing English")
        self.assertEqual(keys - ko, set(), "missing Korean")

    def test_launcher_and_script(self):
        de = open(os.path.join(tg.SF, "usr", "share", "applications", "grokbot-settings.desktop")).read()
        self.assertIn("Exec=/usr/local/bin/grokbot-settings", de)
        exe = os.path.join(tg.SF, "usr", "local", "bin", "grokbot-settings")
        r = subprocess.run([exe, "permissions"], capture_output=True, text=True,
                           env=dict(os.environ, GROKBOT_SETTINGS_PRINT="1"))
        self.assertEqual(r.stdout.strip(), "http://settings.app.localhost:7311/#permissions")
        r = subprocess.run([exe, "x;rm"], capture_output=True, text=True,
                           env=dict(os.environ, GROKBOT_SETTINGS_PRINT="1"))
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()


class AppTokenTests(tg.Base):
    """Finding #3: a local process can write any Origin header."""

    def rpc(self, headers):
        return self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "audio.status"}, headers)

    def test_app_origin_needs_launcher_cookie(self):
        o = "http://settings.app.localhost:%d" % self.port
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump({"origins": {o: {"audio": "allow"}}}, f)
        try:
            self.assertEqual(self.rpc({"Origin": o})[0], 200)
            self.assertEqual(self.rpc({"Origin": o, "Cookie": "gbt=" + "0" * 64})[0], 403)
            self.assertEqual(self.rpc({"Origin": o, "Cookie": "x=1"})[0], 403)
            # a token is bound to its origin
            other = self.app_token("http://notes.app.localhost:%d" % self.port)
            self.assertEqual(self.rpc({"Origin": o, "Cookie": "gbt=" + other})[0], 403)
            ev = [e for e in self.audit_rejects() if e.get("error") == "app_token_missing"]
            self.assertTrue(ev)
        finally:
            self.grant({})

    def test_launch_url_sets_cookie_and_redirects(self):
        o = "http://settings.app.localhost:%d" % self.port
        tok = self.app_token(o)
        conn = __import__("http.client").client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/?gbt=%s&x=1" % tok, headers={"Host": o[7:]})
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 303)
        self.assertEqual(r.getheader("Location"), "/?x=1")
        c = r.getheader("Set-Cookie")
        self.assertIn("gbt=" + tok, c)
        for a in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(a, c)
        conn.request("GET", "/?gbt=bad", headers={"Host": o[7:]})
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 303)
        self.assertIsNone(r.getheader("Set-Cookie"))
        conn.close()
        key = os.path.join(self.tmp.name, "state", "grokbot", "webapp-key")
        self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)


class OriginPeerTests(tg.Base):
    """Origin from a program that is not a browser is ignored."""

    trust_peer = False

    def test_script_origin_is_anonymous(self):
        o = "http://settings.app.localhost:%d" % self.port
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump({"origins": {o: {"audio": "allow"}}}, f)
        try:
            code, h, _ = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "audio.status"}, {"Origin": o})
            self.assertEqual(code, 403)
            self.assertNotIn("Access-Control-Allow-Origin", h)
            self.assertTrue([e for e in self.audit_rejects() if e.get("error") == "origin_untrusted_peer"])
        finally:
            self.grant({})


class PeerUnitTests(unittest.TestCase):
    def test_peer_is_browser(self):
        from grokbotd import policy
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            def proc(pid, exe, root, inode):
                os.makedirs(os.path.join(d, str(pid), "fd"))
                os.symlink(exe, os.path.join(d, str(pid), "exe"))
                os.symlink(root, os.path.join(d, str(pid), "root"))
                os.symlink("socket:[%d]" % inode, os.path.join(d, str(pid), "fd", "7"))
            proc(10, "/usr/lib64/firefox/firefox", "/", 100)
            proc(11, "/usr/bin/curl", "/", 101)
            proc(12, "/app/bin/firefox", "/proc/12/root-elsewhere", 102)
            old = os.environ.pop("GROKBOT_TRUST_ANY_ORIGIN_PEER", None)
            try:
                self.assertEqual(policy.socket_owner(100, d), 10)
                self.assertTrue(policy.peer_is_browser(100, d))
                self.assertFalse(policy.peer_is_browser(101, d))
                self.assertFalse(policy.peer_is_browser(102, d))  # sandboxed
                self.assertFalse(policy.peer_is_browser(999, d))
                self.assertFalse(policy.peer_is_browser(None, d))
            finally:
                if old is not None:
                    os.environ["GROKBOT_TRUST_ANY_ORIGIN_PEER"] = old
