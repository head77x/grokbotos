"""Minimal sway (i3) IPC client. RUN_COMMAND is used only by displays.py and keyboard.py for
`output ...` commands it builds from validated parameters."""
import glob
import json
import os
import socket
import struct

from . import paths

MAGIC = b"i3-ipc"
RUN_COMMAND = 0
GET_WORKSPACES = 1
GET_OUTPUTS = 3
GET_TREE = 4
GET_INPUTS = 100


class SwayUnavailable(RuntimeError):
    pass


def socket_path():
    p = os.environ.get("SWAYSOCK")
    if p and os.path.exists(p):
        return p
    # The daemon is a systemd user service and may start before sway, so
    # SWAYSOCK is not in its environment. Find the user's live socket.
    cands = sorted(glob.glob(os.path.join(paths.runtime_dir(), "sway-ipc.*.sock")),
                   key=lambda x: os.path.getmtime(x), reverse=True)
    if not cands:
        raise SwayUnavailable("sway IPC socket not found")
    return cands[0]


def session_env():
    """os.environ plus the graphical session's SWAYSOCK and WAYLAND_DISPLAY.

    grokbotd is a systemd user service that usually starts before sway has
    imported those into the user manager, so they are missing from its own
    environment. Children that open windows or call swaymsg (grokbot-webapp,
    grokbot-run, the consent prompt, swaylock) need them, or they fail
    silently and nothing appears on screen."""
    env = dict(os.environ)
    if not (env.get("SWAYSOCK") and os.path.exists(env["SWAYSOCK"])):
        try:
            env["SWAYSOCK"] = socket_path()
        except SwayUnavailable:
            env.pop("SWAYSOCK", None)
    if not env.get("WAYLAND_DISPLAY"):
        socks = sorted(os.path.basename(p) for p in glob.glob(os.path.join(paths.runtime_dir(), "wayland-*"))
                       if not p.endswith(".lock"))
        if socks:
            env["WAYLAND_DISPLAY"] = socks[0]
    return env


def _recv(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise SwayUnavailable("sway closed the IPC socket")
        buf += chunk
    return buf


def call(msg_type, payload=b""):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(socket_path())
        s.sendall(MAGIC + struct.pack("=II", len(payload), msg_type) + payload)
        hdr = _recv(s, 14)
        if hdr[:6] != MAGIC:
            raise SwayUnavailable("bad sway IPC reply")
        length, _ = struct.unpack("=II", hdr[6:])
        return json.loads(_recv(s, length))
    except OSError as e:
        raise SwayUnavailable(str(e))
    finally:
        s.close()


def windows_from_tree(tree):
    out = []

    def walk(node, ws):
        if node.get("type") == "workspace":
            ws = node.get("name")
        kids = node.get("nodes", []) + node.get("floating_nodes", [])
        is_window = node.get("type") in ("con", "floating_con") and not kids and (
            node.get("app_id") is not None or node.get("window_properties") or node.get("pid"))
        if is_window:
            wp = node.get("window_properties") or {}
            out.append({
                "id": node.get("id"),
                "app_id": node.get("app_id") or wp.get("class"),
                "title": node.get("name"),
                "pid": node.get("pid"),
                "workspace": ws,
                "focused": bool(node.get("focused")),
                "fullscreen": bool(node.get("fullscreen_mode")),
                "floating": node.get("type") == "floating_con",
                "xwayland": node.get("shell") == "xwayland",
                "rect": node.get("rect"),
            })
        for k in kids:
            walk(k, ws)

    walk(tree, None)
    return out
