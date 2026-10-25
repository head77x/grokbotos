#!/usr/bin/python3
"""Grok Bot OS consent prompt (GTK3 + layer-shell, overlay layer).

grokbotd runs this when a caller's mode for a scope is "ask". The request
arrives as JSON on stdin; the answer is printed on stdout:
  once | always | deny
Esc, closing, or no answer within the timeout means deny. "always" is
offered only when the request allows it (never for camera, microphone,
power or permission changes). The prompt takes the keyboard exclusively
so nothing else can type into it, and its default button is Deny.

The text building is pure (lines()) so it can be unit-tested without GTK.
"""
import json
import sys
import time

ARM_S = 0.6


def who(req):
    p = req.get("principal") or "?"
    if p.startswith("origin:"):
        ko, en = "웹 앱 %s" % p[7:], "Web app %s" % p[7:]
    elif p.startswith("local:"):
        from grokbotd import peer
        n = peer.describe(p)
        if p.endswith(":unknown") or p.count(":") < 2:
            ko, en = "이 컴퓨터의 알 수 없는 프로그램", "An unidentified program on this computer"
        else:
            ko, en = "이 컴퓨터의 프로그램: %s" % n, "Program on this computer: %s" % n
        detail = p.split(":", 2)[2] if p.count(":") >= 2 else ""
        if detail and detail != n:
            ko += " (%s)" % detail
            en += " (%s)" % detail
    else:
        ko = en = p
    c = req.get("client")
    if c:
        ko += " · 스스로 밝힌 이름: %s" % c
        en += " · says it is: %s" % c
    return ko, en


