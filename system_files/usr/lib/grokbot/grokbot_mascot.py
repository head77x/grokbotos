"""The Grok Bot OS face, drawn in code after the x.ai/bot avatar guideline:
a flat circle (viewBox 0 0 92 92, centre 46,46, r 27.6) with two vertical
pill eyes in the background colour. No mouth, brows or limbs, ever. Every
state is told by eye shape/tilt and body motion only.

face(mood, blink, look, t, age) -> dict
  body: (cx, cy, r)            scale: float (applied about the body centre)
  eyes: [(cx, cy, w, h, deg), (cx, cy, w, h, deg)]   rotation about own centre
  dim:  0..1 opacity of the body (sad/error look dimmer)
Colours are not baked in: the body is the foreground ink and the eyes the
background, so the face inverts with the theme (draw(fg=, bg=)).
"""
import math
import os
import random

MOODS = ("idle", "thinking", "listening", "happy", "alert", "error", "sleeping", "sad")
VIEW = 92.0
CX, CY, R = 46.0, 46.0, 27.6
EYE_W, EYE_H = 6.9, 15.6
EYE_L, EYE_R, EYE_Y = 37.45, 54.5, 46.0   # x 34.0-40.9 / 51.0-58.0, y 38.2-53.8
BLINK_H = 3.2
# The large hero avatar on x.ai/bot draws bigger eyes (measured from the
# page at 253 px: x 31.5-42.2 / 50.0-60.7, y 34.5-57.5). hero=True uses them.
HERO_W, HERO_H, HERO_L, HERO_R = 10.7, 23.0, 36.85, 55.35
BLINK_S = 0.25
INK, PAPER = "#0a0a0a", "#ffffff"
COATS = {"orange": "#F19D38", "teal": "#54B9A6", "purple": "#885CF5",
         "blue": "#3C82F6", "red": "#EA4045"}
LABELS = {"idle": "", "thinking": "생각 중… / Thinking…", "listening": "듣는 중… / Listening…",
          "happy": "완료 / Done", "alert": "확인이 필요합니다 / Needs you",
          "error": "문제가 생겼습니다 / Something went wrong", "sleeping": "절전 / Resting",
          "sad": "연결 안 됨 / Offline"}


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def spring(age):
    """Settle-on-appear scale factor: 0.85 -> overshoot -> 1."""
    if age is None or age >= 1.2:
        return 1.0
    a = max(0.0, age)
    return 1.0 - 0.15 * math.exp(-6.0 * a) * math.cos(12.0 * a)


def face(mood="idle", blink=0.0, look=(0.0, 0.0), t=0.0, age=None, hero=False):
    """Geometry for mood. blink 0 (open)..1 (closed, eye h 3.2); look x/y in
    -1..1 (eyes lean/rotate toward x, body follows); t seconds drives the
    wobble; age seconds since the face appeared (spring settle)."""
    if mood not in MOODS:
        mood = "idle"
    lx, ly = _clamp(look[0]), _clamp(look[1])
    sc = 1.0 + 0.03 * math.sin(t * 2 * math.pi / 3.2)       # gentle pulse
    bx = 0.8 * math.sin(t * 0.9) + lx * 2.0                 # body leans with eyes
    by = 0.8 * math.sin(t * 1.3)
    ew, eh, edy, spread, tilt = EYE_W, EYE_H, ly * 2.0, 0.0, 0.0
    el, er = EYE_L, EYE_R
    if hero:
        ew, eh, el, er = HERO_W, HERO_H, HERO_L, HERO_R
    rot = lx * 12.0
    dim = 1.0
    if mood == "thinking":       # eyes up to the side, slow wobble
        lx, ly = 0.8, -0.7
        rot = 12.0 + 3.0 * math.sin(t * 1.1)
        edy = -3.0
        bx = 2.0 + 1.2 * math.sin(t * 0.7)
        sc = 1.0 + 0.02 * math.sin(t * 2 * math.pi / 4.5)
    elif mood == "listening":    # eyes a touch larger, gentle pulse
        ew, eh = ew * 1.12, eh * 1.1
        sc = 1.0 + 0.04 * math.sin(t * 2 * math.pi * 1.2)
    elif mood == "alert":        # quick pop, eyes wide
        ew, eh = ew * 1.18, eh * 1.12
        sc = 1.05 + 0.025 * math.sin(t * 2 * math.pi * 1.6)
        spread = 0.8
    elif mood == "sleeping":     # eyes a thin line, slow breathing
        blink = 1.0
        rot = 0.0
        lx = 0.0
        edy = 2.0
        sc = 1.0 + 0.04 * math.sin(t * 2 * math.pi / 4.5)
        bx, by = 0.0, 1.2 * math.sin(t * 2 * math.pi / 4.5)
    elif mood in ("sad", "error"):   # eyes droop and tilt down, dimmer
        edy, eh, tilt, rot, lx = 3.0, eh * 0.82, 14.0, 0.0, 0.0
        by += 1.5
        dim = 0.55 if mood == "error" else 0.7
        if mood == "error":
            bx = 1.2 * math.sin(t * 14.0) * max(0.0, math.cos(t * 0.8))
    elif mood == "happy":        # bouncy hop
        by = -4.0 * abs(math.sin(math.pi * t * 1.6))
        eh *= 0.94
    sc *= spring(age)
    closed = BLINK_H * (HERO_H / EYE_H if hero else 1.0)
    if mood != "sleeping":
        b = _clamp(blink, 0.0, 1.0)
        eh = eh - (eh - closed) * b
    else:
        eh = closed * 0.75
    ex = lx * 3.5
    eyes = [(el - spread + ex, EYE_Y + edy, ew, eh, rot + tilt),
            (er + spread + ex, EYE_Y + edy, ew, eh, rot - tilt)]
    return {"mood": mood, "body": (CX + bx, CY + by, R), "scale": sc, "eyes": eyes,
            "dim": dim, "label": LABELS[mood]}


def blink_at(dt):
    """Blink amount dt seconds into a blink: symmetric sine ease over 250ms."""
    if dt < 0 or dt >= BLINK_S:
        return 0.0
    return math.sin(math.pi * dt / BLINK_S)


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
        if 0 <= dt < BLINK_S:
            blink = blink_at(dt)
        elif dt >= BLINK_S:
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
        return moving or 0 <= now - self.next_blink < BLINK_S + 0.02


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


def draw(cr, size, f, fg=INK, bg=PAPER, shadow=None):
    """Paint face f with cairo into a size x size square at the origin.
    fg is the body, bg the eyes (swap them on a dark surface). shadow
    defaults on for large faces, like the official large avatar."""
    if shadow is None:
        shadow = size >= 64
    cx, cy, r = f["body"]
    cr.save()
    cr.scale(size / VIEW, size / VIEW)
    cr.translate(cx, cy)
    cr.scale(f["scale"], f["scale"])
    cr.translate(-cx, -cy)
    if shadow:
        for i in range(6, 0, -1):
            cr.set_source_rgba(0, 0, 0, 0.035)
            cr.arc(cx, cy + 3.0, r + i * 0.9, 0, 2 * math.pi)
            cr.fill()
    cr.push_group()
    cr.set_source_rgb(*_rgb(fg))
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(*_rgb(bg))
    for ex, ey, w, h, deg in f["eyes"]:
        cr.save()
        cr.translate(ex, ey)
        cr.rotate(math.radians(deg))
        _rrect(cr, -w / 2, -h / 2, w, h, w / 2)
        cr.fill()
        cr.restore()
    cr.pop_group_to_source()
    cr.paint_with_alpha(f["dim"])
    cr.restore()
