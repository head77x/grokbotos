"""Bit, the Grok Bot OS character: a rounded-square head with two pill
eyes, drawn entirely in code. Expressions are geometry, so every surface
(Dock, consent prompt, web apps via /_grokbot/mascot.js) animates the same
way. Pure functions here; cairo drawing is optional (draw()).

Coordinates are a 100x100 box. A face is a dict:
  head: (x, y, w, h, radius)    eyes: [shape, shape]    mouth: shape|None
  coat: "#rrggbb"
shape kinds: ("pill", cx, cy, w, h) ("arc", cx, cy, w, h) ("x", cx, cy, s)
             ("line", x1, y1, x2, y2) ("o", cx, cy, r)
"""
import math
import os
import random

MOODS = ("idle", "thinking", "listening", "happy", "alert", "error", "sleeping", "sad")
COATS = {"idle": "#4c8dff", "thinking": "#8b6cf6", "listening": "#3fc2a6", "happy": "#3fc2a6",
         "alert": "#f2b33d", "error": "#ff6b5e", "sleeping": "#6b7280", "sad": "#8b9bb4"}
INK = "#0a0a0b"
HEAD = (8.0, 10.0, 84.0, 80.0, 30.0)
EYE_Y, EYE_DX, EYE_W, EYE_H = 44.0, 17.0, 11.0, 22.0


def face(mood="idle", blink=0.0, look=(0.0, 0.0), t=0.0):
    """Geometry for mood. blink 0 (open)..1 (closed); look in -1..1 moves
    the eyes; t (seconds) drives the slow breathing/pulse."""
    if mood not in MOODS:
        mood = "idle"
    lx, ly = max(-1.0, min(1.0, look[0])), max(-1.0, min(1.0, look[1]))
    bob = math.sin(t * 2 * math.pi / 3.2) * 1.2
    x, y, w, h, r = HEAD
    head = (x, y + bob, w, h, r)
    cx, cy = 50.0 + lx * 7, EYE_Y + ly * 5 + bob
    ew, eh = EYE_W, EYE_H
    mouth = None
    if mood == "thinking":
        cy -= 6
        cx += 5
        eh *= 0.8
        mouth = ("line", 44, 72 + bob, 54, 71 + bob)
    elif mood == "listening":
        ew, eh = ew * 1.15, eh * 1.12
        mouth = ("o", 50, 72 + bob, 3.5 + 1.2 * abs(math.sin(t * 4)))
    elif mood == "alert":
        ew, eh = ew * 1.2, eh * 1.15
        mouth = ("o", 50, 73 + bob, 3.0)
    elif mood == "sad":
        cy += 4
        eh *= 0.75
        mouth = ("arc", 50, 76 + bob, 14, -4)
    elif mood == "sleeping":
        blink = 1.0
        cy += 4
    elif mood == "happy":
        mouth = ("arc", 50, 68 + bob, 18, 6)
    if mood == "happy":
        eyes = [("arc", cx - EYE_DX, cy, 14, -7), ("arc", cx + EYE_DX, cy, 14, -7)]
    elif mood == "error":
        eyes = [("x", cx - EYE_DX, cy, 9), ("x", cx + EYE_DX, cy, 9)]
        mouth = ("line", 42, 73 + bob, 58, 73 + bob)
    else:
        bh = max(2.5, eh * (1.0 - max(0.0, min(1.0, blink))))
        eyes = [("pill", cx - EYE_DX, cy, ew, bh), ("pill", cx + EYE_DX, cy, ew, bh)]
    return {"mood": mood, "head": head, "eyes": eyes, "mouth": mouth, "coat": COATS[mood]}


class Idle:
    """Code-driven life: random blinks every 2-6 s and an occasional
    glance. step(now) -> (blink, look). Deterministic with a seeded rng."""

    def __init__(self, rng=None, now=0.0):
        self.rng = rng or random.Random()
        self.next_blink = now + self.rng.uniform(2, 6)
        self.next_look = now + self.rng.uniform(4, 9)
        self.look, self.target, self.look_until = (0.0, 0.0), (0.0, 0.0), 0.0

    def step(self, now):
        blink = 0.0
        dt = now - self.next_blink
        if 0 <= dt < 0.18:
            blink = 1.0 - abs(dt - 0.09) / 0.09
        elif dt >= 0.18:
            self.next_blink = now + self.rng.uniform(2, 6)
        if now >= self.next_look:
            self.target = (self.rng.choice((-1, -0.6, 0.6, 1)), self.rng.uniform(-0.4, 0.3))
            self.look_until = now + self.rng.uniform(0.8, 1.6)
            self.next_look = now + self.rng.uniform(5, 11)
        goal = self.target if now < self.look_until else (0.0, 0.0)
        self.look = tuple(a + (b - a) * 0.25 for a, b in zip(self.look, goal))
        return blink, self.look

    def animating(self, now):
        """True while a blink or glance is in motion (redraw fast)."""
        moving = any(abs(a) > 0.02 for a in self.look) or now < self.look_until
        return moving or 0 <= now - self.next_blink < 0.2


