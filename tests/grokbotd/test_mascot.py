"""Bit, the code-drawn character: moods, OS-state mapping, idle life, and
the web (mascot.js) and native (grokbot_mascot.py) copies agreeing."""
import json
import os
import random
import re
import unittest

import helpers
import grokbot_mascot as m

JS = os.path.join(helpers.SF, "usr/share/grokbot/design/mascot.js")


class MascotTest(unittest.TestCase):
    def test_every_mood_has_geometry_inside_the_box(self):
        for mood in m.MOODS:
            f = m.face(mood, blink=0.5, look=(1, -1), t=1.3)
            self.assertEqual(f["mood"], mood)
            self.assertEqual(len(f["eyes"]), 2)
            x, y, w, h, _r = f["head"]
            self.assertTrue(0 <= x and x + w <= 100 and 0 <= y and y + h <= 100, mood)
        self.assertEqual(m.face("nope")["mood"], "idle")
        self.assertEqual(m.face("error")["eyes"][0][0], "x")
        self.assertEqual(m.face("happy")["eyes"][0][0], "arc")
        # sleeping eyes are closed lines; idle eyes open
        self.assertLess(m.face("sleeping")["eyes"][0][4], 3)
        self.assertGreater(m.face("idle")["eyes"][0][4], 20)

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
        for mood, coat in m.COATS.items():
            self.assertIn('%s: "%s"' % (mood, coat), js)
        self.assertNotIn("innerHTML", js)
        for app in ("files", "notes", "settings"):
            html = open(os.path.join(helpers.SF, "usr/share/grokbot/webapps", app, "index.html"), encoding="utf-8").read()
            self.assertIn('src="/_grokbot/mascot.js"', html, app)


if __name__ == "__main__":
    unittest.main()
