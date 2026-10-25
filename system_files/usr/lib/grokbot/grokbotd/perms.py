"""Consent-based permissions, per OS function (scope), per caller.

A *principal* is who calls (policy.py):
  local:uid=N:...  same-user process on the unix socket, identified by
                   the kernel (SO_PEERCRED pid -> systemd unit, or the
                   executable and script; peer.py). Grants are bound to
                   that identity, not to what the caller says it is.
                   A bare "local:uid=N" grant (before 0.2.1) is no
                   longer applied; it is listed so it can be revoked.
  origin:<o>      a web page, by its HTTP Origin
  http:no-origin  an HTTP client without Origin (never granted anything)

A *scope* is an OS function: display, audio, network, power, input,
notifications, files, camera, microphone, location, ... (SCOPES). Every
API method belongs to exactly one scope and has an access level, read or
write (os-api.schema.json "scope"/"access").

Each principal has, per scope, a mode:
  allow  calls go through silently
  ask    every call shows the native consent prompt: deny / allow once
         (this call only) / allow for this session (until grokbotd stops:
         logout or reboot; kept in memory) / always (stored allow)
  deny   calls fail with -32001

Where modes come from, first match wins:
  1. user grants   ~/.config/grokbot/api-grants.json (written by the API:
                   permissions.set / permissions.revoke, the prompt's
                   "always", the Settings app, grokbot-os grant/revoke)
  2. system file   /etc/grokbot/api-permissions.json ("local" and
                   "origins"; the legacy list-of-capabilities form still
                   grants *read* access for those capabilities)
  3. built-in      local: read=allow, write=ask; everyone else: deny
The local user's reads are always allowed; stored modes for local only
govern writes.

There is no blanket grant: "*" and app-wide grants are not accepted.
Some scopes can never be silently written (ALWAYS_ASK): camera,
microphone and power prompt on every use session / action, whatever the
file says. Their read methods (power.status) are allowed once the scope
is granted at all (ask), and denied otherwise.
A missing or unreadable file grants nothing beyond the built-in default.
"""
import json
import os
import threading
import time

from . import paths

MODES = ("allow", "ask", "deny")

SCOPES = {
    "system": ("시스템 정보", "System information"),
    "windows": ("창과 작업 공간", "Windows and workspaces"),
    "desktop": ("독과 배경화면", "Docks and wallpaper"),
    "apps": ("앱 목록, 설치와 실행", "Apps (list, install, open)"),
    "display": ("화면 밝기", "Display"),
    "audio": ("소리", "Sound"),
    "network": ("네트워크와 Wi-Fi", "Network and Wi-Fi"),
    "bluetooth": ("블루투스", "Bluetooth"),
    "storage": ("USB와 외장 저장장치", "USB and removable storage"),
    "power": ("전원(절전, 다시 시작, 끄기)", "Power (suspend, restart, shut down)"),
    "power-mode": ("전원 모드(절전, 균형, 성능)", "Power mode (saver, balanced, performance)"),
    "printing": ("프린터와 인쇄", "Printers and printing"),
    "input": ("키보드와 한글 입력", "Keyboard and input method"),
    "notifications": ("알림과 방해 금지", "Notifications and Do Not Disturb"),
    "lock": ("화면 잠금과 대기", "Screen lock and idle"),
    "screen": ("화면 캡처", "Screen capture"),
    "app-data": ("이 앱 전용 데이터 폴더", "This app's own data folder"),
    "files": ("홈 폴더 파일 보기", "See files in your home folder"),
    "files-write": ("홈 폴더 파일 바꾸기(저장, 이름 바꾸기, 휴지통)", "Change files in your home folder (save, rename, trash)"),
    "updates": ("OS 업데이트(확인, 설치, 되돌리기)", "OS updates (check, install, roll back)"),
    "mediakeys": ("미디어 키(재생, 다음 곡)", "Media keys (play, next track)"),
    "camera": ("카메라", "Camera"),
    "microphone": ("마이크", "Microphone"),
    "location": ("위치", "Location"),
    "permissions": ("권한 관리", "Permission management"),
    "audit": ("감사 기록", "Audit log"),
}

# scope -> {"read", "write"}: which access levels have methods. Filled
# from the schema by rpc.Dispatcher; used for display only.
SCOPE_ACCESS = {}

# These never become silent: each use session / action is confirmed.
ALWAYS_ASK = frozenset({"camera", "microphone", "power", "updates"})

_lock = threading.Lock()


def grants_path():
    return os.environ.get("GROKBOT_API_GRANTS") or os.path.join(
        paths.config_home(), "grokbot", "api-grants.json")


def is_local(principal):
    base = "local:uid=%d" % os.getuid()
    return principal == base or principal.startswith(base + ":")


def storable(principal):
    """Grants can be stored for a web origin or an identified local program."""
    if principal.startswith("origin:"):
        return len(principal) > len("origin:")
    return is_local(principal) and principal.count(":") >= 2 and not principal.endswith(":unknown")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _system():
    """(local_modes, origin_modes, origin_legacy_caps) from the system file
    and the user's legacy ~/.config/grokbot/api-permissions.json."""
    local, modes, caps = {}, {}, {}
    for p in paths.permissions_paths():
        doc = _load_json(p)
        lm = doc.get("local")
        if isinstance(lm, dict):
            local.update({s: m for s, m in lm.items() if s in SCOPES and m in MODES})
        origins = doc.get("origins")
        if not isinstance(origins, dict):
            continue
        for origin, g in origins.items():
            if not isinstance(origin, str):
                continue
            if isinstance(g, list):  # phase-1 form: read capabilities
                caps.setdefault(origin, set()).update(
                    c for c in g if isinstance(c, str) and c != "*")
            elif isinstance(g, dict):
                modes.setdefault(origin, {}).update(
                    {s: m for s, m in g.items() if s in SCOPES and m in MODES})
    return local, modes, caps


