"""appdata.* : each installed web app's own private data folder.

An app (caller origin:<its origin>, e.g. http://todo.app.localhost:7311)
reads and writes only ~/.local/share/grokbot/app-data/<app id>/. The app
id comes from the installed-app record that owns the calling origin, never
from a parameter, so one app cannot name another app's folder. Scope
"app-data" is allowed silently for installed apps (it reaches nothing
outside the app's own folder) and denied for everyone else, unless the
user stored a "deny" for that app.

Paths are relative to the app folder ("todos.json", "sub/a.txt"; a leading
"/" means the folder root). Every component is opened with
O_NOFOLLOW relative to its parent's fd (openat), so ".." and symlinks
cannot leave the folder even if something placed a link inside it.
apps.uninstall removes the folder unless keep_data is true.
"""
import base64
import contextlib
import os
import shutil
import stat

from .backends import BackendError
from . import paths

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_DEPTH = 16
DIRF = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def root_dir():
    return os.path.join(paths.data_home(), "grokbot", "app-data")


def app_dir(app_id):
    return os.path.join(root_dir(), app_id)


def app_for(principal):
    """The installed app that owns this caller's origin, or None."""
    if not principal.startswith("origin:"):
        return None
    origin = principal[len("origin:"):]
    from . import webapps
    for a in webapps.all_apps():
        if a.get("origin") == origin and webapps.ID_RE.fullmatch(a.get("id", "")):
            return a
    return None


def parts(path):
    """Validated path components; [] is the folder itself."""
    if not isinstance(path, str) or "\x00" in path or "\\" in path:
        raise BackendError("bad path")
    p = path[1:] if path.startswith("/") else path
    if p.startswith("/"):
        raise BackendError("bad path")
    out = [c for c in p.split("/") if c != ""]
    if len(out) > MAX_DEPTH:
        raise BackendError("path too deep")
    for c in out:
        if c in (".", "..") or len(c.encode("utf-8")) > 255:
            raise BackendError("bad path: %r is not allowed" % c)
    return out


def _app_id(ctx):
    a = app_for(ctx["principal"])
    if a is None:
        raise BackendError("app-data is only for installed web apps")
    return a["id"]


