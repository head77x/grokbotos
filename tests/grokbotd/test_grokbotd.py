"""grokbotd phase 1 tests: schema, policy, transports, audit, CLI, MCP.

Runs the real daemon in a temporary XDG tree with a fake sway IPC socket.
"""
import json
import re
import os
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SF = os.path.join(ROOT, "system_files")
LIB = os.path.join(SF, "usr", "lib", "grokbot")
SCHEMA = os.path.join(SF, "usr", "share", "grokbot", "api", "os-api.schema.json")
CLI = os.path.join(SF, "usr", "local", "bin", "grokbot-os")
DAEMON = os.path.join(SF, "usr", "local", "bin", "grokbotd")
sys.path.insert(0, LIB)

TREE = {"type": "root", "nodes": [{"type": "output", "name": "Virtual-1", "nodes": [
    {"type": "workspace", "name": "1", "nodes": [
        {"type": "con", "id": 10, "app_id": "grok-bot", "name": "Grok Bot", "pid": 100,
         "focused": True, "fullscreen_mode": 0, "nodes": [], "floating_nodes": []}],
     "floating_nodes": []},
    {"type": "workspace", "name": "2", "nodes": [
        {"type": "con", "id": 11, "app_id": "foot", "name": "foot", "pid": 101,
         "focused": False, "fullscreen_mode": 0, "nodes": [], "floating_nodes": []}],
     "floating_nodes": []}]}], "floating_nodes": []}
WORKSPACES = [{"name": "1", "num": 1, "output": "Virtual-1", "focused": True, "visible": True},
              {"name": "2", "num": 2, "output": "Virtual-1", "focused": False, "visible": False}]


class FakeSway(socketserver.StreamRequestHandler):
    def handle(self):
        hdr = self.rfile.read(14)
        n, t = struct.unpack("=II", hdr[6:])
        self.rfile.read(n)
        body = json.dumps(TREE if t == 4 else WORKSPACES).encode()
        self.wfile.write(b"i3-ipc" + struct.pack("=II", len(body), t) + body)


