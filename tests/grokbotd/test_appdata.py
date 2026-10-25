"""appdata.*: each installed web app reads and writes only its own folder."""
import json
import os
import sys
import unittest

import test_grokbotd as tg
from test_installer import bundle

sys.path.insert(0, tg.LIB)
from grokbotd import appdata, backends  # noqa: E402


class AppDataTests(tg.Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        side = os.path.join(cls.tmp.name, "src")
        for gid in ("todo", "other"):
            bundle(os.path.join(side, gid), name=gid.title(), gid=gid, scopes=("app-data",))
            cls.answer_s(cls, "once")
            r = cls.rpc_unix(cls, "apps.install", {"path": os.path.join(side, gid)})
            assert "result" in r, r

    def answer_s(self, a):
        with open(os.path.join(self.tmp.name, "consent-answer"), "w") as f:
            f.write(a + "\n")

    def origin(self, gid):
        return "http://%s.app.localhost:%d" % (gid, self.port)

    def call(self, gid, method, params=None):
        o = self.origin(gid)
        tok = self.app_token(o)
        st, _, body = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                                {"Origin": o, "Cookie": "gbt=" + tok})
        return body

    def folder(self, gid):
        return os.path.join(self.env["XDG_DATA_HOME"], "grokbot", "app-data", gid)

    def prompts_count(self):
        p = os.path.join(self.tmp.name, "consent.log")
        return open(p).read().count("\n\n") if os.path.exists(p) else 0

    def test_write_read_list_delete_without_prompt(self):
        n = self.prompts_count()
        w = self.call("todo", "appdata.write", {"path": "todos.json", "data": json.dumps({"t": "우유 사기"}, ensure_ascii=False)})
        self.assertIn("result", w, w)
        self.assertEqual(self.prompts_count(), n, "app-data must not prompt")
        with open(os.path.join(self.folder("todo"), "todos.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["t"], "우유 사기")
        self.assertEqual(os.stat(self.folder("todo")).st_mode & 0o777, 0o700)
        r = self.call("todo", "appdata.read", {"path": "/todos.json"})["result"]
        self.assertIn("우유", r["data"])
        self.assertIn("result", self.call("todo", "appdata.write", {"path": "a/b/c.txt", "data": "x"}))
        ls = self.call("todo", "appdata.list", {"path": "/"})["result"]
        self.assertLessEqual({"todos.json", "a"}, {e["name"] for e in ls["entries"]})
        self.assertNotIn("error", self.call("todo", "appdata.delete", {"path": "a", "recursive": True}))
        self.assertFalse(os.path.exists(os.path.join(self.folder("todo"), "a")))
        self.assertIn("error", self.call("todo", "appdata.write", {"path": "todos.json", "data": "y", "overwrite": False}))

    def test_other_app_cannot_see_it(self):
        self.call("todo", "appdata.write", {"path": "secret.txt", "data": "todo only"})
        r = self.call("other", "appdata.read", {"path": "secret.txt"})
        self.assertIn("error", r)
        self.assertIn("no such file", r["error"]["message"])
        for bad in ("../todo/secret.txt", "/../todo/secret.txt", "a/../../todo/secret.txt", "..", "./x",
                    "//etc/passwd", "a\\..\\b", "x\x00y"):
            r = self.call("other", "appdata.read", {"path": bad})
            self.assertIn("error", r, bad)
            self.assertNotIn("todo only", json.dumps(r))

    def test_symlink_escape_is_refused(self):
        self.call("other", "appdata.write", {"path": "seed.txt", "data": "s"})
        d = self.folder("other")
        os.symlink(self.folder("todo"), os.path.join(d, "link"))
        os.symlink("/etc/hostname", os.path.join(d, "f"))
        self.call("todo", "appdata.write", {"path": "secret.txt", "data": "todo only"})
        for m, p in (("appdata.read", {"path": "link/secret.txt"}), ("appdata.read", {"path": "f"}),
                     ("appdata.write", {"path": "link/x", "data": "pwn"}), ("appdata.write", {"path": "f", "data": "pwn"}),
                     ("appdata.list", {"path": "link"})):
            r = self.call("other", m, p)
            self.assertIn("error", r, (m, p, r))
        self.assertFalse(os.path.exists(os.path.join(self.folder("todo"), "x")))
        # deleting a link removes the link only
        self.assertNotIn("error", self.call("other", "appdata.delete", {"path": "link"}))
        self.assertTrue(os.path.exists(os.path.join(self.folder("todo"), "secret.txt")))

    def test_non_apps_are_denied(self):
        r = self.rpc_unix("appdata.list", {})
        self.assertIn("error", r)
        st, _, body = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "appdata.list", "params": {}},
                                {"Origin": "http://evil.example"})
        self.assertNotEqual(st, 200)

    def test_user_deny_wins(self):
        self.answer_s("once")
        o = "origin:" + self.origin("other")
        self.assertIn("result", self.rpc_unix("permissions.set", {"principal": o, "scope": "app-data", "mode": "deny"}))
        try:
            self.assertEqual(self.call("other", "appdata.list")["error"]["code"], -32001)
        finally:
            self.answer_s("once")
            self.rpc_unix("permissions.revoke", {"principal": o, "scope": "app-data"})
        self.assertIn("result", self.call("other", "appdata.list"))

    def test_uninstall_removes_data_unless_kept(self):
        side = os.path.join(self.tmp.name, "src")
        for gid, keep in (("gone", False), ("kept", True)):
            bundle(os.path.join(side, gid), name=gid, gid=gid, scopes=("app-data",))
            self.answer_s("once")
            self.assertIn("result", self.rpc_unix("apps.install", {"path": os.path.join(side, gid)}))
            self.assertIn("result", self.call(gid, "appdata.write", {"path": "d.json", "data": "{}"}))
            self.answer_s("once")
            self.assertIn("result", self.rpc_unix("apps.uninstall", {"id": gid, "keep_data": keep}))
            self.assertEqual(os.path.exists(self.folder(gid)), keep, gid)


class PathTests(unittest.TestCase):
    def test_size_and_quota_limits(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"XDG_DATA_HOME": t}), \
                mock.patch.object(appdata, "app_for", return_value={"id": "todo"}), \
                mock.patch.object(appdata, "MAX_FILE", 10), mock.patch.object(appdata, "MAX_TOTAL", 25):
            ctx = {"principal": "origin:http://todo.app.localhost:7311"}
            appdata.appdata_write({"path": "a", "data": "x" * 10}, ctx)
            with self.assertRaises(backends.BackendError):
                appdata.appdata_write({"path": "b", "data": "x" * 11}, ctx)
            appdata.appdata_write({"path": "b", "data": "x" * 10}, ctx)
            with self.assertRaises(backends.BackendError):
                appdata.appdata_write({"path": "c", "data": "x" * 10}, ctx)


    def test_parts(self):
        self.assertEqual(appdata.parts("/"), [])
        self.assertEqual(appdata.parts("a//b/"), ["a", "b"])
        for bad in ("..", "a/..", "../x", ".", "a/./b", "a\\b", "a\x00", "//x", "x" * 256):
            with self.assertRaises(backends.BackendError, msg=bad):
                appdata.parts(bad)


if __name__ == "__main__":
    unittest.main()
