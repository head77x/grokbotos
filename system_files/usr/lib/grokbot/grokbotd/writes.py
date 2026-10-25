"""Write methods. Each runs only after rpc.py has checked the caller's
mode for the method's scope and, when needed, the user answered the
consent prompt. Backends call the same local tools the hotkeys use
(wpctl, brightnessctl, nmcli, makoctl, fcitx5-remote, grim) as the
session user; privileged actions (suspend, reboot) go through logind and
polkit via systemctl, never a root helper.

Context-aware functions take (params, ctx); ctx has principal, client.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading

from . import consent, media, notify, paths, perms, procs
from .backends import BackendError


def _run(cmd, timeout=10, what=None):
    if shutil.which(cmd[0]) is None:
        raise BackendError("%s is not installed" % cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackendError("%s timed out" % (what or cmd[0]))
    except OSError as e:
        raise BackendError("%s failed: %s" % (cmd[0], e))
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise BackendError("%s failed: %s" % (what or cmd[0], msg[-1] if msg else r.returncode))
    return r.stdout


# ---------------- audio / display ----------------

def audio_set(params):
    target = "@DEFAULT_AUDIO_SINK@" if params.get("target", "output") == "output" else "@DEFAULT_AUDIO_SOURCE@"
    if "volume_percent" not in params and "muted" not in params:
        raise BackendError("give volume_percent and/or muted")
    if "id" in params:
        # One device from audio.devices.list (must exist: never a free string).
        from . import audiodev
        audiodev.find(int(params["id"]))
        target = str(int(params["id"]))
    if "volume_percent" in params:
        _run(["wpctl", "set-volume", "-l", "1.0", target, "%d%%" % params["volume_percent"]])
    if "muted" in params:
        _run(["wpctl", "set-mute", target, "1" if params["muted"] else "0"])
    return media.audio_status({})


def display_set_brightness(params):
    if not media.display_brightness({})["available"]:
        raise BackendError("no backlight device")
    _run(["brightnessctl", "-q", "-c", "backlight", "set", "%d%%" % max(1, params["percent"])])
    return media.display_brightness({})


# ---------------- network ----------------

def _nm_split(line):
    """nmcli -t escapes ':' as '\\:' inside fields."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def wifi_list(params):
    out = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,DEVICE", "device", "wifi", "list",
                "--rescan", "yes" if params.get("rescan") else "auto"], timeout=20)
    nets, seen = [], {}
    for line in out.splitlines():
        f = _nm_split(line)
        if len(f) < 5 or not f[1]:
            continue
        n = {"ssid": f[1], "signal": int(f[2]) if f[2].isdigit() else None,
             "security": f[3] or None, "in_use": f[0].strip() == "*", "device": f[4]}
        prev = seen.get(n["ssid"])
        if prev is None:
            seen[n["ssid"]] = n
            nets.append(n)
        else:  # same SSID, several APs: keep the best / the one in use
            prev["in_use"] = prev["in_use"] or n["in_use"]
            if (n["signal"] or 0) > (prev["signal"] or 0):
                prev["signal"] = n["signal"]
    nets.sort(key=lambda n: (not n["in_use"], -(n["signal"] or 0)))
    return {"networks": nets}


def _valid_text(s):
    return s and "\n" not in s and "\r" not in s and "\0" not in s


def wifi_connect(params):
    ssid, pw = params["ssid"], params.get("password")
    if not _valid_text(ssid) or (pw is not None and pw and not _valid_text(pw)):
        raise BackendError("invalid ssid or password")
    if pw is not None and pw and not 8 <= len(pw) <= 63:
        raise BackendError("WPA password must be 8-63 characters")
    cmd = ["nmcli", "--wait", "30", "device", "wifi", "connect", ssid]
    tmp = None
    try:
        if pw:
            # Never on argv (/proc/*/cmdline is world-readable).
            fd, tmp = tempfile.mkstemp(prefix="wifi-", dir=paths.runtime_dir())
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("802-11-wireless-security.psk:%s\n" % pw)
            cmd += ["passwd-file", tmp]
        _run(cmd, timeout=40, what="wifi connect")
    finally:
        if tmp:
            os.unlink(tmp)
    return {"connected": True, "ssid": ssid}