FAKE_TOOLS = {
    # Answer comes from $HOME/consent-answer (default deny); the request is logged.
    "fake-consent": 'cat >>"$HOME/consent.log"; echo >>"$HOME/consent.log"; '
                    '[[ -f $HOME/consent-delay ]] && sleep 1; cat "$HOME/consent-answer" 2>/dev/null || echo deny',
    "fake-capture": 'mkdir -p "$HOME/shots"; f="$HOME/shots/screenshot-test.png"; '
                    'printf PNG >"$f"; echo "$f"',
    "systemctl": "exit 0",
    "wpctl": 'if [[ $1 == get-volume ]]; then echo "Volume: 0.30"; fi',
    "brightnessctl": "exit 0",
    "makoctl": "exit 0",
    "fcitx5-remote": "exit 0",
    "pkill": "exit 0",
    "notify-send": "exit 0",
    "nmcli": 'case "$*" in *"wifi list"*) printf "*:Home\\:Net:80:WPA2:wlan0\\n:Cafe:40::wlan0\\n:Cafe:60::wlan0\\n";; '
             '*"passwd-file"*) for a; do [[ -f $a ]] && cat "$a" >>"$HOME/pwfile.seen"; done;; '
             '*"-f DEVICE,TYPE,STATE"*) printf "wlan0:wifi:connected\\neth0:ethernet:unavailable\\n";; esac',
}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Base(unittest.TestCase):
    trust_peer = True
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = cls.tmp.name
        cls.port = free_port()
        env = dict(os.environ)
        for k in ("SWAYSOCK", "WAYLAND_DISPLAY"):
            env.pop(k, None)
        env.update({
            "HOME": t, "XDG_RUNTIME_DIR": os.path.join(t, "run"),
            "XDG_CONFIG_HOME": os.path.join(t, "cfg"), "XDG_STATE_HOME": os.path.join(t, "state"),
            "XDG_DATA_HOME": os.path.join(t, "data"), "XDG_DATA_DIRS": os.path.join(t, "share"),
            "GROKBOT_LIB": LIB, "GROKBOT_API_SCHEMA": SCHEMA,
            "GROKBOT_API_SYS_PERMISSIONS": os.path.join(SF, "etc", "grokbot", "api-permissions.json"),
            "GROKBOT_DOCK_SYS_CONF": os.path.join(SF, "etc", "grokbot", "dock.conf"),
            "GROKBOT_DESKTOP_SYS_CONF": os.path.join(SF, "etc", "grokbot", "desktop.conf"),
            "GROKBOT_API_PORT": str(cls.port),
            "GROKBOT_WEBAPPS_DIR": os.path.join(SF, "usr", "share", "grokbot", "webapps"),
            "GROKBOT_DESIGN_DIR": os.path.join(SF, "usr", "share", "grokbot", "design"),
            "GROKBOT_UPDATE_RUN": os.path.join(t, "run-update"),
            "GROKBOT_HEALTH_DIR": os.path.join(t, "health"),
            # urllib stands in for the browser; OriginPeerTests turns this off.
            "GROKBOT_TRUST_ANY_ORIGIN_PEER": "1" if cls.trust_peer else "0",
        })
        # Fake tools: the daemon must never touch the real machine in tests
        # (systemctl suspend, nmcli, wpctl ...). Each logs its argv.
        fb = os.path.join(t, "fakebin")
        os.makedirs(fb)
        for tool, body in FAKE_TOOLS.items():
            with open(os.path.join(fb, tool), "w") as f:
                f.write("#!/bin/bash\necho \"%s $*\" >>\"$HOME/tools.log\"\n%s\n" % (tool, body))
            os.chmod(os.path.join(fb, tool), 0o755)
        env["PATH"] = fb + ":" + env.get("PATH", "")
        env["GROKBOT_CONSENT_CMD"] = os.path.join(fb, "fake-consent")
        env["GROKBOT_CAPTURE_CMD"] = os.path.join(fb, "fake-capture")
        env["GROKBOT_API_GRANTS"] = os.path.join(t, "cfg", "grokbot", "api-grants.json")
        cls.env = env
        os.makedirs(env["XDG_RUNTIME_DIR"], mode=0o700)
        # user dock override, an installed app and a launcher
        os.makedirs(os.path.join(t, "cfg", "grokbot"))
        with open(os.path.join(t, "cfg", "grokbot", "dock.conf"), "w") as f:
            f.write("[dock]\nleft = labels\n")
        inst = os.path.join(t, "data", "grokbot", "installed")
        os.makedirs(inst)
        with open(os.path.join(inst, "org.example.Notes.json"), "w") as f:
            f.write('{"id":"org.example.Notes","kind":"flatpak","name":"Notes"}')
        apps = os.path.join(t, "share", "applications")
        os.makedirs(apps)
        with open(os.path.join(apps, "foot.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Foot\nExec=foot\nIcon=foot\n")
        with open(os.path.join(apps, "hidden.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=H\nExec=h\nNoDisplay=true\n")
        sway_sock = os.path.join(env["XDG_RUNTIME_DIR"], "sway-ipc.1000.1.sock")
        cls.sway = socketserver.ThreadingUnixStreamServer(sway_sock, FakeSway)
        threading.Thread(target=cls.sway.serve_forever, daemon=True).start()
        cls.proc = subprocess.Popen([DAEMON], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        cls.sock = os.path.join(env["XDG_RUNTIME_DIR"], "grokbot", "api.sock")
        for _ in range(100):
            if os.path.exists(cls.sock):
                try:
                    socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                    break
                except OSError:
                    pass
            time.sleep(0.05)
        else:
            raise RuntimeError("daemon did not start: %s" % cls.proc.stdout.read1())

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.sway.shutdown()
        cls.sway.server_close()
        cls.tmp.cleanup()

    def cli(self, *args, inp=None):
        r = subprocess.run([CLI, *args], env=self.env, capture_output=True, text=True, input=inp, timeout=20)
        return r.returncode, r.stdout, r.stderr

    def rpc_unix(self, method, params=None):
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.sock)
        f = s.makefile("rwb")
        f.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}) + "\n").encode())
        f.flush()
        r = json.loads(f.readline())
        s.close()
        return r

    def http(self, path, body=None, headers=None, method=None):
        h = {"Host": "127.0.0.1:%d" % self.port}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        o = h.get("Origin") or ""
        if re.fullmatch(r"http://[a-z0-9-]+\.app\.localhost(:\d+)?", o) and "Cookie" not in h \
                and not getattr(self, "no_app_cookie", False):
            h["Cookie"] = "gbt=" + self.app_token(o)
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            data = e.read()
            return e.code, dict(e.headers), json.loads(data) if data else None

    def app_token(self, origin):
        env = dict(os.environ, XDG_STATE_HOME=self.env["XDG_STATE_HOME"])
        return subprocess.run([sys.executable, "-m", "grokbotd.apptoken", origin], env=dict(env, PYTHONPATH=LIB),
                              capture_output=True, text=True, check=True).stdout.strip()

    def grant(self, origins):
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump({"origins": origins}, f)

    def audit_rejects(self):
        p = os.path.join(self.tmp.name, "state", "grokbot", "audit-rejects.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f]

    def audit(self):
        with open(os.path.join(self.tmp.name, "state", "grokbot", "audit.jsonl")) as f:
            return [json.loads(x) for x in f]


class SchemaTests(unittest.TestCase):
    def test_every_method_has_backend_and_known_capability(self):
        from grokbotd import backends, perms, rpc, schema
        doc = schema.load(SCHEMA)
        caps = doc["x-capabilities"]
        for name, spec in doc["methods"].items():
            self.assertIn("description", spec, name)
            self.assertEqual(spec["params"]["type"], "object", name)
            self.assertIn(spec.get("access"), ("read", "write"), name)
            if name not in rpc.SPECIAL:
                self.assertTrue(name in rpc.METHODS or name in rpc.CTX_METHODS, name)
            if spec["capability"] is not None:
                self.assertIn(spec["capability"], caps, name)
            if spec.get("scope") is not None:
                self.assertIn(spec["scope"], perms.SCOPES, name)
                self.assertIn(spec["scope"], doc["x-scopes"], name)
            self.assertEqual(len(spec.get("x-title", [])), 2, name)
        self.assertEqual(set(rpc.METHODS) | set(rpc.CTX_METHODS) | rpc.SPECIAL, set(doc["methods"]))
        self.assertEqual(set(backends.METHODS) & set(rpc.CTX_METHODS), set())

    def test_http_connections_time_out(self):
        # An idle or half-sent request must not hold a server thread forever.
        from grokbotd import server
        self.assertIsNotNone(server.HttpHandler.timeout)
        self.assertLessEqual(server.HttpHandler.timeout, 30)

    def test_validate_params(self):
        from grokbotd import schema
        spec = schema.load(SCHEMA)["methods"]["apps.list"]
        self.assertEqual(schema.validate_params(spec, None), {"include_launchers": True})
        with self.assertRaises(schema.ParamError):
            schema.validate_params(spec, {"include_launchers": "yes"})
        with self.assertRaises(schema.ParamError):
            schema.validate_params(spec, {"bogus": 1})
        with self.assertRaises(schema.ParamError):
            schema.validate_params(spec, [])

    def test_read_methods_have_read_verbs(self):
        from grokbotd import schema
        for name, spec in schema.load(SCHEMA)["methods"].items():
            verb = name.split(".")[-1]
            if spec["access"] == "read":
                # "brightness" is a read (display.brightness), not a setter.
                self.assertIn(verb, ("methods", "info", "list", "get", "status", "brightness", "whoami", "resources",
                                     "stat", "read", "wait"), name)
            else:
                self.assertNotIn(verb, ("list", "get", "status", "info"), name)

    def test_validate_ranges(self):
        from grokbotd import schema
        m = schema.load(SCHEMA)["methods"]
        for bad in ({"percent": 0}, {"percent": 101}, {"percent": True}, {}):
            with self.assertRaises(schema.ParamError):
                schema.validate_params(m["display.set_brightness"], bad)
        with self.assertRaises(schema.ParamError):
            schema.validate_params(m["power.action"], {"action": "rm -rf"})
        with self.assertRaises(schema.ParamError):
            schema.validate_params(m["network.wifi.connect"], {"ssid": ""})
        with self.assertRaises(schema.ParamError):
            schema.validate_params(m["network.wifi.connect"], {"ssid": "x" * 33})


class DaemonTests(Base):
    def test_unix_all_methods(self):
        with open(SCHEMA) as f:
            names = [n for n, s in json.load(f)["methods"].items()
                     if s.get("access") == "read" and not s["params"].get("required")]
        for m in names:
            r = self.rpc_unix(m, {"timeout": 0} if m == "media.keys.wait" else None)
            self.assertIn("result", r, (m, r))

    def test_socket_permissions(self):
        self.assertEqual(os.stat(self.sock).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(self.sock)).st_mode & 0o777, 0o700)

    def test_windows_and_workspaces_from_sway(self):
        w = self.rpc_unix("windows.list")["result"]["windows"]
        self.assertEqual([(x["app_id"], x["workspace"], x["focused"]) for x in w],
                         [("grok-bot", "1", True), ("foot", "2", False)])
        w2 = self.rpc_unix("windows.list", {"workspace": "2"})["result"]["windows"]
        self.assertEqual([x["app_id"] for x in w2], ["foot"])
        ws = self.rpc_unix("workspaces.list")["result"]["workspaces"]
        self.assertEqual([x["name"] for x in ws], ["1", "2"])

    def test_dock_merges_user_conf(self):
        d = self.rpc_unix("dock.get")["result"]
        self.assertEqual((d["bottom"], d["left"], d["icon_size"]), ("icons", "labels", 40))
        self.assertEqual(d["status"], "auto")

    def test_apps(self):
        r = self.rpc_unix("apps.list")["result"]
        self.assertEqual(r["installed"], [{"id": "org.example.Notes", "kind": "flatpak", "name": "Notes"}])
        self.assertEqual([x["desktop_id"] for x in r["launchers"]], ["foot.desktop"])
        r = self.rpc_unix("apps.list", {"include_launchers": False})["result"]
        self.assertNotIn("launchers", r)

    def test_errors(self):
        self.assertEqual(self.rpc_unix("nope.list")["error"]["code"], -32601)
        self.assertEqual(self.rpc_unix("apps.list", {"x": 1})["error"]["code"], -32602)
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.sock)
        s.sendall(b"not json\n")
        self.assertEqual(json.loads(s.makefile().readline())["error"]["code"], -32700)
        s.close()

    def test_http_health_and_schema(self):
        code, _, body = self.http("/v1/health")
        self.assertEqual((code, body["ok"]), (200, True))
        code, _, body = self.http("/v1/schema")
        self.assertIn("system.info", body["methods"])

    def test_http_deny_by_default(self):
        self.grant({})
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "system.info"}
        code, _, body = self.http("/v1/rpc", rpc)
        self.assertEqual((code, body["error"]["code"]), (403, -32001))
        code, h, body = self.http("/v1/rpc", rpc, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        code, _, _ = self.http("/v1/rpc", rpc, {"Origin": "http://evil.example"}, method="OPTIONS")
        self.assertEqual(code, 403)
        code, _, body = self.http("/v1/rpc", rpc, {"Origin": "null"})
        self.assertEqual(code, 403)

    def test_http_origin_grant_is_per_capability(self):
        o = "http://notes.app.localhost:%d" % self.port
        self.grant({o: ["system.read"]})
        try:
            rpc = {"jsonrpc": "2.0", "id": 1, "method": "system.info"}
            code, h, body = self.http("/v1/rpc", rpc, {"Origin": o})
            self.assertEqual(code, 200)
            self.assertIn("result", body)
            self.assertEqual(h.get("Access-Control-Allow-Origin"), o)
            rpc["method"] = "windows.list"
            code, _, body = self.http("/v1/rpc", rpc, {"Origin": o})
            self.assertEqual((code, body["error"]["data"]["capability"]), (403, "windows.read"))
            code, h, _ = self.http("/v1/rpc", None, {"Origin": o}, method="OPTIONS")
            self.assertEqual((code, h.get("Access-Control-Allow-Origin")), (204, o))
        finally:
            self.grant({})

    def test_http_host_and_content_type_guards(self):
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "api.methods"}
        code, _, _ = self.http("/v1/health", headers={"Host": "attacker.example:%d" % self.port})
        self.assertEqual(code, 403)
        code, _, _ = self.http("/v1/rpc", rpc, {"Content-Type": "text/plain"})
        self.assertEqual(code, 415)
        code, _, body = self.http("/v1/rpc", rpc, {"Host": "x.app.localhost:%d" % self.port})
        self.assertEqual(code, 200)
        self.assertTrue(all(not m["allowed"] for m in body["result"]["methods"] if m["capability"]))

    def test_http_binds_loopback_only(self):
        out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout
        lines = [x for x in out.splitlines() if ":%d " % self.port in x + " "]
        self.assertTrue(lines)
        self.assertTrue(all("127.0.0.1:%d" % self.port in x for x in lines), lines)

    def test_audit_records_allow_and_deny(self):
        self.rpc_unix("power.status")
        self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "network.status"},
                  {"Origin": "http://evil.example"})
        a = self.audit()
        self.assertTrue(any(e.get("method") == "power.status" and e["decision"] == "allow"
                            and e["transport"] == "unix" for e in a))
        self.assertTrue(any(e.get("method") == "network.status" and e["decision"] == "deny"
                            and e["principal"] == "origin:http://evil.example" for e in a))
        p = os.path.join(self.tmp.name, "state", "grokbot", "audit.jsonl")
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_cli(self):
        rc, out, _ = self.cli("--json", "dock.get")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["result"]["left"], "labels")
        rc, out, _ = self.cli("windows", "list", "workspace=2")
        self.assertEqual(rc, 0)
        self.assertIn("app_id: foot", out)
        rc, out, _ = self.cli("--json", "bogus.get")
        self.assertEqual(rc, 2)
        self.assertFalse(json.loads(out)["ok"])
        rc, out, _ = self.cli("methods")
        self.assertIn("network.status", out)
        rc, out, _ = self.cli("audit", "-n", "3")
        self.assertEqual(rc, 0)

    def test_cli_unreachable(self):
        env = dict(self.env, GROKBOT_API_SOCK=os.path.join(self.tmp.name, "nope.sock"))
        r = subprocess.run([CLI, "--json", "system.info"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["error"]["code"], "unreachable")

    def test_mcp(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "workspaces_list", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "apps_list", "arguments": {"bad": 1}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}},
        ]
        rc, out, err = self.cli("mcp", inp="".join(json.dumps(m) + "\n" for m in msgs))
        self.assertEqual(rc, 0, err)
        r = {x["id"]: x for x in map(json.loads, out.splitlines())}
        self.assertEqual(set(r), {1, 2, 3, 4, 5})
        self.assertEqual(r[1]["result"]["serverInfo"]["name"], "grokbot-os")
        names = {t["name"] for t in r[2]["result"]["tools"]}
        with open(SCHEMA) as f:
            expected = {m.replace(".", "_") for m in json.load(f)["methods"]} - {"api_methods"}
        self.assertEqual(names, expected)
        self.assertTrue({"system_info", "windows_list", "power_status"} <= names)
        ro = {t["name"]: t["annotations"]["readOnlyHint"] for t in r[2]["result"]["tools"]}
        self.assertTrue(ro["system_info"])
        self.assertFalse(ro["audio_set"])
        self.assertTrue([t for t in r[2]["result"]["tools"] if t["name"] == "power_action"][0]
                        ["annotations"]["destructiveHint"])
        self.assertEqual(len(r[3]["result"]["structuredContent"]["workspaces"]), 2)
        self.assertTrue(r[4]["result"]["isError"])
        self.assertEqual(r[5]["error"]["code"], -32602)


class SwayDownTests(unittest.TestCase):
    def test_windows_list_without_sway_is_backend_error(self):
        from grokbotd import backends
        with tempfile.TemporaryDirectory() as t:
            old = dict(os.environ)
            os.environ["XDG_RUNTIME_DIR"] = t
            os.environ.pop("SWAYSOCK", None)
            try:
                with self.assertRaises(backends.BackendError):
                    backends.windows_list({})
            finally:
                os.environ.clear()
                os.environ.update(old)


if __name__ == "__main__":
    unittest.main(verbosity=1)
