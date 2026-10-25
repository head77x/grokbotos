"""Web app installer: apps.install / apps.list / apps.uninstall / apps.launch.

A web app is either
  bundle  a directory or .zip with a manifest.json (W3C web app manifest,
          plus an optional "grokbot" member). Its files are copied to
          ~/.local/share/grokbot/webapps/<id>/ and grokbotd serves them on
          their own origin http://<id>.app.localhost:<port>.
  url     a remote site (https://, or http:// on loopback). Only its start
          URL, name and icon are stored; its origin is the site's origin.
System apps ship in /usr/share/grokbot/webapps/<id>/manifest.json (Settings,
System monitor). They are always "installed" and cannot be removed.

Installing writes a launcher (~/.local/share/applications/
grokbot-webapp-<id>.desktop), so the app shows in the launcher and the dock;
nothing is ever put on the desktop. The launcher runs grokbot-webapp <id>:
a chromeless Firefox window with app_id grokbot-webapp-<id> and its own
profile (~/.local/share/grokbot/webapp-profiles/<id>), which keeps that
app's service worker, cache, IndexedDB and localStorage across restarts.

Installing grants nothing. The app's origin becomes known (it gets CORS
answers, so it can call permissions.request), and every OS function it
uses needs a per-scope grant from the consent prompt. Install and
uninstall always show the prompt, with the app's name, origin and the
scopes its manifest says it will ask for.
"""
import html.parser
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from . import consent, paths, perms

ID_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
RESERVED = {"settings", "www", "api", "localhost", "app", "apps"}
MAX_BUNDLE_BYTES = 50 * 1024 * 1024
MAX_FILES = 2000
MAX_FETCH = 1024 * 1024
MAX_ICON = 512 * 1024
# File types grokbotd serves for web apps (server.WEBAPP_TYPES uses this).
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
         ".json": "application/json", ".webmanifest": "application/manifest+json",
         ".woff": "font/woff", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8",
         ".wasm": "application/wasm"}


class InstallError(Exception):
    pass


class Denied(Exception):
    def __init__(self, detail):
        super().__init__("denied by the user")
        self.detail = detail


# ---------------- paths ----------------

def user_dir():
    return os.path.join(paths.data_home(), "grokbot", "webapps")


def system_dir():
    return paths.webapps_dir()


def _record_path(app_id):
    return os.path.join(paths.installed_dir(), "webapp.%s.json" % app_id)


def _desktop_path(app_id):
    return os.path.join(paths.data_home(), "applications", "grokbot-webapp-%s.desktop" % app_id)


def profile_dir(app_id):
    return os.path.join(paths.data_home(), "grokbot", "webapp-profiles", app_id)


def local_origin(app_id):
    return "http://%s.app.localhost:%d" % (app_id, paths.http_port())


def app_root(app_id):
    """Directory served for <id>.app.localhost: the image first, then the
    user's installed bundles. A user bundle can never shadow a system app."""
    if not ID_RE.fullmatch(app_id or "") and app_id != "settings":
        return None
    for base in (system_dir(), user_dir()):
        d = os.path.join(base, app_id)
        if os.path.isdir(d):
            return os.path.realpath(d)
    return None


# ---------------- manifest ----------------

def _str(v, n=80):
    if not isinstance(v, str):
        return None
    v = "".join(c for c in v.strip() if c.isprintable())[:n]
    return v or None


def parse_manifest(doc):
    if not isinstance(doc, dict):
        raise InstallError("manifest.json must be a JSON object")
    g = doc.get("grokbot") if isinstance(doc.get("grokbot"), dict) else {}
    name = _str(doc.get("name")) or _str(doc.get("short_name"))
    if not name:
        raise InstallError("manifest.json needs a name")
    scopes = g.get("scopes", [])
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise InstallError("grokbot.scopes must be a list of scope names")
    bad = [s for s in scopes if s not in perms.SCOPES]
    if bad:
        raise InstallError("unknown scopes in manifest: %s" % ", ".join(bad[:5]))
    icons = doc.get("icons") if isinstance(doc.get("icons"), list) else []
    return {"name": name, "name_ko": _str(g.get("name_ko")) or name,
            "short_name": _str(doc.get("short_name"), 30),
            "description": _str(doc.get("description"), 200),
            "start_url": _str(doc.get("start_url"), 300) or "/",
            "id": _str(g.get("id"), 31), "scopes": sorted(set(scopes)),
            "icons": [i for i in icons if isinstance(i, dict) and isinstance(i.get("src"), str)][:20],
            "version": _str(doc.get("version") or g.get("version"), 30)}


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    s = re.sub(r"^[^a-z]+", "", s)[:31].strip("-")
    return s or None