def action(req):
    t = req.get("description") or [req.get("method"), req.get("method")]
    if isinstance(t, str):
        t = [t, t]
    params = req.get("summary") or {}
    detail = ", ".join("%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in sorted(params.items()))
    return t[0], t[1], "%s(%s)" % (req.get("method"), detail)


def lines(req):
    wk, we = who(req)
    ak, ae, call = action(req)
    return {
        "title": "권한 요청 / Permission request",
        "who": (wk, we),
        "scope": (req.get("scope_ko") or req.get("scope"), req.get("scope_en") or req.get("scope")),
        "action": (ak, ae),
        "call": call,
        "always": bool(req.get("allow_always")),
        "session": bool(req.get("allow_session")),
        "once": req.get("allow_once", True) is not False,
        "warning": req.get("warning"),
        "sensitive": req.get("scope") in ("camera", "microphone", "power", "permissions"),
    }


CSS = b"""
/* Grok Bot OS design tokens (see /usr/share/grokbot/design/tokens.css). */
@define-color gb_surface #18181b;
@define-color gb_text #f2f2f2;
@define-color gb_text2 #a3a3a3;
@define-color gb_text3 #8a8a8a;
@define-color gb_accent #2f8cff;
@define-color gb_warning #e8a33d;
@define-color gb_danger #ff6b5e;
window.grokbot-consent { background-color: rgba(0,0,0,0); }
.card { background-color: @gb_surface; border: 1px solid alpha(@gb_warning, 0.55); border-radius: 22px;
  padding: 24px 26px; color: @gb_text; }
.card.sensitive { border-color: alpha(@gb_danger, 0.7); }
.title { font-size: 20px; font-weight: bold; }
.key { color: @gb_text3; font-size: 11px; font-weight: bold; margin-top: 4px; }
.val { font-size: 15px; }
.en { color: @gb_text2; font-size: 12px; }
.call { font-family: "Noto Sans Mono", monospace; font-size: 11px; color: @gb_text3;
  background-color: rgba(255,255,255,0.05); border-radius: 8px; padding: 4px 8px; }
button { padding: 9px 16px; border-radius: 12px; background-image: none; box-shadow: none; text-shadow: none;
  color: @gb_text; background-color: rgba(255,255,255,0.08); }
button:hover { background-color: rgba(255,255,255,0.14); }
button.deny { background-color: rgba(255,255,255,0.08); color: @gb_text; }
button.allow, button.always { background-color: @gb_accent; color: #ffffff; font-weight: bold; }
button.allow:hover, button.always:hover { background-color: shade(@gb_accent, 1.1); }
button.session { background-color: alpha(@gb_accent, 0.22); color: #cfe6ff; }
entry.secret { font-size: 16px; padding: 8px 10px; border-radius: 10px; background-color: #0a0a0b;
  color: @gb_text; border: 1px solid rgba(255,255,255,0.18); }
entry.secret:focus { border-color: @gb_accent; }
.timer { color: @gb_text3; font-size: 12px; }
/* Keyboard focus must be obvious: Tab moves between Deny / Allow buttons. */
button { border: 2px solid transparent; outline: none; }
button:focus { border-color: @gb_warning; box-shadow: 0 0 0 3px alpha(@gb_warning, 0.40); }
.warn { color: @gb_warning; font-size: 14px; font-weight: bold; }
.warn-en { color: @gb_warning; font-size: 12px; }
"""


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print("deny")
        return 0
    t = lines(req)
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GLib, Gdk, Gtk, GtkLayerShell

    answer = {"v": "deny"}
    win = Gtk.Window(title="Grok Bot 권한 요청")
    win.get_style_context().add_class("grokbot-consent")
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_namespace(win, "grokbot-consent")
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.get_style_context().add_class("card")
    if t["sensitive"]:
        card.get_style_context().add_class("sensitive")
    card.set_size_request(520, -1)

    def lab(text, cls, wrap=True):
        lb = Gtk.Label(label=text, xalign=0)
        lb.set_line_wrap(wrap)
        lb.set_max_width_chars(60)
        lb.get_style_context().add_class(cls)
        card.pack_start(lb, False, False, 0)
        return lb

    # Bit, the OS character, looks up at you while it waits (code-drawn).
    head = Gtk.Box(spacing=12)
    face_area = Gtk.DrawingArea()
    face_area.set_size_request(44, 44)
    try:
        import grokbot_mascot
        born = time.monotonic()
        life = grokbot_mascot.Idle(now=born)
        anim = {"b": 0.0, "l": (0.0, -0.3)}

        def draw_face(w, cr):
            a = w.get_allocation()
            grokbot_mascot.draw(cr, min(a.width, a.height),
                                grokbot_mascot.face("alert", anim["b"], anim["l"], time.monotonic(),
                                                    time.monotonic() - born),
                                fg="#f2f2f2", bg="#18181b")
            return False

        def tick():
            anim["b"], look = life.step(time.monotonic())
            anim["l"] = (look[0], look[1] - 0.3)
            face_area.queue_draw()
            return True
        face_area.connect("draw", draw_face)
        GLib.timeout_add(60, tick)
        head.pack_start(face_area, False, False, 0)
    except ImportError:
        pass
    title = Gtk.Label(label=t["title"], xalign=0)
    title.set_line_wrap(True)
    title.get_style_context().add_class("title")
    head.pack_start(title, True, True, 0)
    card.pack_start(head, False, False, 0)
    for key, pair in (("누가 / Who", t["who"]), ("무엇을 / Scope", t["scope"]),
                      ("어떤 동작 / Action", t["action"])):
        lab(key, "key")
        lab(pair[0], "val")
        if pair[1] != pair[0]:
            lab(pair[1], "en")
    lab(t["call"], "call")
    if t["warning"]:
        w = t["warning"] if isinstance(t["warning"], list) else [t["warning"], t["warning"]]
        lab(w[0], "warn")
        if w[1] != w[0]:
            lab(w[1], "warn-en")
    timer = lab("", "timer")

    row = Gtk.Box(spacing=8)
    row.set_halign(Gtk.Align.END)

    shown = {"t": None}

    def armed():
        # Ignore input for a moment after the prompt appears, so a click or
        # key meant for the window underneath cannot answer it.
        return shown["t"] is not None and time.monotonic() - shown["t"] >= ARM_S

    def done(v):
        answer["v"] = v
        Gtk.main_quit()

    def button(label, cls, value):
        b = Gtk.Button(label=label)
        b.get_style_context().add_class(cls)
        b.connect("clicked", lambda *_: armed() and done(value))
        # Answer on press as well: on some setups (sway + absolute pointers,
        # seen in the VM) the release that completes "clicked" was lost.
        b.connect("button-press-event", lambda _w, ev: (armed() and ev.button == 1 and done(value)) or False)
        row.pack_start(b, False, False, 0)
        return b

    secret = None
    if req.get("secret"):
        # Hidden field: the text never leaves this process except as the
        # answer on stdout (a pipe to grokbotd).
        secret = Gtk.Entry()
        secret.set_visibility(False)
        secret.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        secret.set_placeholder_text("암호 / Passphrase")
        secret.get_style_context().add_class("secret")
        card.pack_start(secret, False, False, 4)

        def submit(*_):
            if armed() and secret.get_text():
                answer["secret"] = secret.get_text()
                done("once")
        secret.connect("activate", submit)

    deny = button("취소 / Cancel" if secret is not None else "거부 / Deny", "deny", "deny")
    if secret is not None:
        ok = Gtk.Button(label="잠금 해제 / Unlock")
        ok.get_style_context().add_class("allow")
        ok.connect("clicked", submit)
        row.pack_start(ok, False, False, 0)
    elif t["once"]:
        button("이번 한 번만 / Allow once", "allow", "once")
    if t["session"] and secret is None:
        button("이번 세션 동안 / This session", "session", "session")
    if t["always"] and secret is None:
        button("항상 허용 / Always allow", "always", "always")
    card.pack_start(row, False, False, 6)
    win.add(card)

    def key(_w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            done("deny")
            return True
        if not armed():
            return True  # swallow keys typed for the window underneath
        return False
    win.connect("key-press-event", key)
    win.connect("destroy", lambda *_: done("deny"))

    left = {"s": int(req.get("timeout") or 60)}

    def tick():
        left["s"] -= 1
        timer.set_text("%d초 뒤 자동 거부 / auto-deny in %ds" % (left["s"], left["s"]))
        if left["s"] <= 0:
            done("deny")
            return False
        return True
    tick()
    GLib.timeout_add_seconds(1, tick)
    def reassert():
        # Keep the exclusive keyboard grab: sway hands focus to a window that
        # maps after us unless the layer surface re-commits its mode.
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        win.present()
        return True
    GLib.timeout_add(700, reassert)

    # Arm from when the window is shown. "map-event" is not delivered for
    # layer-shell surfaces here (VM b4: every click and key was swallowed
    # because the prompt never armed), so start the clock at show_all and
    # only move it later if a map signal does arrive.
    def on_map(*_):
        if shown["t"] is None:
            shown["t"] = time.monotonic()
    win.connect("map", on_map)
    win.show_all()
    on_map()
    (secret or deny).grab_focus()
    Gtk.main()
    if secret is not None:
        print(json.dumps({"answer": answer["v"], "secret": answer.get("secret") if answer["v"] == "once" else None}),
              flush=True)
        return 0
    print(answer["v"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
