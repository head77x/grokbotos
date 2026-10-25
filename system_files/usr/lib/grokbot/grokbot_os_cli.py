#!/usr/bin/python3
"""grokbot-os: command line and MCP front end for grokbotd.

  grokbot-os [--json] methods
  grokbot-os [--json] <method> [key=value ...]     e.g. grokbot-os windows.list
  grokbot-os [--json] call <method> [key=value ...]
  grokbot-os audit [-n N] [principal=P] [decision=allow|deny|error] [method=M] [access=write]
  grokbot-os grants [principal]                     permissions per scope
  grokbot-os grant <principal> <scope> allow|ask|deny   (asks you to confirm)
  grokbot-os revoke <principal> [scope]
  grokbot-os apps [list]                            web apps (system and installed)
  grokbot-os apps install <url|path> [id]           install (asks you to confirm)
  grokbot-os apps uninstall <id> [--keep-data]      remove (asks you to confirm)
  grokbot-os apps launch <id>                       open in its own app window
  grokbot-os whoami                                 how the daemon identifies this caller
     principal: https://site, origin:..., unit:NAME.service, exe:/path, or a full local:uid=N:...
  grokbot-os mcp                                    MCP server on stdio

Exit codes: 0 ok, 2 usage / invalid params / permission denied,
1 daemon unreachable or the call failed.
"""
import json
import os
import socket
import sys

sys.path.insert(0, os.environ.get("GROKBOT_LIB", "/usr/lib/grokbot"))
from grokbotd import VERSION, paths  # noqa: E402

PROTOCOL = "2025-06-18"


class Unreachable(RuntimeError):
    pass