@contextlib.contextmanager
def _dirfd(app_id, comps, create=False):
    """fd of the folder comps[] inside the app's folder (O_NOFOLLOW at every step)."""
    base = app_dir(app_id)
    if create:
        os.makedirs(root_dir(), mode=0o700, exist_ok=True)
        try:
            os.mkdir(base, 0o700)
        except FileExistsError:
            pass
    try:
        fd = os.open(base, DIRF)
    except FileNotFoundError:
        raise BackendError("no such file or folder: /%s" % "/".join(comps))
    except OSError:
        raise BackendError("app data folder is not usable")
    try:
        for c in comps:
            if create:
                try:
                    os.mkdir(c, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                nfd = os.open(c, DIRF, dir_fd=fd)
            except FileNotFoundError:
                raise BackendError("no such file or folder: /%s" % "/".join(comps))
            except OSError:  # ELOOP (symlink), ENOTDIR
                raise BackendError("not a folder: /%s" % "/".join(comps))
            os.close(fd)
            fd = nfd
        yield fd
    finally:
        os.close(fd)


def _entry(fd, name, rel):
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    kind = "dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
    return {"name": name, "path": rel, "type": kind, "size": st.st_size if kind == "file" else 0,
            "mtime": int(st.st_mtime)}


def usage(app_id):
    total, n = 0, 0
    for dp, dns, fns in os.walk(app_dir(app_id)):
        for f in fns:
            n += 1
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
        n += len(dns)
    return total, n


def appdata_list(params, ctx):
    app_id = _app_id(ctx)
    comps = parts(params.get("path", "/"))
    if not os.path.isdir(app_dir(app_id)) and not comps:
        return {"app": app_id, "path": "/", "entries": []}
    with _dirfd(app_id, comps) as fd:
        names = sorted(os.listdir(fd))[:MAX_ENTRIES]
        base = "/" + "/".join(comps)
        ents = [_entry(fd, n, (base.rstrip("/") + "/" + n)) for n in names]
    total, _ = usage(app_id)
    return {"app": app_id, "path": base, "entries": ents, "used": total, "quota": MAX_TOTAL}


def _split(params):
    comps = parts(params["path"])
    if not comps:
        raise BackendError("path names the app folder itself")
    return comps[:-1], comps[-1]


def appdata_read(params, ctx):
    app_id = _app_id(ctx)
    d, name = _split(params)
    with _dirfd(app_id, d) as fd:
        try:
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        except FileNotFoundError:
            raise BackendError("no such file or folder: %s" % params["path"])
        except OSError:
            raise BackendError("not a regular file: %s" % params["path"])
        with os.fdopen(f, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise BackendError("not a regular file: %s" % params["path"])
            data = fh.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise BackendError("file is larger than %d MB" % (MAX_FILE // 1048576))
    if params.get("encoding", "utf-8") == "utf-8":
        try:
            return {"path": params["path"], "encoding": "utf-8", "size": len(data), "data": data.decode("utf-8")}
        except UnicodeDecodeError:
            raise BackendError("not UTF-8 text; ask for encoding=base64")
    return {"path": params["path"], "encoding": "base64", "size": len(data),
            "data": base64.b64encode(data).decode("ascii")}


def appdata_write(params, ctx):
    app_id = _app_id(ctx)
    d, name = _split(params)
    if params.get("encoding", "utf-8") == "base64":
        try:
            data = base64.b64decode(params["data"], validate=True)
        except ValueError:
            raise BackendError("data is not base64")
    else:
        data = params["data"].encode("utf-8")
    if len(data) > MAX_FILE:
        raise BackendError("too large (max %d MB per file)" % (MAX_FILE // 1048576))
    total, n = usage(app_id) if os.path.isdir(app_dir(app_id)) else (0, 0)
    if total + len(data) > MAX_TOTAL:
        raise BackendError("app data quota (%d MB) exceeded" % (MAX_TOTAL // 1048576))
    if n >= MAX_ENTRIES:
        raise BackendError("too many files in app data")
    with _dirfd(app_id, d, create=bool(params.get("parents", True))) as fd:
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):
                raise BackendError("exists and is not a regular file: %s" % params["path"])
            if not params.get("overwrite", True):
                raise BackendError("file exists; pass overwrite=true")
        except FileNotFoundError:
            pass
        tmp = ".%s.gbtmp" % name[:200]
        f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
        try:
            with os.fdopen(f, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=fd)
            raise
        return _entry(fd, name, "/" + "/".join(d + [name]))


def appdata_mkdir(params, ctx):
    app_id = _app_id(ctx)
    comps = parts(params["path"])
    if not comps:
        raise BackendError("path names the app folder itself")
    with _dirfd(app_id, comps, create=True) as fd:
        del fd
    return {"path": "/" + "/".join(comps), "type": "dir"}


def appdata_delete(params, ctx):
    app_id = _app_id(ctx)
    d, name = _split(params)
    with _dirfd(app_id, d) as fd:
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            raise BackendError("no such file or folder: %s" % params["path"])
        if stat.S_ISDIR(st.st_mode):
            if params.get("recursive"):
                shutil.rmtree(name, dir_fd=fd)
            else:
                try:
                    os.rmdir(name, dir_fd=fd)
                except OSError:
                    raise BackendError("folder is not empty; pass recursive=true")
        else:
            os.unlink(name, dir_fd=fd)  # a symlink is removed, never followed
    return {"path": params["path"], "deleted": True}


def remove_all(app_id):
    if app_id and os.path.basename(app_id) == app_id:
        shutil.rmtree(app_dir(app_id), ignore_errors=True)


CTX_METHODS = {
    "appdata.list": appdata_list,
    "appdata.read": appdata_read,
    "appdata.write": appdata_write,
    "appdata.mkdir": appdata_mkdir,
    "appdata.delete": appdata_delete,
}