def wifi_disconnect(params):
    dev = params.get("device")
    if dev is None:
        out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
        for line in out.splitlines():
            f = _nm_split(line)
            if len(f) >= 3 and f[1] == "wifi" and f[2] == "connected":
                dev = f[0]
                break
        if dev is None:
            raise BackendError("no connected Wi-Fi device")
    if not dev.replace("-", "").replace("_", "").isalnum():
        raise BackendError("invalid device name")
    _run(["nmcli", "device", "disconnect", dev])
    return {"disconnected": True, "device": dev}


# ---------------- notifications / input / lock ----------------

def set_dnd(params):
    if not procs.running("mako"):
        raise BackendError("notification daemon (mako) is not running")
    modes = (procs.run(["makoctl", "mode"]) or "").split()
    on = "do-not-disturb" in modes
    if params["enabled"] and not on:
        _run(["makoctl", "mode", "-a", "do-not-disturb"])
    elif not params["enabled"] and on:
        _run(["makoctl", "mode", "-r", "do-not-disturb"])
    return {"dnd": notify.notifications_list({})["dnd"]}


def input_set(params):
    if not procs.running("fcitx5"):
        raise BackendError("fcitx5 is not running")
    _run(["fcitx5-remote", "-o" if params["active"] else "-c"])
    return {"active": params["active"]}


def idle_conf_path():
    return os.path.join(paths.config_home(), "grokbot", "idle.conf")


def lock_set_idle(params):
    from . import lock
    cur = lock.lock_status({})
    so = params.get("screen_off_s", cur["screen_off_s"])
    lk = params.get("lock_s", cur["lock_s"])
    path = idle_conf_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Written by grokbotd lock.set_idle (Settings). Seconds, 0 = off.\n"
                "[idle]\nscreen_off = %d\nlock = %d\n" % (so, lk))
    os.replace(tmp, path)
    # grokbot-idle re-reads the config each time swayidle exits.
    if shutil.which("pkill"):
        subprocess.run(["pkill", "-u", str(os.getuid()), "-x", "swayidle"], capture_output=True)
    return {"screen_off_s": so, "lock_s": lk}


# ---------------- power / screen ----------------

def _later(cmd):
    def go():
        try:
            from . import sway
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=sway.session_env())
        except OSError:
            pass
    threading.Timer(0.5, go).start()


def power_action(params):
    a = params["action"]
    cmd = {"suspend": ["systemctl", "suspend"], "reboot": ["systemctl", "reboot"],
           "poweroff": ["systemctl", "poweroff"], "lock": ["/usr/local/bin/grokbot-lock"]}[a]
    if shutil.which(cmd[0]) is None and not os.access(cmd[0], os.X_OK):
        raise BackendError("%s is not available" % cmd[0])
    _later(cmd)  # reply first, then act
    return {"action": a, "scheduled": True}