class Client:
    def __init__(self, path=None, label="grokbot-os CLI"):
        self.path = path or paths.socket_path()
        self.label = label
        self.sock = None
        self.n = 0

    def call(self, method, params=None):
        if self.sock is None:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(90)  # a call may wait for the consent prompt (60 s)
            try:
                s.connect(self.path)
            except OSError as e:
                raise Unreachable("grokbotd not reachable at %s: %s" % (self.path, e))
            self.sock, self.f = s, s.makefile("rwb")
        self.n += 1
        req = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        if self.label:
            req["x-client"] = {"name": self.label}  # shown in the prompt, self-reported
        self.f.write((json.dumps(req) + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise Unreachable("grokbotd closed the connection")
        return json.loads(line)


def _coerce(v, typ):
    """key=value strings become the type the schema declares."""
    if typ == "boolean" and v in ("true", "false"):
        return v == "true"
    if typ == "integer":
        try:
            return int(v)
        except ValueError:
            return v
    return v


def parse_kv(args):
    out = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(_usage("expected key=value, got %r" % a))
        k, v = a.split("=", 1)
        out[k] = v
    return out


def typed_params(client, method, raw):
    if not raw:
        return {}
    if not all(isinstance(v, str) for v in raw.values()):
        return raw
    r = client.call("api.methods")
    props = {}
    for m in r.get("result", {}).get("methods", []):
        if m["name"] == method:
            props = (m.get("params") or {}).get("properties", {})
    out = {}
    for k, v in raw.items():
        if v == "-" and props.get(k, {}).get("x-secret"):
            import getpass
            v = getpass.getpass("%s: " % k)  # keeps secrets off argv
        out[k] = _coerce(v, props.get(k, {}).get("type"))
    return out


def _usage(msg=None):
    if msg:
        sys.stderr.write("grokbot-os: %s\n" % msg)
    sys.stderr.write(__doc__.split("\n\n", 1)[1])
    return 2


def human(value, indent=0):
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (pad, k))
                lines.extend(human(v, indent + 1))
            else:
                lines.append("%s%s: %s" % (pad, k, _scalar(v)))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                sub = human(item, indent + 1)
                if sub:
                    sub[0] = pad + "- " + sub[0].lstrip()
                lines.extend(sub)
            else:
                lines.append("%s- %s" % (pad, _scalar(item)))
    else:
        lines.append(pad + _scalar(value))
    return lines


def _scalar(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def run_call(method, params, as_json):
    try:
        c = Client()
        resp = c.call(method, typed_params(c, method, params))
    except Unreachable as e:
        if as_json:
            print(json.dumps({"ok": False, "error": {"code": "unreachable", "message": str(e)}}))
        else:
            sys.stderr.write("grokbot-os: %s\n" % e)
        return 1
    if "error" in resp:
        err = resp["error"]
        if as_json:
            print(json.dumps({"ok": False, "error": err}, ensure_ascii=False))
        else:
            sys.stderr.write("grokbot-os: %s (%s)\n" % (err.get("message"), err.get("code")))
        return 2 if err.get("code") in (-32601, -32602, -32001) else 1
    if as_json:
        print(json.dumps({"ok": True, "result": resp["result"]}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(human(resp["result"])))
    return 0


def _install_human(p):
    try:
        resp = Client().call("apps.install", p)
    except Unreachable as e:
        sys.stderr.write("grokbot-os: %s\n" % e)
        return 1
    if "error" in resp:
        sys.stderr.write("grokbot-os: %s (%s)\n" % (resp["error"].get("message"), resp["error"].get("code")))
        return 2 if resp["error"].get("code") in (-32602, -32001) else 1
    a = resp["result"]
    print("installed %s  %s  %s  asks for: %s" % (a["id"], a.get("name_ko") or a["name"], a["origin"],
                                                ", ".join(a.get("scopes") or []) or "-"))
    return 0


def cmd_apps(args, as_json):
    sub = args[0] if args else "list"
    rest = args[1:]
    if sub == "list" and not rest:
        if as_json:
            return run_call("apps.list", {"include_launchers": False}, True)
        try:
            resp = Client().call("apps.list", {"include_launchers": False})
        except Unreachable as e:
            sys.stderr.write("grokbot-os: %s\n" % e)
            return 1
        if "error" in resp:
            sys.stderr.write("grokbot-os: %s\n" % resp["error"].get("message"))
            return 2
        for a in resp["result"].get("webapps", []):
            print("%-14s %-8s %-28s %s  [%s]" % (a["id"], "system" if a.get("system") else a.get("source"),
                                               a.get("name_ko") or a.get("name"), a.get("origin"),
                                               ",".join(a.get("scopes") or []) or "-"))
        return 0
    if sub == "install" and len(rest) in (1, 2):
        src = rest[0]
        p = {"url": src} if src.startswith(("http://", "https://")) else {"path": os.path.abspath(src)}
        if len(rest) == 2:
            p["id"] = rest[1]
        rc = run_call("apps.install", p, True) if as_json else _install_human(p)
        return rc
    if sub == "uninstall" and rest and len(rest) <= 2 and (len(rest) == 1 or rest[1] == "--keep-data"):
        return run_call("apps.uninstall", {"id": rest[0], "keep_data": len(rest) == 2}, as_json)
    if sub == "launch" and len(rest) == 1:
        return run_call("apps.launch", {"id": rest[0]}, as_json)
    return _usage("usage: apps [list] | install <url|path> [id] | uninstall <id> [--keep-data] | launch <id>")


MEDIA_KEYS = ("play-pause", "play", "pause", "next", "previous", "stop")


def cmd_media_key(args, as_json):
    """sway media-key binding: give the key to the web app waiting for it
    (media.keys.wait); when none is, or grokbotd is down, use playerctl."""
    if len(args) != 1 or args[0] not in MEDIA_KEYS:
        return _usage("usage: media-key " + "|".join(MEDIA_KEYS))
    try:
        resp = Client().call("media.keys.press", {"key": args[0]})
        if resp.get("result", {}).get("delivered"):
            return 0
    except Unreachable:
        pass
    try:
        os.execvp("playerctl", ["playerctl", args[0]])
    except OSError:
        return 1


def cmd_audit(args, as_json):
    params = {"limit": 20}
    rest = list(args)
    if rest[:1] == ["-n"] and len(rest) >= 2 and rest[1].isdigit():
        params["limit"] = int(rest[1])
        rest = rest[2:]
    for a in rest:
        k, eq, v = a.partition("=")
        if not eq or k not in ("principal", "decision", "method", "access"):
            return _usage("usage: audit [-n N] [principal=P] [decision=D] [method=M]")
        params[k] = v
    try:
        resp = Client().call("audit.list", params)
    except Unreachable as e:
        sys.stderr.write("grokbot-os: %s\n" % e)
        return 1
    if "error" in resp:
        sys.stderr.write("grokbot-os: %s\n" % resp["error"].get("message"))
        return 2
    for e in resp["result"]["entries"]:
        if as_json:
            print(json.dumps(e, ensure_ascii=False, sort_keys=True))
        else:
            dec = e.get("decision", e.get("event", "-"))
            if e.get("consent"):
                dec += "/" + e["consent"]
            print("%s %-6s %-12s %-26s %-14s %s%s" % (
                e.get("ts"), e.get("transport", "-"), dec, e.get("method", "-"),
                e.get("scope") or "-", e.get("principal", ""),
                " " + e["error"] if e.get("error") else ""))
    return 0


def cmd_grants(args, as_json):
    params = {"principal": _norm_principal(args[0])} if args else {}
    if len(args) > 1:
        return _usage("usage: grants [principal]")
    try:
        resp = Client().call("permissions.list", params)
    except Unreachable as e:
        sys.stderr.write("grokbot-os: %s\n" % e)
        return 1
    if "error" in resp:
        sys.stderr.write("grokbot-os: %s\n" % resp["error"].get("message"))
        return 2
    if as_json:
        print(json.dumps({"ok": True, "result": resp["result"]}, ensure_ascii=False, indent=2))
        return 0
    for p in resp["result"]["principals"]:
        print(p["principal"] + (" (이 사용자 / this user)" if p["local"] else ""))
        for s, m in p["scopes"].items():
            if p["local"] or m["read"] != "deny" or m["write"] != "deny":
                print("  %-14s read=%-5s write=%-5s %s" % (s, m["read"], m["write"],
                      "stored" if m["stored"] else m["source"]))
    return 0


def _norm_principal(p):
    if p.startswith(("origin:", "local:")):
        return p
    if p.startswith(("unit:", "exe:")):
        k, v = p.split(":", 1)
        return "local:uid=%d:%s=%s" % (os.getuid(), k, v)
    if p.startswith(("http://", "https://")):
        return "origin:" + p
    return p


# ---------------- MCP (stdio, newline-delimited JSON-RPC) ----------------

def _tool_name(method):
    return method.replace(".", "_")


def mcp_serve(inp=sys.stdin, out=sys.stdout):
    client = Client(label="MCP client")
    tools = None

    def send(msg):
        out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        out.flush()

    def load_tools():
        r = client.call("api.methods")
        if "error" in r:
            raise Unreachable(r["error"]["message"])
        return {_tool_name(m["name"]): m for m in r["result"]["methods"]}

    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # notifications (notifications/initialized, cancelled)
        try:
            if method == "initialize":
                ci = ((msg.get("params") or {}).get("clientInfo") or {}).get("name")
                if isinstance(ci, str) and ci:
                    client.label = "MCP: " + ci[:40]
                send({"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": (msg.get("params") or {}).get("protocolVersion", PROTOCOL),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "grokbot-os", "version": VERSION},
                    "instructions": "Grok Bot OS API. Read tools answer at once. Write tools "
                                    "(volume, brightness, Wi-Fi, DND, power, screenshot, camera/"
                                    "microphone sessions) are checked per scope and may show the "
                                    "user a consent prompt; a denied call returns isError."}})
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "tools/list":
                tools = load_tools()
                send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                    {"name": n, "description": m["description"],
                     "inputSchema": m.get("params") or {"type": "object"},
                     "annotations": {"readOnlyHint": m.get("access", "read") == "read",
                                     "destructiveHint": m.get("scope") == "power",
                                     "openWorldHint": False}}
                    for n, m in sorted(tools.items()) if n != "api_methods"]}})
            elif method == "tools/call":
                p = msg.get("params") or {}
                tools = tools or load_tools()
                m = tools.get(p.get("name"))
                if m is None or p.get("name") == "api_methods":
                    send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602,
                          "message": "unknown tool: %s" % p.get("name")}})
                    continue
                r = client.call(m["name"], p.get("arguments") or {})
                if "error" in r:
                    send({"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [
                        {"type": "text", "text": json.dumps(r["error"], ensure_ascii=False)}]}})
                else:
                    send({"jsonrpc": "2.0", "id": mid, "result": {
                        "content": [{"type": "text", "text": json.dumps(r["result"], ensure_ascii=False)}],
                        "structuredContent": r["result"]}})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601,
                      "message": "method not found: %s" % method}})
        except Unreachable as e:
            client = Client(label=client.label)
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(e)}})
    return 0


