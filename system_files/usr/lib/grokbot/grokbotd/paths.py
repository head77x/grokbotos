"""Filesystem locations. Every one can be overridden by an environment
variable so tests run against a temporary tree."""
import os

HOME = os.path.expanduser("~")


def _env(name, default):
    return os.environ.get(name) or default


def runtime_dir():
    return _env("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())


def config_home():
    return _env("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))


def state_home():
    return _env("XDG_STATE_HOME", os.path.join(HOME, ".local", "state"))


def data_home():
    return _env("XDG_DATA_HOME", os.path.join(HOME, ".local", "share"))


def socket_path():
    return _env("GROKBOT_API_SOCK", os.path.join(runtime_dir(), "grokbot", "api.sock"))


def schema_path():
    return _env("GROKBOT_API_SCHEMA", "/usr/share/grokbot/api/os-api.schema.json")


def audit_path():
    return _env("GROKBOT_AUDIT_LOG", os.path.join(state_home(), "grokbot", "audit.jsonl"))


def permissions_paths():
    return [
        _env("GROKBOT_API_SYS_PERMISSIONS", "/etc/grokbot/api-permissions.json"),
        os.path.join(config_home(), "grokbot", "api-permissions.json"),
    ]


def dock_confs():
    return [
        _env("GROKBOT_DOCK_SYS_CONF", "/etc/grokbot/dock.conf"),
        os.path.join(config_home(), "grokbot", "dock.conf"),
    ]


def desktop_confs():
    return [
        _env("GROKBOT_DESKTOP_SYS_CONF", "/etc/grokbot/desktop.conf"),
        os.path.join(config_home(), "grokbot", "desktop.conf"),
    ]


def installed_dir():
    return os.path.join(data_home(), "grokbot", "installed")


def xdg_data_dirs():
    default = ":".join([
        data_home(),
        os.path.join(data_home(), "flatpak", "exports", "share"),
        "/var/lib/flatpak/exports/share", "/usr/local/share", "/usr/share",
    ])
    dirs = [data_home()] + _env("XDG_DATA_DIRS", default).split(":")
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def sysfs():
    return _env("GROKBOT_SYSFS", "/sys")


def procfs():
    return _env("GROKBOT_PROCFS", "/proc")


def design_dir():
    return _env("GROKBOT_DESIGN_DIR", "/usr/share/grokbot/design")


def webapps_dir():
    return _env("GROKBOT_WEBAPPS_DIR", "/usr/share/grokbot/webapps")


def http_port():
    return int(_env("GROKBOT_API_PORT", "7311"))
