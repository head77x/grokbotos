#!/usr/bin/python3
"""Grok Bot OS dock: one layer-shell panel per enabled screen edge.

There are no desktop icons. The only app surfaces besides windows are
these docks and the fuzzel launcher.

Config (later files override earlier keys):
  /etc/grokbot/dock.conf
  ~/.config/grokbot/dock.conf   (written by grokbot-dock-config)

  [dock]
  top = off | icons
  bottom = off | icons
  left = off | icons | labels
  right = off | icons | labels
  icon_size = 40
  hide = footclient.desktop;foot-server.desktop
  status = auto | off | top | bottom | left | right

top/bottom are icon-only: "labels" there is treated as "icons".
SIGHUP (or grokbot-dock-config) reloads the config.
"""
import configparser
import json
import os
import shlex
import signal
import subprocess
import sys
import threading

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grokbot_status  # noqa: E402
import grokbot_mascot  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gio, GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

GROKBOT_DESKTOP = "grok-bot.desktop"
GROKBOT_APP_ID = "grok-bot"
EDGES = ("top", "bottom", "left", "right")
SYS_CONF = os.environ.get("GROKBOT_DOCK_SYS_CONF", "/etc/grokbot/dock.conf")
USER_CONF = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "grokbot", "dock.conf")

CSS = b"""
/* Grok Bot OS design tokens (see /usr/share/grokbot/design/tokens.css). */
window.grokbot-dock { background-color: rgba(18,18,20,0.92); }
.grokbot-dock button { background: none; border: none; box-shadow: none; background-image: none;
  padding: 5px; margin: 3px 2px; border-radius: 12px; color: #f2f2f2;
  transition: background-color 140ms cubic-bezier(.22,1,.36,1); }
.grokbot-dock button:hover { background-color: rgba(255,255,255,0.08); }
.grokbot-dock button.focused { background-color: rgba(255,255,255,0.14); }
.grokbot-dock .dot { color: rgba(0,0,0,0); font-size: 7px; }
.grokbot-dock button.running .dot { color: #64b5ff; }
.grokbot-dock label.name { padding-left: 8px; padding-right: 8px; }
.grokbot-dock .status { margin: 0 8px; }
.grokbot-dock .status button { padding: 3px 5px; margin: 2px 1px; border-radius: 10px; }
.grokbot-dock .status button.mascot { padding: 1px 3px; }
.grokbot-dock .status label { font-size: 13px; padding: 0 2px; color: rgba(255,255,255,0.86); }
.grokbot-dock .status button.alert { background-color: #e5484d; color: #ffffff; }
.grokbot-dock .sep { background-color: rgba(255,255,255,0.10); min-width: 1px; min-height: 1px; }
"""


def load_config():
    cp = configparser.ConfigParser()
    cp.read([SYS_CONF, USER_CONF])
    d = cp["dock"] if cp.has_section("dock") else {}
    conf = {}
    for e in EDGES:
        v = str(d.get(e, "icons" if e == "bottom" else "off")).strip().lower()
        if v not in ("off", "icons", "labels"):
            v = "off"
        if e in ("top", "bottom") and v == "labels":
            v = "icons"
        conf[e] = v
    try:
        conf["icon_size"] = max(16, min(96, int(d.get("icon_size", "40"))))
    except ValueError:
        conf["icon_size"] = 40
    conf["hide"] = {h.strip() for h in
                    str(d.get("hide", "footclient.desktop;foot-server.desktop")).split(";")
                    if h.strip()}
    st = str(d.get("status", "auto")).strip().lower()
    conf["status"] = st if st in ("auto", "off") + EDGES else "auto"
    return conf


def swaymsg(*args):
    try:
        out = subprocess.run(["swaymsg", "-r", *args], capture_output=True,
                             text=True, timeout=5)
        return out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def views(node, acc):
    if node.get("type") in ("con", "floating_con") and node.get("pid") \
            and not node.get("nodes") and not node.get("floating_nodes"):
        acc.append(node)
    for k in ("nodes", "floating_nodes"):
        for c in node.get(k, []):
            views(c, acc)
    return acc


