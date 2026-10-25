"""JSON-RPC 2.0 dispatch shared by every transport.

Order for every call: method lookup -> params validation -> permission
(mode for the caller and the method's scope) -> consent prompt when the
mode is "ask" -> backend. Every outcome is written to the audit log.
"""
import threading
import time

from . import appdata, audiodev, audit, backends, bluetooth, consent, displays, files, keyboard, mediakeys, netconn, nightlight, perms, powermode, printing, schema, storage, updates, webapps, writes

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
BACKEND_ERROR = -32000
PERMISSION_DENIED = -32001

METHODS = dict(backends.METHODS)
METHODS.update(writes.METHODS)
METHODS.update(files.METHODS)
METHODS.update(mediakeys.METHODS)
METHODS.update(updates.METHODS)
METHODS.update(displays.METHODS)
METHODS.update(bluetooth.METHODS)
METHODS.update(audiodev.METHODS)
METHODS.update(storage.METHODS)
METHODS.update(powermode.METHODS)
METHODS.update(keyboard.METHODS)
METHODS.update(netconn.METHODS)
METHODS.update(printing.METHODS)
METHODS.update(nightlight.METHODS)
CTX_METHODS = dict(writes.CTX_METHODS)
CTX_METHODS.update(storage.CTX_METHODS)
CTX_METHODS.update(appdata.CTX_METHODS)
SPECIAL = {"api.methods", "permissions.request"}
REQUEST_COOLDOWN_S = 600


def redact(spec, params):
    """Params as written to the audit log and shown in the prompt:
    secrets replaced, long strings cut."""
    props = (spec.get("params") or {}).get("properties", {})
    out = {}
    for k, v in (params or {}).items():
        if props.get(k, {}).get("x-secret"):
            out[k] = "***"
        elif isinstance(v, str) and len(v) > 80:
            out[k] = v[:80] + "…"
        else:
            out[k] = v
    return out


def _client_label(req, transport):
    c = req.get("x-client") if isinstance(req, dict) else None
    if isinstance(c, dict):
        c = c.get("name")
    if not isinstance(c, str) or not c.strip():
        return None
    c = "".join(ch for ch in c.strip() if ch.isprintable())[:60]
    return c or None