def main(argv):
    as_json = False
    while argv and argv[0].startswith("--"):
        if argv[0] == "--json":
            as_json = True
        elif argv[0] == "--version":
            print(VERSION)
            return 0
        elif argv[0] == "--help":
            return _usage() and 0
        else:
            return _usage("unknown option %s" % argv[0])
        argv = argv[1:]
    if not argv:
        return _usage()
    cmd, rest = argv[0], argv[1:]
    if cmd == "mcp":
        return mcp_serve()
    if cmd == "audit":
        return cmd_audit(rest, as_json)
    if cmd == "grants":
        return cmd_grants(rest, as_json)
    if cmd == "grant":
        if len(rest) != 3:
            return _usage("usage: grant <principal> <scope> allow|ask|deny")
        return run_call("permissions.set", {"principal": _norm_principal(rest[0]), "scope": rest[1],
                                            "mode": rest[2]}, as_json)
    if cmd == "revoke":
        if len(rest) not in (1, 2):
            return _usage("usage: revoke <principal> [scope]")
        p = {"principal": _norm_principal(rest[0])}
        if len(rest) == 2:
            p["scope"] = rest[1]
        return run_call("permissions.revoke", p, as_json)
    if cmd == "apps":
        return cmd_apps(rest, as_json)
    if cmd == "media-key":
        return cmd_media_key(rest, as_json)
    if cmd == "whoami":
        return run_call("permissions.whoami", {}, as_json)
    if cmd == "methods":
        return run_call("api.methods", {}, as_json)
    if cmd == "call":
        if not rest:
            return _usage("call needs a method")
        cmd, rest = rest[0], rest[1:]
    if "." not in cmd and rest and "=" not in rest[0]:
        cmd, rest = cmd + "." + rest[0], rest[1:]  # "windows list" == "windows.list"
    return run_call(cmd, parse_kv(rest), as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