def window_key(v):
    app_id = v.get("app_id")
    if not app_id:
        app_id = (v.get("window_properties") or {}).get("class") or ""
    return app_id.lower()


def app_keys(info):
    keys = set()
    did = (info.get_id() or "").lower()
    if did.endswith(".desktop"):
        did = did[:-8]
    if did:
        keys.add(did)
        keys.add(did.split(".")[-1])
    wm = info.get_string("StartupWMClass") if hasattr(info, "get_string") else None
    if wm:
        keys.add(wm.lower())
    exe = info.get_executable() or ""
    if exe:
        keys.add(os.path.basename(exe).lower())
    if info.get_id() == GROKBOT_DESKTOP:
        keys.add(GROKBOT_APP_ID)
    return keys


def app_list(hide):
    apps = [a for a in Gio.AppInfo.get_all()
            if a.should_show() and a.get_id() not in hide]
    apps.sort(key=lambda a: (a.get_id() != GROKBOT_DESKTOP,
                             (a.get_display_name() or "").lower()))
    if not any(a.get_id() == GROKBOT_DESKTOP for a in apps):
        g = Gio.DesktopAppInfo.new(GROKBOT_DESKTOP)
        if g is not None:
            apps.insert(0, g)
    return apps


def new_workspace():
    try:
        wss = json.loads(swaymsg("-t", "get_workspaces") or "[]")
    except ValueError:
        wss = []
    used = {w.get("num") for w in wss}
    n = 2
    while n in used:
        n += 1
    return n


def launch(info):
    if info.get_id() == GROKBOT_DESKTOP:
        # grokbot-kiosk keeps Grok Bot running on workspace 1.
        swaymsg("workspace number 1")
        return
    cmd = "gtk-launch " + shlex.quote(info.get_id()[:-8] if info.get_id().endswith(".desktop") else info.get_id())
    # sway puts windows from `exec` on the workspace that was focused
    # when exec ran, so each app opens alone and fills the usable area.
    swaymsg(f"workspace number {new_workspace()}; exec {cmd}")


def monitors():
    """Gdk monitors, the one at the origin (sway's primary layout spot) first."""
    disp = Gdk.Display.get_default()
    mons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())]
    if not mons:
        return [None]
    return sorted(mons, key=lambda m: (m.get_geometry().x, m.get_geometry().y))