class Dispatcher:
    def __init__(self, schema_doc):
        self.schema = schema_doc
        self.methods = schema_doc["methods"]
        missing = [m for m in self.methods
                   if m not in SPECIAL and m not in METHODS and m not in CTX_METHODS]
        if missing:
            raise ValueError("schema methods without a backend: %s" % ", ".join(missing))
        for s in self.methods.values():
            if s.get("scope"):
                perms.SCOPE_ACCESS.setdefault(s["scope"], set()).add(s.get("access", "read"))
        self._req_lock = threading.Lock()
        self._last_request = {}

    def _api_methods(self, principal):
        out = []
        for n, s in sorted(self.methods.items()):
            scope, access = s.get("scope"), s.get("access", "read")
            mode = "allow" if scope is None else perms.mode_for(principal, scope, access, s.get("capability"))[0]
            if s.get("consent") == "always" and mode == "allow":
                mode = "ask"
            out.append({"name": n, "description": s.get("description"), "capability": s.get("capability"),
                        "scope": scope, "access": access, "mode": mode, "allowed": mode != "deny",
                        "title": s.get("x-title"), "params": s.get("params")})
        return {"version": self.schema.get("version"), "methods": out}

    def handle(self, req, principal, transport, peer=None):
        """req: parsed JSON (or None on parse failure). Returns a response dict."""
        if req is None:
            return _err(None, PARSE_ERROR, "parse error")
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            return _err(req.get("id") if isinstance(req, dict) else None, INVALID_REQUEST, "invalid request")
        rid, method = req.get("id"), req["method"]
        client = _client_label(req, transport)
        spec = self.methods.get(method)
        base = {"transport": transport, "principal": principal, "method": method[:64]}
        if client:
            base["client"] = client
        if peer and peer.get("pid"):
            base["pid"] = peer["pid"]
        if spec is None:
            audit.record(decision="error", error="method_not_found", **base)
            return _err(rid, METHOD_NOT_FOUND, "method not found: %s" % method[:64])
        cap, scope, access = spec.get("capability"), spec.get("scope"), spec.get("access", "read")
        base.update(capability=cap, scope=scope, access=access)
        try:
            params = schema.validate_params(spec, req.get("params"))
        except schema.ParamError as e:
            audit.record(decision="error", error="invalid_params", **base)
            return _err(rid, INVALID_PARAMS, str(e))
        if access == "write":
            base["params"] = redact(spec, params)
        ctx = {"principal": principal, "client": client, "transport": transport, "peer": peer or {}}

        if method == "permissions.request":
            return self._request(rid, params, ctx, base)

        if scope is not None:
            mode, source = perms.mode_for(principal, scope, access, cap)
            if spec.get("consent") == "always" and mode == "allow":
                mode = "ask"
            if spec.get("consent") == "always" and not principal.startswith(("local:", "origin:")):
                mode = "deny"
            base.update(mode=mode, source=source)
            if mode == "deny":
                audit.record(decision="deny", **base)
                return _err(rid, PERMISSION_DENIED, "permission denied: %s needs scope %s (%s)"
                            % (method, scope, access), {"capability": cap, "scope": scope,
                                                        "access": access, "mode": mode})
            if mode == "ask" and spec.get("x-secret-prompt"):
                # The backend shows the secure prompt (who / what + the
                # secret field); answering it is the consent for this call.
                base.update(consent="secret_prompt")
            elif mode == "ask":
                allow_always = (scope not in perms.ALWAYS_ASK and spec.get("consent") != "always"
                                and perms.storable(principal))
                allow_session = scope not in perms.ALWAYS_ASK and spec.get("consent") != "always"
                ans, detail = consent.prompt(principal, client, scope, method,
                                             spec.get("x-title") or [method, method],
                                             base.get("params", {}), allow_always, allow_session)
                base.update(consent=ans, consent_by=detail)
                if ans == "deny":
                    audit.record(decision="deny", **base)
                    return _err(rid, PERMISSION_DENIED, "permission denied by the user: %s" % method,
                                {"capability": cap, "scope": scope, "access": access, "mode": "ask",
                                 "consent": detail})
                if ans == "always":
                    perms.set_mode(principal, scope, "allow", by="prompt")
                elif ans == "session":
                    perms.session_allow(principal, scope)
        quiet = False
        try:
            if method == "api.methods":
                result = self._api_methods(principal)
            elif method in CTX_METHODS:
                result = CTX_METHODS[method](params, ctx)
            elif method == "media.keys.wait":
                quiet = not mediakeys.begin(principal)
                try:
                    result = METHODS[method](params)
                finally:
                    mediakeys.end(principal)
            else:
                result = METHODS[method](params)
        except webapps.Denied as e:
            base.update(consent="deny", consent_by=e.detail)
            audit.record(decision="deny", **base)
            return _err(rid, PERMISSION_DENIED, "permission denied by the user: %s" % method,
                        {"scope": scope, "access": access, "consent": e.detail})
        except webapps.InstallError as e:
            audit.record(decision="allow", error="backend", detail=str(e)[:200], **base)
            return _err(rid, BACKEND_ERROR, str(e))
        except backends.BackendError as e:
            audit.record(decision="allow", error="backend", detail=str(e)[:200], **base)
            return _err(rid, BACKEND_ERROR, str(e))
        except Exception as e:  # never kill the daemon over one call
            audit.record(decision="allow", error="internal", detail=type(e).__name__, **base)
            return _err(rid, BACKEND_ERROR, "internal error: %s" % type(e).__name__)
        if not quiet:
            audit.record(decision="allow", **base)
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _request(self, rid, params, ctx, base):
        principal, scope = ctx["principal"], params["scope"]
        base["requested_scope"] = scope
        if scope not in perms.SCOPES:
            audit.record(decision="error", error="invalid_params", **base)
            return _err(rid, INVALID_PARAMS, "unknown scope: %s" % scope)
        if not principal.startswith("origin:") and not perms.is_local(principal):
            audit.record(decision="deny", error="anonymous", **base)
            return _err(rid, PERMISSION_DENIED, "only a web origin or the local user can request a scope")
        cur = perms.mode_for(principal, scope, "write")[0]
        if cur == "allow" or (cur == "ask" and scope in perms.ALWAYS_ASK):
            audit.record(decision="allow", mode=cur, **base)
            return {"jsonrpc": "2.0", "id": rid, "result": {"scope": scope, "mode": cur}}
        key = (principal, scope)
        with self._req_lock:
            last = self._last_request.get(key, 0)
            if time.time() - last < REQUEST_COOLDOWN_S:
                audit.record(decision="deny", error="rate_limited", **base)
                return _err(rid, PERMISSION_DENIED, "asked recently; try again later",
                            {"scope": scope, "retry_after_s": int(REQUEST_COOLDOWN_S - (time.time() - last))})
            self._last_request[key] = time.time()
        title = ["이 기능 사용 권한 요청: %s" % params.get("reason", ""),
                 "Permission request: %s" % params.get("reason", "")]
        # A request is about the future, so "once" means nothing here except
        # for always-ask scopes, where it grants the right to ask (each use
        # is still confirmed). Others: this session, or always.
        sensitive = scope in perms.ALWAYS_ASK
        allow_always = not sensitive and perms.storable(principal)
        ans, detail = consent.prompt(principal, ctx["client"], scope, "permissions.request",
                                     title, {"scope": scope}, allow_always,
                                     allow_session=not sensitive, allow_once=sensitive)
        if ans == "session":
            perms.session_allow(principal, scope)
            base.update(consent=ans, consent_by=detail)
            audit.record(decision="allow", **base)
            return {"jsonrpc": "2.0", "id": rid, "result": {"scope": scope, "mode": "allow",
                                                             "answer": ans, "until": "session"}}
        new = {"always": "allow", "once": "ask", "deny": "deny"}[ans]
        if detail in ("timeout", "no_prompt", "bad_answer") or not perms.storable(principal):
            new = None  # no answer: store nothing
        if new is not None:
            perms.set_mode(principal, scope, new, by="prompt")
        base.update(consent=ans, consent_by=detail)
        audit.record(decision="allow" if new in ("allow", "ask") else "deny", **base)
        return {"jsonrpc": "2.0", "id": rid, "result": {"scope": scope, "mode": new or cur,
                                                         "answer": ans}}


def _err(rid, code, msg, data=None):
    e = {"code": code, "message": msg}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}