def capture_screenshot(params):
    exe = os.environ.get("GROKBOT_CAPTURE_CMD") or "/usr/local/bin/grokbot-capture"
    try:
        r = subprocess.run([exe, "full"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise BackendError("screenshot failed: %s" % e)
    path = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode != 0 or not os.path.isfile(path[0]):
        raise BackendError("screenshot failed")
    return {"name": os.path.basename(path[0]), "dir": os.path.dirname(path[0]),
            "size_bytes": os.path.getsize(path[0])}


# ---------------- camera / microphone ----------------

def _session_start(kind):
    def start(params, ctx):
        return consent.session_start(kind, ctx["principal"], ctx.get("client"),
                                     params.get("purpose", ""), params.get("duration_s", 600))
    return start


def session_stop(params, ctx):
    try:
        ok = consent.session_stop(params["id"], ctx["principal"])
    except PermissionError as e:
        raise BackendError(str(e))
    if not ok:
        raise BackendError("no such session")
    return {"stopped": True}


def privacy_status(params):
    s = consent.sessions()
    return {"sessions": s, "camera": any(x["kind"] == "camera" for x in s),
            "microphone": any(x["kind"] == "microphone" for x in s)}


# ---------------- permissions / audit ----------------

def permissions_list(params, ctx=None):
    return {"scopes": {k: {"ko": v[0], "en": v[1], "always_ask": k in perms.ALWAYS_ASK,
                           "access": sorted(perms.SCOPE_ACCESS.get(k, ()))}
                       for k, v in perms.SCOPES.items()},
            "principals": perms.listing(params.get("principal"),
                                        include=(ctx or {}).get("principal"))}


def permissions_whoami(params, ctx):
    """The caller's own principal, as the daemon identified it."""
    from . import peer
    p = ctx["principal"]
    out = {"principal": p, "transport": ctx.get("transport"), "local": perms.is_local(p),
           "storable": perms.storable(p), "client_label": ctx.get("client")}
    if perms.is_local(p):
        out["name"] = peer.describe(p)
        out.update({k: v for k, v in (ctx.get("peer") or {}).items() if k in ("pid", "exe", "unit", "script")})
    return out


def permissions_set(params, ctx):
    try:
        perms.set_mode(params["principal"], params["scope"], params["mode"], by=ctx["principal"])
    except ValueError as e:
        raise BackendError(str(e))
    return {"principal": params["principal"], "scope": params["scope"], "mode": params["mode"]}


def permissions_revoke(params, ctx):
    s = params.get("scope")
    if s is not None and s not in perms.SCOPES:
        raise BackendError("unknown scope: %s" % s)
    return {"principal": params["principal"], "revoked": perms.revoke(params["principal"], s)}


def audit_list(params):
    path = paths.audit_path()
    lines = []
    from . import audit
    for p in ["%s.%d" % (path, i) for i in range(audit.GENERATIONS, 0, -1)] + [path]:
        try:
            with open(p, encoding="utf-8") as f:
                lines.extend(f.readlines())
        except OSError:
            pass
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if params.get("principal") and e.get("principal") != params["principal"]:
            continue
        if params.get("decision") and e.get("decision") != params["decision"]:
            continue
        if params.get("method") and e.get("method") != params["method"]:
            continue
        if params.get("access") and e.get("access") != params["access"]:
            continue
        out.append(e)
    limit = params.get("limit", 100)
    return {"entries": out[-limit:], "total": len(out), "path": path}


METHODS = {
    "audio.set": audio_set,
    "display.set_brightness": display_set_brightness,
    "network.wifi.list": wifi_list,
    "network.wifi.connect": wifi_connect,
    "network.wifi.disconnect": wifi_disconnect,
    "notifications.set_dnd": set_dnd,
    "power.action": power_action,
    "lock.set_idle": lock_set_idle,
    "input.set": input_set,
    "capture.screenshot": capture_screenshot,
    "privacy.status": privacy_status,
    "audit.list": audit_list,
}
def _apps_install(params, ctx):
    from . import webapps
    return webapps.public(webapps.install(params, ctx))


def _apps_uninstall(params, ctx):
    from . import webapps
    return webapps.uninstall(params, ctx)


def _apps_launch(params, ctx):
    from . import webapps
    return webapps.launch(params, ctx)


CTX_METHODS = {
    "apps.install": _apps_install,
    "apps.uninstall": _apps_uninstall,
    "apps.launch": _apps_launch,
    "camera.session.start": _session_start("camera"),
    "microphone.session.start": _session_start("microphone"),
    "media.session.stop": session_stop,
    "permissions.set": permissions_set,
    "permissions.list": permissions_list,
    "permissions.whoami": permissions_whoami,
    "permissions.revoke": permissions_revoke,
}