class Dock:
    def __init__(self):
        self.windows = {}
        self.windows_monitors = []
        self.buttons = []  # (button, keys, info)
        self.status_box = None
        self.status_mode = None
        self.status_widgets = {}
        self.status_pages = {}
        self.conf = load_config()
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self.rebuild())
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        add_signal = getattr(GLib, "unix_signal_add")
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGHUP, self.reload)
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        # One dock per output; rebuild when outputs come and go.
        disp = Gdk.Display.get_default()
        disp.connect("monitor-added", lambda *_: GLib.idle_add(self._rebuild_once))
        disp.connect("monitor-removed", lambda *_: GLib.idle_add(self._rebuild_once))
        self.rebuild()
        GLib.timeout_add(1500, self.refresh)
        GLib.timeout_add_seconds(2, self.refresh_status)

    def quit(self):
        Gtk.main_quit()
        return False

    def reload(self):
        self.conf = load_config()
        self.rebuild()
        return True

    def _rebuild_once(self):
        # Only when the set of outputs really changed (Wayland announces the
        # existing outputs at startup too).
        if len(monitors()) != len(getattr(self, "windows_monitors", [])):
            self.rebuild()
        return False

    def rebuild(self):
        for w in self.windows.values():
            w.destroy()
        self.windows = {}
        self.buttons = []
        self.status_box = None
        self.status_widgets = {}
        apps = app_list(self.conf["hide"])
        self.windows_monitors = monitors()
        for i, mon in enumerate(self.windows_monitors):
            for edge in EDGES:
                mode = self.conf[edge]
                if mode != "off":
                    # status indicators only on the primary (first) output
                    self.windows[(i, edge)] = self.make_window(edge, mode, apps, mon, primary=(i == 0))
        self.refresh()
        self.refresh_status()

    def make_window(self, edge, mode, apps, mon=None, primary=True):
        win = Gtk.Window()
        win.get_style_context().add_class("grokbot-dock")
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "grokbot-dock")
        if mon is not None and len(self.windows_monitors) > 1:
            # Pin to an output only with several; with one, let the
            # compositor place it (unchanged single-screen behaviour).
            GtkLayerShell.set_monitor(win, mon)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
        e = {"top": GtkLayerShell.Edge.TOP, "bottom": GtkLayerShell.Edge.BOTTOM,
             "left": GtkLayerShell.Edge.LEFT, "right": GtkLayerShell.Edge.RIGHT}
        GtkLayerShell.set_anchor(win, e[edge], True)
        horiz = edge in ("top", "bottom")
        # Stretch along the edge.
        for other in (("left", "right") if horiz else ("top", "bottom")):
            GtkLayerShell.set_anchor(win, e[other], True)
        GtkLayerShell.auto_exclusive_zone_enable(win)
        orient = Gtk.Orientation.HORIZONTAL if horiz else Gtk.Orientation.VERTICAL
        box = Gtk.Box(orientation=orient, spacing=0)
        box.set_halign(Gtk.Align.CENTER if horiz else Gtk.Align.FILL)
        box.set_valign(Gtk.Align.CENTER if not horiz else Gtk.Align.FILL)
        if not horiz:
            box.set_valign(Gtk.Align.START)
            box.set_margin_top(6)
        size = self.conf["icon_size"]
        for info in apps:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            name = info.get_display_name() or info.get_id()
            btn.set_tooltip_text(name)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if horiz
                            else Gtk.Orientation.HORIZONTAL)
            img = Gtk.Image()
            icon = info.get_icon()
            if icon is not None:
                img.set_from_gicon(icon, Gtk.IconSize.DIALOG)
            else:
                img.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
            img.set_pixel_size(size)
            dot = Gtk.Label(label="●")
            dot.get_style_context().add_class("dot")
            if horiz:
                inner.pack_start(img, False, False, 0)
                inner.pack_start(dot, False, False, 0)
            else:
                inner.pack_start(dot, False, False, 0)
                inner.pack_start(img, False, False, 0)
                if mode == "labels":
                    lab = Gtk.Label(label=name, xalign=0)
                    lab.get_style_context().add_class("name")
                    # Without a width request GTK shrinks an ellipsizing
                    # label to just "...".
                    lab.set_width_chars(14)
                    lab.set_max_width_chars(18)
                    lab.set_ellipsize(3)  # Pango.EllipsizeMode.END
                    inner.pack_start(lab, True, True, 0)
            btn.add(inner)
            btn.connect("clicked", self.on_click, info)
            # GTK keeps a tooltip up after a click while the pointer stays
            # still, and the window it belonged to has moved on. Drop it on
            # click and allow it again once the pointer leaves.
            # Tooltips start off and come back only on real pointer motion,
            # so a dock rebuilt (config reload) under a still pointer does
            # not pop one up either.
            btn.set_has_tooltip(False)
            btn.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
            btn.connect("motion-notify-event", self.on_motion)
            box.pack_start(btn, False, False, 0)
            self.buttons.append((btn, app_keys(info), info))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC if horiz else Gtk.PolicyType.NEVER,
                            Gtk.PolicyType.NEVER if horiz else Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_width(True)
        scroller.set_propagate_natural_height(True)
        scroller.add(box)
        if primary and grokbot_status.status_edge(self.conf) == edge:
            # Status area at the END of the dock: right end of a top/bottom
            # dock, bottom end of a left/right dock.
            outer = Gtk.Box(orientation=orient, spacing=0)
            outer.pack_start(scroller, True, True, 0)
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL if horiz
                                else Gtk.Orientation.HORIZONTAL)
            sep.get_style_context().add_class("sep")
            outer.pack_start(sep, False, False, 4)
            self.status_box = Gtk.Box(orientation=orient, spacing=0)
            self.status_box.get_style_context().add_class("status")
            self.status_mode = (horiz, mode)
            outer.pack_end(self.status_box, False, False, 0)
            win.add(outer)
        else:
            win.add(scroller)
        win.show_all()
        return win

    def refresh_status(self):
        """Timer (2 s), rebuild and clicks: ask the worker for fresh items
        and redraw now with the last ones (fresh clock). Never blocks the
        main loop and always stays armed."""
        if not hasattr(self, "poller"):
            self.status_items = []
            self.poller = grokbot_status.Poller(
                grokbot_mascot.leading(grokbot_status.items), lambda res: GLib.idle_add(self._status_ready, res))
        self.poller.request()
        try:
            self.apply_status(self.status_items)
        except Exception as e:  # noqa: BLE001 - a bad item must not stop the timer
            print("dock status: %s" % e, file=sys.stderr)
        return True

    def _status_ready(self, res):
        if res is not None:
            self.status_items = res
        try:
            self.apply_status(self.status_items)
        except Exception as e:  # noqa: BLE001
            print("dock status: %s" % e, file=sys.stderr)
        return False

    def apply_status(self, fetched):
        if self.status_box is None:
            return
        horiz, mode = self.status_mode
        size = max(16, min(24, self.conf["icon_size"] // 2))
        items = grokbot_status.with_clock(fetched)
        live = {i["id"] for i in items}
        self.status_pages = {i["id"]: i.get("page") for i in items}
        for sid, (b, _i, _l) in self.status_widgets.items():
            b.set_visible(sid in live)
        for pos, item in enumerate(items):
            w = self.status_widgets.get(item["id"])
            if w is None and item["id"] == "mascot":
                w = self.status_widgets["mascot"] = self.make_mascot(size + 6)
            if item["id"] == "mascot":
                btn = w[0]
                btn.set_visible(True)
                self.status_box.reorder_child(btn, pos)
                self.mascot_mood = item.get("mascot", "idle")
                btn.set_tooltip_text(item["tooltip"])
                continue
            if w is None:
                btn = Gtk.Button()
                btn.set_relief(Gtk.ReliefStyle.NONE)
                inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if (horiz or mode == "labels")
                                else Gtk.Orientation.VERTICAL, spacing=4)
                img = Gtk.Image()
                lab = Gtk.Label()
                if item["icon"]:
                    inner.pack_start(img, False, False, 0)
                # Top/bottom and left/right "icons": icon only, except the
                # clock, which is its text. Left/right "labels": icon + text.
                if item["icon"] is None or mode == "labels":
                    inner.pack_start(lab, False, False, 0)
                btn.add(inner)
                btn.connect("clicked", self.on_status_click, item["id"])
                btn.add_events(Gdk.EventMask.SCROLL_MASK)
                btn.connect("scroll-event", self.on_status_scroll, item["id"])
                self.status_box.pack_start(btn, False, False, 0)
                btn.show_all()
                w = self.status_widgets[item["id"]] = (btn, img, lab)
            btn, img, lab = w
            btn.set_visible(True)
            self.status_box.reorder_child(btn, pos)
            ctx = btn.get_style_context()
            if item.get("alert"):
                ctx.add_class("alert")
            else:
                ctx.remove_class("alert")
            if item["icon"]:
                img.set_from_icon_name(item["icon"], Gtk.IconSize.BUTTON)
                img.set_pixel_size(size)
            lab.set_text(item["text"] if (horiz or mode == "labels" or item["icon"] is None) else "")
            if item["id"] == "clock" and not horiz and mode != "labels":
                lab.set_text(item["text"].replace(":", "\n"))
            # Every dock, including icon-only top/bottom: the label lives
            # in the tooltip (충전 중, 전원 연결됨, 전원 연결됨 (가득 참), NN%).
            btn.set_tooltip_text(item["tooltip"])

    def make_mascot(self, px):
        """Bit in the status area: a DrawingArea animated in code."""
        import time
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.get_style_context().add_class("mascot")
        area = Gtk.DrawingArea()
        area.set_size_request(px, px)
        btn.add(area)
        btn.connect("clicked", self.on_status_click, "mascot")
        self.mascot_mood = "idle"
        life = grokbot_mascot.Idle(now=time.monotonic())
        state = {"b": 0.0, "l": (0.0, 0.0), "t": 0.0, "alive": True,
                 "mood": "idle", "since": time.monotonic()}

        def on_draw(_w, cr):
            a = area.get_allocation()
            sz = min(a.width, a.height)
            cr.translate((a.width - sz) / 2, (a.height - sz) / 2)
            # Dark Dock: light body, eyes in the Dock colour (theme inverse).
            f = grokbot_mascot.face(self.mascot_mood, state["b"], state["l"], state["t"],
                                    state["t"] - state["since"])
            grokbot_mascot.draw(cr, sz, f, fg="#f2f2f2", bg="#121214", fit=True)
            return False

        def tick():
            if not state["alive"]:
                return False
            now = time.monotonic()
            state["b"], state["l"] = life.step(now)
            state["t"] = now
            if self.mascot_mood != state["mood"]:   # new state: spring in again
                state["mood"], state["since"] = self.mascot_mood, now
            area.queue_draw()   # the face always wobbles gently
            return True
        area.connect("draw", on_draw)
        area.connect("destroy", lambda *_: state.update(alive=False))
        GLib.timeout_add(60, tick)
        self.status_box.pack_start(btn, False, False, 0)
        btn.show_all()
        return (btn, None, None)

    def on_status_click(self, _btn, sid):
        if sid == "mascot":
            subprocess.Popen(["/usr/local/bin/grokbot-focus"])
        elif sid == "network":
            wired = getattr(self, "status_pages", {}).get("network") == "network"
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "network" if wired else "wifi"])
        elif sid == "vpn":
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "network"])
        elif sid == "bluetooth":
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "bluetooth"])
        elif sid == "storage":
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "storage"])
        elif sid in ("brightness", "nightlight"):
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "display"])
        elif sid == "printing":
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "printers"])
        elif sid in ("power-mode", "battery"):
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "power"])
        elif sid.startswith("inuse-"):
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "permissions"])
        elif sid == "mic-muted":
            subprocess.Popen(["/usr/local/bin/grokbot-volume", "mic-mute"])
        elif sid == "volume":
            subprocess.Popen(["/usr/local/bin/grokbot-volume", "mute"])
        elif sid == "update":
            subprocess.Popen(["/usr/local/bin/grokbot-settings", "update"])
        GLib.timeout_add(400, self.refresh_status_once)

    def on_status_scroll(self, _btn, event, sid):
        if sid not in ("volume", "brightness"):
            return False
        up = event.direction == Gdk.ScrollDirection.UP or (
            event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y < 0)
        if sid == "brightness":
            threading.Thread(target=grokbot_status.brightness_step, args=(up,), daemon=True).start()
        else:
            subprocess.Popen(["/usr/local/bin/grokbot-volume", "up" if up else "down"])
        GLib.timeout_add(300, self.refresh_status_once)
        return True

    def refresh_status_once(self):
        self.refresh_status()
        return False

    def current_views(self):
        try:
            return views(json.loads(swaymsg("-t", "get_tree") or "{}"), [])
        except ValueError:
            return []

    def on_motion(self, btn, _event):
        if not btn.get_has_tooltip():
            btn.set_has_tooltip(True)
        return False

    def hide_tooltips(self):
        for btn, _keys, _info in self.buttons:
            btn.set_has_tooltip(False)

    def on_click(self, btn, info):
        btn.set_has_tooltip(False)
        keys = app_keys(info)
        for v in self.current_views():
            if window_key(v) in keys:
                swaymsg(f"[con_id={v['id']}] focus")
                return
        launch(info)

    def refresh(self):
        vs = self.current_views()
        running = {window_key(v) for v in vs}
        focused = {window_key(v) for v in vs if v.get("focused")}
        # The focused window changed (click, Alt+Tab, Alt+G): drop any
        # tooltip left over from before.
        if focused != getattr(self, "_last_focused", None):
            self._last_focused = focused
            self.hide_tooltips()
        for btn, keys, _info in self.buttons:
            ctx = btn.get_style_context()
            for cls, on in (("running", bool(keys & running)),
                            ("focused", bool(keys & focused))):
                if on:
                    ctx.add_class(cls)
                else:
                    ctx.remove_class(cls)
        return True


def main():
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("grokbot-dock: WAYLAND_DISPLAY is not set", file=sys.stderr)
        return 1
    Dock()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