def _pick_icon(icons):
    def size(i):
        try:
            return max(int(x.split("x")[0]) for x in (i.get("sizes") or "0x0").split())
        except ValueError:
            return 0
    svg = [i for i in icons if i["src"].lower().split("?")[0].endswith(".svg")]
    if svg:
        return svg[0]["src"]
    png = sorted((i for i in icons if i["src"].lower().split("?")[0].endswith(".png")), key=size)
    big = [i for i in png if size(i) >= 96]
    return (big or png or [{}])[0].get("src") if (big or png) else None


# ---------------- bundle ----------------

def _check_tree(root):
    total, count = 0, 0
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            if n.startswith(".") or os.path.islink(p):
                raise InstallError("bundle may not contain dotfiles or symlinks: %s" % n)
        for n in files:
            ext = os.path.splitext(n)[1].lower()
            if ext not in TYPES:
                raise InstallError("file type not allowed in a web app: %s" % n)
            total += os.path.getsize(os.path.join(d, n))
            count += 1
            if total > MAX_BUNDLE_BYTES or count > MAX_FILES:
                raise InstallError("bundle too large (max %d MB, %d files)"
                                   % (MAX_BUNDLE_BYTES // 2 ** 20, MAX_FILES))


def _unzip(src, dest):
    with zipfile.ZipFile(src) as z:
        total = 0
        for zi in z.infolist():
            name = zi.filename
            if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                raise InstallError("unsafe path in zip: %s" % name[:80])
            if (zi.external_attr >> 16) & 0o170000 == 0o120000:
                raise InstallError("bundle may not contain symlinks")
            total += zi.file_size
            if total > MAX_BUNDLE_BYTES or len(z.infolist()) > MAX_FILES:
                raise InstallError("bundle too large")
        z.extractall(dest)
    # a zip with one top-level directory: use that directory
    items = [x for x in os.listdir(dest) if not x.startswith("__MACOSX")]
    if len(items) == 1 and os.path.isdir(os.path.join(dest, items[0])) and \
            not os.path.exists(os.path.join(dest, "manifest.json")):
        return os.path.join(dest, items[0])
    return dest


def stage_bundle(path, tmp):
    path = os.path.realpath(os.path.expanduser(path))
    if os.path.isdir(path):
        src = path
    elif os.path.isfile(path) and zipfile.is_zipfile(path):
        src = _unzip(path, os.path.join(tmp, "unzip"))
    else:
        raise InstallError("path must be a directory or a .zip with manifest.json")
    mf = os.path.join(src, "manifest.json")
    if not os.path.isfile(mf):
        raise InstallError("no manifest.json in the bundle")
    try:
        with open(mf, encoding="utf-8") as f:
            man = parse_manifest(json.load(f))
    except ValueError:
        raise InstallError("manifest.json is not valid JSON")
    _check_tree(src)
    start = urllib.parse.urlsplit(man["start_url"])
    if start.scheme or start.netloc:
        raise InstallError("a bundle's start_url must be a path inside the bundle")
    return src, man


# ---------------- url ----------------

class _LinkFinder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.manifest, self.icon, self.title, self._t = None, None, None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        rel = (a.get("rel") or "").lower().split()
        if tag == "link" and "manifest" in rel and not self.manifest:
            self.manifest = a.get("href")
        if tag == "link" and ("icon" in rel or "apple-touch-icon" in rel) and not self.icon:
            self.icon = a.get("href")
        if tag == "title":
            self._t = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._t = False

    def handle_data(self, data):
        if self._t and not self.title:
            self.title = data.strip()


def _url_ok(u):
    p = urllib.parse.urlsplit(u)
    if p.scheme == "https" and p.hostname:
        return True
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")


def _fetch(u, limit):
    if not _url_ok(u):
        raise InstallError("only https:// URLs (or http:// on this computer)")
    req = urllib.request.Request(u, headers={"User-Agent": "grokbotd-webapp-installer",
                                             "Accept": "text/html,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=10) as r:
        if not _url_ok(r.geturl()):
            raise InstallError("redirected to a URL that is not allowed")
        data = r.read(limit + 1)
        if len(data) > limit:
            raise InstallError("response too large: %s" % u[:80])
        return r.geturl(), r.headers.get_content_type(), data


def stage_url(url, tmp):
    if not _url_ok(url):
        raise InstallError("only https:// URLs (or http:// on this computer)")
    try:
        final, ctype, body = _fetch(url, MAX_FETCH)
    except InstallError:
        raise
    except Exception as e:
        raise InstallError("could not open %s: %s" % (url[:80], type(e).__name__))
    found = _LinkFinder()
    if ctype == "text/html":
        found.feed(body.decode("utf-8", "replace"))
    man = None
    if found.manifest:
        try:
            _, _, mb = _fetch(urllib.parse.urljoin(final, found.manifest), MAX_FETCH)
            man_url = urllib.parse.urljoin(final, found.manifest)
            man = parse_manifest(json.loads(mb))
            man["from_manifest"] = True
        except (InstallError, ValueError, OSError):
            man = None
    if man is None:
        host = urllib.parse.urlsplit(final).hostname
        man = {"name": _str(found.title) or host, "name_ko": _str(found.title) or host, "short_name": None,
               "description": None, "start_url": final, "id": None, "scopes": [], "icons": [],
               "version": None}
        man_url = final
        if found.icon:
            man["icons"] = [{"src": found.icon}]
    start = urllib.parse.urljoin(man_url, man["start_url"])
    origin = "%s://%s" % urllib.parse.urlsplit(start)[:2]
    if origin != "%s://%s" % urllib.parse.urlsplit(final)[:2] or not _url_ok(start):
        start = final  # start_url outside the site: ignore it
        origin = "%s://%s" % urllib.parse.urlsplit(final)[:2]
    man["start_url"] = start
    icon_file = None
    src = _pick_icon(man["icons"]) if man["icons"] else None
    if src:
        try:
            iu = urllib.parse.urljoin(man_url, src)
            _, ict, ib = _fetch(iu, MAX_ICON)
            ext = ".svg" if (ict == "image/svg+xml" or iu.lower().split("?")[0].endswith(".svg")) else ".png"
            if ext == ".png" and not ib.startswith(b"\x89PNG"):
                raise InstallError("icon is not a PNG")
            icon_file = os.path.join(tmp, "icon" + ext)
            with open(icon_file, "wb") as f:
                f.write(ib)
        except Exception:
            icon_file = None
    return man, origin, icon_file


# ---------------- records ----------------

def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def system_apps():
    out = []
    base = system_dir()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for n in names:
        mf = _load(os.path.join(base, n, "manifest.json"))
        if mf is None:
            continue
        try:
            man = parse_manifest(mf)
        except InstallError:
            continue
        icon = _pick_icon(man["icons"])
        out.append({"id": n, "kind": "webapp", "source": "system", "system": True,
                    "name": man["name"], "name_ko": man["name_ko"], "description": man["description"],
                    "origin": local_origin(n), "start_url": local_origin(n) + _path(man["start_url"]),
                    "scopes": man["scopes"], "version": man["version"],
                    "icon": os.path.join(base, n, icon) if icon else None,
                    "desktop_id": "grokbot-webapp-%s.desktop" % n if n != "settings" else "grokbot-settings.desktop"})
    return out


def _path(p):
    p = p or "/"
    return p if p.startswith("/") else "/" + p


def user_apps():
    out = []
    try:
        names = sorted(os.listdir(paths.installed_dir()))
    except OSError:
        names = []
    for n in names:
        if n.startswith("webapp.") and n.endswith(".json"):
            r = _load(os.path.join(paths.installed_dir(), n))
            if r and ID_RE.fullmatch(str(r.get("id"))):
                r["system"] = False
                out.append(r)
    return out


def all_apps():
    return system_apps() + user_apps()


def get(app_id):
    for a in all_apps():
        if a["id"] == app_id:
            return a
    return None


def known_origins():
    return {a["origin"] for a in all_apps() if a.get("origin")}


# ---------------- launcher ----------------

def _desktop_escape(s):
    return (s or "").replace("\\", "\\\\").replace("\n", " ").replace("\r", " ")


def write_desktop(rec):
    p = _desktop_path(rec["id"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lines = ["[Desktop Entry]", "Type=Application",
             "Name=%s" % _desktop_escape(rec["name_ko"] or rec["name"]),
             "Name[en]=%s" % _desktop_escape(rec["name"]),
             "Comment=%s" % _desktop_escape(rec.get("description") or rec["origin"]),
             "Exec=/usr/local/bin/grokbot-webapp %s" % rec["id"],
             "Icon=%s" % (rec.get("icon") or "applications-internet"),
             "Terminal=false", "Categories=Network;WebApps;",
             "StartupWMClass=grokbot-webapp-%s" % rec["id"],
             "X-GrokBot-WebApp=%s" % rec["id"]]
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, p)


# ---------------- API ----------------

def _prompt(ctx, method, title, summary, warning=None):
    ans, detail = consent.prompt(ctx["principal"], ctx.get("client"), "apps", method, title, summary, False,
                                 warning=warning)
    if ans != "once":
        raise Denied(detail)


def install(params, ctx):
    if bool(params.get("path")) == bool(params.get("url")):
        raise InstallError("give exactly one of path (bundle) or url")
    os.makedirs(paths.installed_dir(), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="grokbot-webapp-") as tmp:
        if params.get("path"):
            src, man = stage_bundle(params["path"], tmp)
            source, icon_file = "bundle", None
        else:
            man, origin, icon_file = stage_url(params["url"], tmp)
            source, src = "url", None
        host_slug = _slug((urllib.parse.urlsplit(man["start_url"]).hostname or "").replace(".", "-")) \
            if source == "url" else None
        app_id = params.get("id") or man.get("id") or _slug(man.get("short_name")) or \
            (host_slug if source == "url" and not man.get("from_manifest") else None) or _slug(man["name"]) or host_slug
        if not app_id or not ID_RE.fullmatch(app_id):
            raise InstallError("app id must match [a-z][a-z0-9-]{0,30}; pass id=")
        if app_id in RESERVED or os.path.isdir(os.path.join(system_dir(), app_id)):
            raise InstallError("id %s is reserved by the system" % app_id)
        existing = _load(_record_path(app_id))
        if source == "bundle":
            origin = local_origin(app_id)
            start = origin + _path(man["start_url"])
        else:
            start = man["start_url"]
        title = ["웹 앱 설치: %s" % man["name_ko"], "Install web app: %s" % man["name"]]
        summary = {"app": man["name"], "id": app_id, "origin": origin, "source": source,
                   "requests_scopes": ", ".join(man["scopes"]) or "-",
                   "note": "권한은 기능별로 따로 묻습니다 / each OS function is asked for separately"}
        if existing:
            summary["replaces"] = existing.get("version") or "installed version"
        warning = None
        if source == "url":
            title = ["웹 앱 설치: %s (%s)" % (man["name_ko"], origin), "Install web app: %s (%s)" % (man["name"], origin)]
            warning = ["%s 사이트의 코드가 이 앱에 허용하는 권한을 그대로 받습니다. 사이트는 언제든 코드를 바꿀 수 있습니다."
                       % origin,
                       "Code served by %s receives every permission you grant this app, and the site can change "
                       "that code at any time." % origin]
        _prompt(ctx, "apps.install", title, summary, warning)
        dest_root = os.path.join(user_dir(), app_id)
        icon = None
        if source == "bundle":
            os.makedirs(user_dir(), exist_ok=True)
            new = dest_root + ".new"
            shutil.rmtree(new, ignore_errors=True)
            shutil.copytree(src, new, symlinks=False)
            shutil.rmtree(dest_root, ignore_errors=True)
            os.replace(new, dest_root)
            rel = _pick_icon(man["icons"])
            if rel:
                cand = os.path.realpath(os.path.join(dest_root, rel.split("?")[0].lstrip("/")))
                if cand.startswith(dest_root + os.sep) and os.path.isfile(cand):
                    icon = cand
        else:
            os.makedirs(os.path.join(paths.data_home(), "grokbot", "webapp-icons"), exist_ok=True)
            if icon_file:
                icon = os.path.join(paths.data_home(), "grokbot", "webapp-icons",
                                    app_id + os.path.splitext(icon_file)[1])
                shutil.copyfile(icon_file, icon)
        rec = {"id": app_id, "kind": "webapp", "source": source, "name": man["name"],
               "name_ko": man["name_ko"], "description": man["description"], "origin": origin,
               "start_url": start, "scopes": man["scopes"], "version": man["version"], "icon": icon,
               "desktop_id": "grokbot-webapp-%s.desktop" % app_id,
               "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "installed_by": ctx["principal"]}
        tmpf = _record_path(app_id) + ".tmp"
        with open(tmpf, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmpf, _record_path(app_id))
        write_desktop(rec)
        if existing and existing.get("origin") and existing["origin"] != origin:
            perms.revoke("origin:" + existing["origin"])
    rec["system"] = False
    return rec


def uninstall(params, ctx):
    app_id = params["id"]
    rec = get(app_id)
    if rec is None:
        raise InstallError("no such app: %s" % app_id)
    if rec.get("system"):
        raise InstallError("%s is part of the system and cannot be removed" % app_id)
    keep = bool(params.get("keep_data"))
    _prompt(ctx, "apps.uninstall", ["웹 앱 제거: %s" % rec.get("name_ko"), "Remove web app: %s" % rec.get("name")],
            {"app": rec.get("name"), "id": app_id, "origin": rec.get("origin"),
             "data": "보관 / kept" if keep else "삭제 / deleted (storage, cache, grants)"})
    from . import sway
    subprocess.run(["swaymsg", "[app_id=\"grokbot-webapp-%s\"] kill" % app_id],
                   capture_output=True, timeout=5, env=sway.session_env()) if shutil.which("swaymsg") else None
    for p in (_desktop_path(app_id), _record_path(app_id)):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    if rec.get("source") == "bundle":
        shutil.rmtree(os.path.join(user_dir(), app_id), ignore_errors=True)
    if rec.get("icon") and rec["icon"].startswith(os.path.join(paths.data_home(), "grokbot", "webapp-icons")):
        try:
            os.unlink(rec["icon"])
        except OSError:
            pass
    revoked = []
    if not keep:
        shutil.rmtree(profile_dir(app_id), ignore_errors=True)
        if rec.get("origin"):
            revoked = perms.revoke("origin:" + rec["origin"])
    return {"id": app_id, "removed": True, "data_kept": keep, "revoked": revoked}


def launch(params, ctx):
    app_id = params["id"]
    rec = get(app_id)
    if rec is None:
        raise InstallError("no such app: %s" % app_id)
    cmd = ["/usr/local/bin/grokbot-settings"] if app_id == "settings" else \
        [os.environ.get("GROKBOT_WEBAPP_BIN", "/usr/local/bin/grokbot-webapp"), app_id]
    # grokbot-webapp / grokbot-settings put the window on a new workspace.
    from . import sway
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=sway.session_env())
    except OSError as e:
        raise InstallError("could not start the app: %s" % type(e).__name__)
    return {"id": app_id, "launched": True, "app_id": "grokbot-webapp-%s" % app_id}


def public(rec):
    keys = ("id", "kind", "source", "system", "name", "name_ko", "description", "origin", "start_url",
            "scopes", "version", "desktop_id", "installed_at")
    out = {k: rec.get(k) for k in keys}
    out["icon_data"] = _icon_data(rec.get("icon"))
    return out


def _icon_data(path):
    """Small icons as data: URLs, so pages with img-src 'self' data: can show them."""
    import base64
    if not path:
        return None
    ext = os.path.splitext(path)[1].lower()
    mime = {".svg": "image/svg+xml", ".png": "image/png"}.get(ext)
    try:
        if mime is None or os.path.getsize(path) > 128 * 1024:
            return None
        with open(path, "rb") as f:
            return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())
    except OSError:
        return None
