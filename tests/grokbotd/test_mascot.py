"""The code-drawn Grok Bot face: moods, OS-state mapping, idle life, and
the web (mascot.js) and native (grokbot_mascot.py) copies agreeing."""
import json
import math
import os
import random
import re
import unittest

import helpers
import grokbot_mascot as m

JS = os.path.join(helpers.SF, "usr/share/grokbot/design/mascot.js")


class MascotTest(unittest.TestCase):
    def test_official_face_geometry(self):
        # x.ai/bot avatar: viewBox 92, circle (46,46) r 27.6, pill eyes
        # 6.9 x 15.6 at x 34.0-40.9 / 51.0-58.0, y 38.2-53.8; no mouth.
        f = m.face("idle")
        self.assertEqual(f["body"], (46.0, 46.0, 27.6))
        self.assertEqual(f["scale"], 1.0)
        (lx, ly, lw, lh, lr), (rx, ry, rw, rh, rr) = f["eyes"]
        self.assertAlmostEqual(lx - lw / 2, 34.0, places=1)
        self.assertAlmostEqual(lx + lw / 2, 40.9, places=1)
        self.assertAlmostEqual(rx - rw / 2, 51.05, places=1)
        self.assertAlmostEqual(ly - lh / 2, 38.2, places=1)
        self.assertAlmostEqual(ly + lh / 2, 53.8, places=1)
        self.assertEqual((lr, rr), (0.0, 0.0))
        for mood in m.MOODS:
            g = m.face(mood, blink=0.3, look=(1, -1), t=1.3, age=0.2)
            self.assertEqual(set(g), {"mood", "body", "scale", "eyes", "dim", "label"}, mood)
            cx, cy, r = g["body"]
            self.assertTrue(abs(cx - 46) < 5 and abs(cy - 46) < 6 and r == 27.6, mood)
            self.assertTrue(0.8 < g["scale"] < 1.12, mood)
            for ex, ey, w, h, deg in g["eyes"]:   # eyes stay inside the body
                self.assertLess(math.hypot(ex - cx, ey - cy) + h / 2, r, mood)
                self.assertLessEqual(abs(deg), 18, mood)
        self.assertEqual(m.face("nope")["mood"], "idle")
        h = m.face("idle", hero=True)["eyes"][0]
        self.assertAlmostEqual(h[0] - h[2] / 2, 31.5, places=1)
        self.assertAlmostEqual(h[1] - h[3] / 2, 34.5, places=1)

    def test_states_use_eyes_and_motion_only(self):
        self.assertAlmostEqual(m.face("idle", blink=1.0)["eyes"][0][3], 3.2)   # blink 15.6 -> 3.2
        self.assertAlmostEqual(m.blink_at(0.125), 1.0)
        self.assertEqual(m.blink_at(0.25), 0.0)
        self.assertLess(m.face("sleeping")["eyes"][0][3], 3.2)                 # closed line
        self.assertGreater(m.face("listening")["eyes"][0][2], m.EYE_W)         # larger eyes
        self.assertGreater(m.face("alert")["scale"], 1.02)                     # pop
        th = m.face("thinking")["eyes"][0]
        self.assertLess(th[1], m.EYE_Y)                                        # eyes look up
        self.assertGreater(th[4], 5)                                           # and to the side
        sad = m.face("sad")["eyes"]
        self.assertGreater(sad[0][1], m.EYE_Y)                                 # droop
        self.assertGreater(sad[0][4], 0); self.assertLess(sad[1][4], 0)        # tops lean in
        self.assertLess(m.face("error")["dim"], 1)
        hops = [m.face("happy", t=k / 10)["body"][1] for k in range(10)]
        self.assertLess(min(hops), 43)                                         # hop
        self.assertLess(m.spring(0.0), 0.9); self.assertEqual(m.spring(2.0), 1.0)

    def test_os_state_to_mood(self):
        self.assertEqual(m.mood_for([])[0], "idle")
        self.assertEqual(m.mood_for([], busy=True)[0], "thinking")
        self.assertEqual(m.mood_for([{"id": "inuse-microphone", "alert": True}])[0], "listening")
        self.assertEqual(m.mood_for([{"id": "network", "icon": "network-offline-symbolic"}])[0], "sad")
        self.assertEqual(m.mood_for([{"id": "battery", "text": "9%"}])[0], "sleeping")
        self.assertEqual(m.mood_for([{"id": "battery", "text": "충전 중"}])[0], "idle")
        self.assertEqual(m.mood_for([{"id": "update", "alert": True}])[0], "alert")
        self.assertEqual(m.mood_for([{"id": "inuse-microphone"}], consent=True)[0], "alert")
        it = m.mood_item([], consent=False, busy=False)
        self.assertEqual((it["id"], it["mascot"], it["icon"]), ("mascot", "idle", None))

    def test_consent_open_scans_proc(self):
        env = helpers.Env()
        try:
            env.write("proc/12/cmdline", "/usr/bin/python3\0/usr/lib/grokbot/grokbot_consent.py\0")
            env.write("proc/13/cmdline", "bash\0")
            self.assertTrue(m.consent_open(env.path("proc")))
            os.remove(os.path.join(env.root, "proc/12/cmdline"))
            self.assertFalse(m.consent_open(env.path("proc")))
        finally:
            env.close()

    def test_idle_blinks_and_looks(self):
        life = m.Idle(rng=random.Random(4), now=0.0)
        blinks = looks = 0
        t = 0.0
        while t < 60:
            b, look = life.step(t)
            blinks += b > 0.5
            looks += abs(look[0]) > 0.3
            t += 0.03
        self.assertGreater(blinks, 5)
        self.assertGreater(looks, 5)

    def test_cairo_draw(self):
        try:
            import cairo
        except ImportError:
            self.skipTest("no pycairo")
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 48, 48)
        cr = cairo.Context(surf)
        for mood in m.MOODS:
            m.draw(cr, 48, m.face(mood))
        self.assertTrue(any(surf.get_data()))

    def test_js_and_python_agree(self):
        js = open(JS, encoding="utf-8").read()
        moods = json.loads(re.search(r"const MOODS = (\[[^\]]*\])", js).group(1))
        self.assertEqual(tuple(moods), m.MOODS)
        for name in ("CX", "CY", "R", "EYE_W", "EYE_H", "EYE_L", "EYE_R", "EYE_Y", "BLINK_H", "BLINK_S", "HERO_W", "HERO_H", "HERO_L", "HERO_R"):
            v = float(re.search(r"\b%s = ([0-9.]+)" % name, js).group(1))
            self.assertEqual(v, getattr(m, name), name)
        self.assertIn('viewBox: "0 0 92 92"', js)
        for mood, text in m.LABELS.items():
            self.assertIn('%s: "%s"' % (mood, text), js)
        src = js + open(m.__file__, encoding="utf-8").read()
        self.assertNotIn("mouth", src.replace("No mouth", ""))   # the face never has one
        self.assertNotIn("innerHTML", js)
        for app in ("files", "notes", "settings"):
            html = open(os.path.join(helpers.SF, "usr/share/grokbot/webapps", app, "index.html"), encoding="utf-8").read()
            self.assertIn('src="/_grokbot/mascot.js"', html, app)

    def test_js_face_matches_python_numerically(self):
        import shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        prog = ("global.window={matchMedia:()=>({matches:false})};global.matchMedia=window.matchMedia;"
                "require(process.argv[1]);const F=window.GBMascot.face,o={};"
                "for(const m of window.GBMascot.MOODS)for(const h of [false,true])"
                "o[m+h]=F(m,0.4,[0.7,-0.3],1.37,0.3,h);console.log(JSON.stringify(o))")
        js = json.loads(subprocess.run([node, "-e", prog, JS], capture_output=True, text=True,
                                       check=True, timeout=30).stdout)
        for mood in m.MOODS:
            for hero in (False, True):
                p = m.face(mood, 0.4, (0.7, -0.3), 1.37, 0.3, hero)
                j = js[mood + ("true" if hero else "false")]
                a = [*p["body"], p["scale"], p["dim"]] + [v for e in p["eyes"] for v in e]
                b = [*j["body"], j["scale"], j["dim"]] + [v for e in j["eyes"] for v in e]
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, places=9, msg=mood)


if __name__ == "__main__":
    unittest.main()


class ShellThemeTest(unittest.TestCase):
    def test_shell_uses_tokens(self):
        sway = open(os.path.join(helpers.SF, "etc/sway/config"), encoding="utf-8").read()
        self.assertIn("client.focused           #64b5ff", sway)
        self.assertIn("default_border none", sway)  # still no window chrome on a maximized app
        lock = open(os.path.join(helpers.BIN, "grokbot-lock"), encoding="utf-8").read()
        self.assertIn("--ring-wrong-color ff6b5eff", lock)
        self.assertIn('--font "Noto Sans CJK KR"', lock)
        for rel in ("etc/xdg/fuzzel/fuzzel.ini", "etc/xdg/foot/foot.ini"):
            txt = open(os.path.join(helpers.SF, rel), encoding="utf-8").read()
            self.assertIn("CJK KR", txt, rel)
            for v in re.findall(r"^[a-z0-9-]+=([0-9a-f]+)$", txt.split("[colors")[1].split("\n[")[0], re.M):
                self.assertIn(len(v), (6, 8), rel + " " + v)
