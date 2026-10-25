"""The native consent prompt and camera/microphone use sessions.

prompt() runs the GTK layer-shell dialog (grokbot-consent) as a child
process and waits for the user's answer: "once", "always" or "deny".
One prompt at a time; a prompt that is not answered in TIMEOUT seconds,
or that cannot be shown (no Wayland session), counts as "deny".
The request text is passed on stdin as JSON, never on the command line.
"""
import json
import os
import subprocess
import threading
import time
import uuid

from . import perms

TIMEOUT = 60
SECRET_TIMEOUT = 120
SESSION_MAX_S = 3600
_prompt_lock = threading.Lock()
_pending_lock = threading.Lock()
_pending = {}
_sessions = {}
_sess_lock = threading.Lock()


def _cmd():
    c = os.environ.get("GROKBOT_CONSENT_CMD")
    return c.split() if c else ["/usr/local/bin/grokbot-consent"]


def _env():
    from . import sway
    return sway.session_env()


def prompt(principal, client, scope, method, description, summary, allow_always,
           allow_session=False, allow_once=True, warning=None):
    """Returns (answer, detail). answer in once|always|deny.

    Identical requests that arrive while one is waiting for the user share
    its answer instead of queueing one prompt each (a polling page used to
    pile up dozens; VM b3)."""
    key = json.dumps([principal, scope, method, summary, bool(allow_always), bool(allow_session)],
                     sort_keys=True, default=str)
    with _pending_lock:
        ev = _pending.get(key)
        if ev is None:
            ev = _pending[key] = {"event": threading.Event(), "answer": None}
            owner = True
        else:
            owner = False
    if not owner:
        ev["event"].wait(TIMEOUT + 10)
        return ev["answer"] or ("deny", "timeout")
    try:
        ev["answer"] = _prompt(principal, client, scope, method, description, summary, allow_always,
                               allow_session, allow_once, warning)
        return ev["answer"]
    finally:
        with _pending_lock:
            _pending.pop(key, None)
        ev["event"].set()


def _prompt(principal, client, scope, method, description, summary, allow_always,
            allow_session=False, allow_once=True, warning=None):
    ko, en = perms.SCOPES.get(scope, (scope, scope))
    req = {"principal": principal, "client": client, "scope": scope, "scope_ko": ko, "scope_en": en,
           "method": method, "description": description, "summary": summary,
           "allow_always": bool(allow_always), "allow_session": bool(allow_session),
           "allow_once": bool(allow_once), "warning": warning, "timeout": TIMEOUT}
    with _prompt_lock:
        try:
            r = subprocess.run(_cmd(), input=json.dumps(req, ensure_ascii=False), capture_output=True,
                               text=True, timeout=TIMEOUT + 5, env=_env())
        except subprocess.TimeoutExpired:
            return "deny", "timeout"
        except OSError:
            return "deny", "no_prompt"
    ans = (r.stdout or "").strip().splitlines()[-1:] or [""]
    ans = ans[0]
    if r.returncode != 0 or ans not in ("once", "session", "always", "deny"):
        return "deny", "no_prompt" if r.returncode != 0 else "bad_answer"
    # Never trust the prompt process to widen what was offered.
    if ans == "always" and not allow_always:
        ans = "session" if allow_session else "once"
    if ans == "session" and not allow_session:
        ans = "once"
    if ans == "once" and not allow_once:
        ans = "deny"
    return ans, "user"


def secret_prompt(principal, client, scope, method, description, summary, warning):
    """The consent prompt with a hidden text field (e.g. a drive passphrase).
    Returns (answer, detail, secret). answer is "once" or "deny"; secret is
    only set for "once". The secret comes back on the prompt's stdout pipe
    (never argv, env or a file) and is not logged by anyone."""
    ko, en = perms.SCOPES.get(scope, (scope, scope))
    req = {"principal": principal, "client": client, "scope": scope, "scope_ko": ko, "scope_en": en,
           "method": method, "description": description, "summary": summary,
           "allow_always": False, "allow_session": False, "allow_once": True, "secret": True,
           "warning": warning, "timeout": SECRET_TIMEOUT}
    with _prompt_lock:
        try:
            r = subprocess.run(_cmd(), input=json.dumps(req, ensure_ascii=False), capture_output=True,
                               text=True, timeout=SECRET_TIMEOUT + 5, env=_env())
        except subprocess.TimeoutExpired:
            return "deny", "timeout", None
        except OSError:
            return "deny", "no_prompt", None
    if r.returncode != 0:
        return "deny", "no_prompt", None
    try:
        out = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return "deny", "bad_answer", None
    if not isinstance(out, dict) or out.get("answer") != "once":
        return "deny", "user", None
    secret = out.get("secret")
    if not isinstance(secret, str) or not secret:
        return "deny", "user", None
    return "once", "user", secret


# ---------------- camera / microphone sessions ----------------

def _expire():
    now = time.time()
    for k in [k for k, s in _sessions.items() if s["expires"] <= now]:
        del _sessions[k]


def session_start(kind, principal, client, purpose, duration_s):
    duration_s = max(10, min(SESSION_MAX_S, int(duration_s)))
    sid = uuid.uuid4().hex[:16]
    with _sess_lock:
        _expire()
        _sessions[sid] = {"id": sid, "kind": kind, "principal": principal, "client": client,
                          "purpose": purpose, "started": time.time(),
                          "expires": time.time() + duration_s}
        return _public(_sessions[sid])


def session_stop(sid, principal):
    with _sess_lock:
        _expire()
        s = _sessions.get(sid)
        if s is None:
            return False
        if s["principal"] != principal and not perms.is_local(principal):
            raise PermissionError("not your session")
        del _sessions[sid]
        return True


def sessions():
    with _sess_lock:
        _expire()
        return [_public(s) for s in sorted(_sessions.values(), key=lambda s: s["started"])]


def _public(s):
    return {"id": s["id"], "kind": s["kind"], "principal": s["principal"], "client": s["client"],
            "purpose": s["purpose"], "started": int(s["started"]), "expires": int(s["expires"])}