def _user():
    g = _load_json(grants_path()).get("grants")
    return g if isinstance(g, dict) else {}


# "Allow for this session": in memory only, gone when grokbotd restarts
# (logout, reboot). Never for ALWAYS_ASK scopes.
_session = {}


def session_allow(principal, scope):
    if scope in ALWAYS_ASK:
        raise ValueError("%s always asks" % scope)
    with _lock:
        _session.setdefault(principal, set()).add(scope)


def session_scopes(principal):
    with _lock:
        return sorted(_session.get(principal, ()))


def mode_for(principal, scope, access, capability=None):
    """Effective mode and where it came from: (mode, source)."""
    if scope not in SCOPES:
        return "deny", "unknown_scope"
    with _lock:
        in_session = scope in _session.get(principal, ())
    if in_session and scope not in ALWAYS_ASK:
        return "allow", "session"
    if scope == "app-data":
        # Installed apps reach only their own folder (appdata.py): allowed
        # without a prompt unless the user stored a deny for that app.
        ug = _user().get(principal, {})
        if isinstance(ug, dict) and isinstance(ug.get(scope), dict) and ug[scope].get("mode") == "deny":
            return "deny", "user"
        from . import appdata
        if appdata.app_for(principal) is not None:
            return "allow", "app"
        return "deny", "default"
    if is_local(principal) and access == "read":
        # The user's own processes always read (the dock polls status);
        # a stored mode only governs writes.
        return "allow", "builtin"
    mode, source = None, None
    ug = _user().get(principal, {})
    if isinstance(ug, dict) and isinstance(ug.get(scope), dict) and ug[scope].get("mode") in MODES:
        mode, source = ug[scope]["mode"], "user"
    if mode is None:
        local, modes, caps = _system()
        if is_local(principal):
            if access == "read":
                mode, source = "allow", "builtin"
            elif scope in local:
                mode, source = local[scope], "system"
            else:
                mode, source = "ask", "builtin"
        elif principal.startswith("origin:"):
            o = principal[len("origin:"):]
            if scope in modes.get(o, {}):
                mode, source = modes[o][scope], "system"
            elif access == "read" and capability and capability in caps.get(o, set()):
                mode, source = "allow", "legacy"
    if mode is None:
        return "deny", "default"
    if mode == "allow" and scope in ALWAYS_ASK and access == "write":
        mode = "ask"
    if mode == "ask" and scope in ALWAYS_ASK and access == "read":
        # "ask" is the strongest grant these scopes can hold; their status
        # reads (power.status) must not prompt on every poll (VM b3-06).
        # Actions still prompt every time.
        mode = "allow"
    return mode, source


def origin_known(origin):
    """Origins that get CORS headers: any with a grant of any kind."""
    _, modes, caps = _system()
    if origin in modes or origin in caps:
        return True
    if ("origin:" + origin) in _user():
        return True
    from . import webapps  # installed web apps may ask for scopes
    return origin in webapps.known_origins()


def _save(grants):
    path = grants_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "grants": grants}, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def set_mode(principal, scope, mode, by):
    if scope not in SCOPES:
        raise ValueError("unknown scope: %s" % scope)
    if mode not in MODES:
        raise ValueError("mode must be allow, ask or deny")
    if mode == "allow" and scope in ALWAYS_ASK:
        raise ValueError("%s always asks; it cannot be set to allow" % scope)
    if not storable(principal):
        raise ValueError("cannot store a grant for %s (unidentified caller)" % principal)
    with _lock:
        g = _user()
        g.setdefault(principal, {})[scope] = {"mode": mode, "by": by,
                                             "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        _save(g)


def revoke(principal, scope=None):
    """Remove stored grants (and session grants). Returns the scopes removed."""
    with _lock:
        ses = _session.get(principal, set())
        gone = set(ses) if scope is None else ({scope} & ses)
        ses -= gone
        if not ses:
            _session.pop(principal, None)
        g = _user()
        cur = g.get(principal, {})
        if not isinstance(cur, dict):
            cur = {}
        removed = sorted(cur) if scope is None else ([scope] if scope in cur else [])
        for s in removed:
            del cur[s]
        if cur:
            g[principal] = cur
        else:
            g.pop(principal, None)
        if removed:
            _save(g)
        removed = sorted(set(removed) | gone)
        return removed


def listing(principal=None, include=None):
    """Every principal that has a stored or system grant, with the
    effective mode per scope (read and write)."""
    local, modes, caps = _system()
    user = _user()
    names = set(user) | {"origin:" + o for o in set(modes) | set(caps)}
    if include:
        names.add(include)
    if principal is not None:
        names = {principal}
    out = []
    for p in sorted(names):
        scopes = {}
        for s in SCOPES:
            r = mode_for(p, s, "read")
            w = mode_for(p, s, "write")
            stored = (user.get(p) or {}).get(s)
            scopes[s] = {"read": r[0], "write": w[0], "source": w[1] if w[1] != "builtin" else r[1],
                         "session": s in _session.get(p, ()),
                         "stored": stored if isinstance(stored, dict) else None}
        out.append({"principal": p, "local": is_local(p), "scopes": scopes})
    return out