def _cpu_busy():
    try:
        return os.getloadavg()[0] > 0.85 * (os.cpu_count() or 1)
    except OSError:
        return False


def consent_open(procfs="/proc"):
    """Is a consent prompt on screen (any grokbot_consent process)?"""
    try:
        for pid in os.listdir(procfs):
            if pid.isdigit():
                try:
                    with open(os.path.join(procfs, pid, "cmdline"), "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                if b"grokbot_consent" in data or b"grokbot-consent" in data:
                    return True
    except OSError:
        pass
    return False


def mood_for(items, consent=False, busy=False):
    """OS state -> (mood, ko, en) from Dock status items."""
    ids = {i.get("id"): i for i in items or []}
    if consent:
        return "alert", "권한 요청을 기다리고 있어요", "Waiting for your permission"
    if "inuse-microphone" in ids:
        return "listening", "마이크를 듣고 있어요", "Listening (microphone in use)"
    if "inuse-camera" in ids or "inuse-screen" in ids:
        return "alert", "카메라나 화면이 사용 중이에요", "Camera or screen in use"
    net = ids.get("network")
    if net and net.get("icon") == "network-offline-symbolic":
        return "sad", "오프라인이에요", "Offline"
    bat = ids.get("battery")
    if bat and bat.get("text", "").endswith("%"):
        try:
            if int(bat["text"].rstrip("%")) <= 15:
                return "sleeping", "배터리가 얼마 없어요", "Battery low"
        except ValueError:
            pass
    if any(i.get("alert") for i in ids.values()):
        return "alert", "확인할 것이 있어요", "Something needs a look"
    if busy:
        return "thinking", "열심히 일하는 중", "Working hard"
    return "idle", "Grok Bot", "Grok Bot"


def mood_item(items, consent=None, busy=None):
    consent = consent_open() if consent is None else consent
    busy = _cpu_busy() if busy is None else busy
    mood, ko, en = mood_for(items, consent, busy)
    return {"id": "mascot", "icon": None, "mascot": mood, "text": "",
            "tooltip": "%s / %s" % (ko, en) if ko != en else ko}


def leading(fetch):
    """Wrap a status fetch (runs in the Dock's worker thread) so its items
    are led by Bit's mood item for the current OS state."""
    def run():
        got = fetch()
        return [mood_item(got)] + list(got or [])
    return run


def _rgb(hexs):
    return tuple(int(hexs[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def _rrect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def draw(cr, size, f, ink=INK):
    """Paint face f with cairo into a size x size square at the origin."""
    cr.save()
    cr.scale(size / 100.0, size / 100.0)
    cr.set_source_rgb(*_rgb(f["coat"]))
    _rrect(cr, *f["head"])
    cr.fill()
    cr.set_source_rgb(*_rgb(ink))
    cr.set_line_cap(1)  # round
    cr.set_line_width(5)
    for s in f["eyes"] + ([f["mouth"]] if f["mouth"] else []):
        k = s[0]
        if k == "pill":
            _, cx, cy, w, h = s
            _rrect(cr, cx - w / 2, cy - h / 2, w, h, w / 2)
            cr.fill()
        elif k == "o":
            cr.arc(s[1], s[2], s[3], 0, 2 * math.pi)
            cr.fill()
        elif k == "x":
            _, cx, cy, d = s
            cr.move_to(cx - d / 2, cy - d / 2); cr.line_to(cx + d / 2, cy + d / 2)
            cr.move_to(cx + d / 2, cy - d / 2); cr.line_to(cx - d / 2, cy + d / 2)
            cr.stroke()
        elif k == "line":
            cr.move_to(s[1], s[2]); cr.line_to(s[3], s[4]); cr.stroke()
        elif k == "arc":
            _, cx, cy, w, d = s
            cr.move_to(cx - w / 2, cy); cr.curve_to(cx - w / 4, cy + d, cx + w / 4, cy + d, cx + w / 2, cy)
            cr.stroke()
    cr.restore()
