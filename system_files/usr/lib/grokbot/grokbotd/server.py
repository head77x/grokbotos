"""Transports: unix socket (newline-delimited JSON-RPC) and HTTP on
127.0.0.1 (POST /v1/rpc, GET /v1/health, GET /v1/schema)."""
import json
import os
import re
import socket
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from urllib.parse import parse_qsl, urlencode

from . import apptoken, peer, webapps, VERSION, audit, paths, policy

MAX_BODY = 64 * 1024
_APP_ORIGIN = re.compile(r"http://[a-z0-9][a-z0-9-]*\.app\.localhost(:\d+)?")


def _host_ok(host, port):
    """DNS-rebinding guard: the Host header must name loopback."""
    if not host:
        return False
    host = host.lower()
    return bool(re.fullmatch(r"(127\.0\.0\.1|localhost|[a-z0-9][a-z0-9.-]*\.app\.localhost):%d" % port, host))


def _origin_ok(origin):
    return bool(re.fullmatch(r"https?://[a-z0-9.-]+(:\d+)?", origin or ""))


class UnixHandler(socketserver.StreamRequestHandler):
    def handle(self):
        creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, _ = struct.unpack("3i", creds)
        if uid != os.getuid():
            audit.record(transport="unix", principal="local:uid=%d" % uid, decision="deny",
                         error="foreign_uid", pid=pid)
            return
        principal, who = peer.identify(pid, uid)
        while True:
            line = self.rfile.readline(MAX_BODY + 1)
            if not line:
                return
            if len(line) > MAX_BODY:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "request too large"}}
            else:
                try:
                    req = json.loads(line)
                except ValueError:
                    req = None
                resp = self.server.dispatcher.handle(req, principal, "unix", peer=who)
            self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class HttpHandler(BaseHTTPRequestHandler):
    server_version = "grokbotd/" + VERSION
    sys_version = ""
    # Every connection holds a thread. Without a socket timeout, a web page
    # or local process that opens connections and never finishes a request
    # keeps those threads forever. A timed-out request is just closed.
    timeout = 10

    def log_message(self, fmt, *args):
        pass  # the audit log records RPC calls; access logs would leak titles

    def _send(self, code, body, origin=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, full):
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", WEBAPP_TYPES[os.path.splitext(full)[1].lower()])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        uid, inode = policy.tcp_peer(self.client_address[1], self.server.server_address[1])
        if uid != os.getuid():
            audit.record(transport="http", principal="http:uid=%s" % uid, decision="deny",
                         error="foreign_uid")
            self._send(403, {"error": "forbidden"})
            return None
        if not _host_ok(self.headers.get("Host"), self.server.server_address[1]):
            audit.record(transport="http", principal="http:bad-host", decision="deny",
                         error="bad_host", host=self.headers.get("Host"))
            self._send(403, {"error": "forbidden host"})
            return None
        if not self.path.startswith("/v1/"):
            return ("http:static", None)  # web app files: no principal needed
        origin = self.headers.get("Origin")
        if origin is None and self.headers.get("Sec-Fetch-Site") == "same-origin" and \
                webapp_file(self.headers.get("Host"), "/index.html"):
            # Browsers may omit Origin on same-origin requests; Sec-Fetch-*
            # cannot be set by page scripts.
            origin = "http://" + self.headers.get("Host").lower()
        if origin is None:
            return ("http:no-origin", None)
        if not _origin_ok(origin):
            return ("http:bad-origin", None)
        # Origin only means something when a browser sent it (docs/OS_API.md).
        if not policy.peer_is_browser(inode):
            audit.record(transport="http", principal="http:no-origin", decision="downgrade",
                         error="origin_untrusted_peer", origin=origin)
            return ("http:no-origin", None)
        if _APP_ORIGIN.fullmatch(origin.lower()) and not apptoken.valid(
                origin, apptoken.cookie_value(self.headers.get("Cookie"))):
            audit.record(transport="http", principal="http:no-origin", decision="downgrade",
                         error="app_token_missing", origin=origin)
            return ("http:no-origin", None)
        return ("origin:" + origin, origin if policy.origin_known(origin) else None)

    def _token_redirect(self):
        """<start_url>?gbt=<token> from a launcher: set the app cookie and
        redirect to the same URL without the token."""
        path, _, query = self.path.partition("?")
        q = parse_qsl(query, keep_blank_values=True)
        tok = [v for k, v in q if k == apptoken.PARAM]
        if not tok:
            return False
        origin = "http://" + self.headers.get("Host").lower()
        rest = [(k, v) for k, v in q if k != apptoken.PARAM]
        loc = path + ("?" + urlencode(rest) if rest else "")
        self.send_response(303)
        if apptoken.valid(origin, tok[0]):
            self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (apptoken.COOKIE, tok[0]))
        else:
            audit.record(transport="http", principal="origin:" + origin, decision="deny", error="app_token_bad")
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        return True

    def do_OPTIONS(self):
        g = self._guard()
        if g is None:
            return
        principal, cors = g
        if not cors:
            audit.record(transport="http", principal=principal, decision="deny", error="preflight")
            self._send(403, {"error": "origin not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", cors)
        self.send_header("Access-Control-Allow-Methods", "POST, GET")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        g = self._guard()
        if g is None:
            return
        _, cors = g
        if self.path == "/v1/health":
            self._send(200, {"ok": True, "service": "grokbotd", "version": VERSION}, cors)
        elif self.path == "/v1/schema":
            self._send(200, self.server.dispatcher.schema, cors)
        elif not self.path.startswith("/v1/") and webapp_file(self.headers.get("Host"), self.path):
            if self._token_redirect():
                return
            self._send_file(webapp_file(self.headers.get("Host"), self.path))
        else:
            self._send(404, {"error": "not found"}, cors)

    def do_POST(self):
        g = self._guard()
        if g is None:
            return
        principal, cors = g
        if self.path != "/v1/rpc":
            self._send(404, {"error": "not found"}, cors)
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # Forces a CORS preflight for browsers: no "simple" form POSTs.
            audit.record(transport="http", principal=principal, decision="deny", error="content_type")
            self._send(415, {"error": "Content-Type must be application/json"}, cors)
            return
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self._send(413, {"error": "body too large"}, cors)
            return
        try:
            req = json.loads(self.rfile.read(n) or b"null")
        except ValueError:
            req = None
        resp = self.server.dispatcher.handle(req, principal, "http")
        code = 200
        if "error" in resp and resp["error"]["code"] == -32001:
            code = 403
        self._send(code, resp, cors)


WEBAPP_TYPES = webapps.TYPES
# System web apps are static files from the read-only image, served on
# their own origin http://<id>.app.localhost:<port>. They reach the OS only
# through /v1/rpc on that origin, with that origin's grants.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; font-src 'self'; manifest-src 'self'; "
       "worker-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

DESIGN_PREFIX = "/_grokbot/"


def webapp_file(host, path):
    """Absolute file for GET path on host, or None. No traversal, no
    dotfiles, no symlinks out of the app directory."""
    m = re.fullmatch(r"([a-z0-9][a-z0-9-]*)\.app\.localhost:\d+", (host or "").lower())
    if not m:
        return None
    root = webapps.app_root(m.group(1))
    if root is None:
        return None
    rel = path.split("?", 1)[0].split("#", 1)[0]
    if rel.startswith(DESIGN_PREFIX):
        # Shared design system (tokens, base components, the character),
        # read-only from the image, same origin for every app so the CSP holds.
        root = os.path.realpath(paths.design_dir())
        rel = rel[len(DESIGN_PREFIX) - 1:]
    if rel.endswith("/"):
        rel += "index.html"
    parts = [x for x in rel.split("/") if x]
    if any(x.startswith(".") or "\\" in x for x in parts):
        return None
    full = os.path.realpath(os.path.join(root, *parts))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in WEBAPP_TYPES:
        return None
    return full


class HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(dispatcher, http=True):
    sock = paths.socket_path()
    os.makedirs(os.path.dirname(sock), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(sock), 0o700)
    if os.path.exists(sock):
        os.unlink(sock)
    old = os.umask(0o177)
    try:
        us = UnixServer(sock, UnixHandler)
    finally:
        os.umask(old)
    us.dispatcher = dispatcher
    threads = [threading.Thread(target=us.serve_forever, daemon=True)]
    hs = None
    if http:
        hs = HttpServer(("127.0.0.1", paths.http_port()), HttpHandler)
        hs.dispatcher = dispatcher
        threads.append(threading.Thread(target=hs.serve_forever, daemon=True))
    for t in threads:
        t.start()
    return us, hs
