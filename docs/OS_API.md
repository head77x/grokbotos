# Grok Bot OS API (grokbotd)

`grokbotd` is the local API daemon of Grok Bot OS. It exposes the OS to
web apps, scripts and Grok Bot through one API, defined by one file:

    /usr/share/grokbot/api/os-api.schema.json

The JSON-RPC methods, the `grokbot-os` CLI and the MCP tools all come
from that schema. Read methods answer at once. Write methods change the
system only after the caller's permission for that OS function (scope)
is checked, and, in `ask` mode, after the user answers a native consent
prompt. See "Permission model" below and the threat model in
[`SECURITY.md`](../SECURITY.md#권한-모델과-위협-모델--permission-and-threat-model).

## Methods

| Method | Scope / access | Capability | Returns |
|---|---|---|---|
| `api.methods` | (none) | (none) | Methods, their capability and whether the caller is allowed |
| `system.info` | `system` read | `system.read` | OS name and version, kernel, hostname, uptime, memory, CPUs, booted bootc image, session |
| `system.resources` | `system` read | `system.read` | CPU percent (since the previous call, at most 60 s ago; `null` on the first), per-CPU, load average, memory and swap, disk space per mount, network byte counters |
| `windows.list` | `windows` read | `windows.read` | Windows from the sway tree: id, app_id, title, pid, workspace, focused, fullscreen, floating, rect. Optional param `workspace` |
| `workspaces.list` | `windows` read | `windows.read` | Workspaces: name, num, output, focused, visible, urgent |
| `dock.get` | `desktop` read | `desktop.read` | Effective dock config (`/etc/grokbot/dock.conf` + `~/.config/grokbot/dock.conf`) |
| `wallpaper.get` | `desktop` read | `desktop.read` | Effective wallpaper, mode and color, and whether the image exists |
| `apps.list` | `apps` read | `apps.read` | `installed` (records written by `grokbot-install`), `webapps` (system and installed web apps: id, name, name_ko, origin, start_url, source, requested scopes, `icon_data`) and `launchers` (visible .desktop entries). Param `include_launchers` (default true) |
| `apps.install` | `apps` write | `apps.write` | Install a web app from `path` (directory or .zip with `manifest.json`) or `url`. Always prompts, showing name, origin and requested scopes. Grants nothing. See [Web apps](#web-apps) |
| `apps.uninstall` | `apps` write | `apps.write` | Remove an installed web app (`id`); with `keep_data` false (default) also its profile and grants. Always prompts. System apps cannot be removed |
| `apps.launch` | `apps` write | `apps.write` | Open a web app (`id`) in its own app window |
| `power.status` | `power` read | `power.read` | Batteries (capacity, status) and `on_ac` |
| `network.status` | `network` read | `network.read` | Interfaces (state, MAC, wireless, addresses), default route, `online` |
| `lock.status` | `lock` read | `lock.read` | `pin_set` (never the PIN), `setup_skipped`, `locked`, `idle_running`, `screen_off_s`, `lock_s` |
| `audio.status` | `audio` read | `audio.read` | `available`, `output` and `input`: `volume_percent`, `muted` |
| `display.brightness` | `display` read | `display.read` | Backlight `devices`: name, brightness, max_brightness, percent |
| `notifications.list` | `notifications` read | `notifications.read` | `daemon_running`, `dnd`, `notifications` (id, app, summary, urgency; never the body). Param `include_history` |
| `capture.status` | `screen` read | `capture.read` | Screenshot `dir`, `count`, `recent` (name, size, mtime; never image data), `tools`. Param `limit` |
| `input.status` | `input` read | `input.read` | fcitx5 `running`, `current` (e.g. `hangul`), `active`, `input_methods`, `trigger_keys`, `xmodifiers` |
| `audio.set` | `audio` write | `audio.write` | Set output or input volume and/or mute: the default device (`target`) or one device (`id` from `audio.devices.list`). |
| `audio.devices.list` | `audio` read | `audio.read` | `outputs` and `inputs` (PipeWire nodes): `id`, `description`, `default`, `bluetooth`, `volume_percent`, `muted` |
| `audio.set_default` | `audio` write | `audio.write` | Make device `id` the default output or input (wpctl set-default); the id must be a current device |
| `display.set_brightness` | `display` write | `display.write` | Set backlight brightness in percent (1-100; never fully dark). |
| `display.nightlight.status` | `display` read | `display.read` | Night light (gammastep): enabled, temperature K, schedule `always`/`custom` with `from`/`to` (HH:MM), available, running |
| `display.nightlight.set` | `display` write | `display.write` | Change night light (2500-6000 K; schedule; times). Saved to `~/.config/grokbot/nightlight.json`, applied by the user unit `grokbot-nightlight.service` (no root). |
| `network.wifi.list` | `network` read | `network.read` | Visible Wi-Fi networks (SSID, signal, security, in use) via NetworkManager. |
| `network.wifi.connect` | `network` write | `network.write` | Connect to a Wi-Fi network (nmcli). The password is passed to NetworkManager through a 0600 file, never logged or put on a command line. |
| `network.wifi.disconnect` | `network` write | `network.write` | Disconnect a Wi-Fi device (default: the connected one). |
| `network.connections.list` | `network` read | `network.read` | Wired and VPN (WireGuard/OpenVPN) NetworkManager connections, wired IPv4 settings, ethernet devices, active VPNs. No secrets |
| `network.connection.up` / `.down` | `network` write | `network.write` | Connect / disconnect a wired or VPN connection by `uuid` (Wi-Fi profiles are refused here) |
| `network.wired.configure` | `network` write | `network.write` | IPv4 `auto` (DHCP) or `manual` with `address` (a.b.c.d/nn), `gateway` (same network) and `dns` |
| `network.vpn.import` | `network` write | `network.write` | Import a `.conf` (WireGuard) or `.ovpn` (OpenVPN) file from the home folder (files-scope path rules) |
| `network.vpn.delete` | `network` write | `network.write` | Delete a VPN profile |
| `notifications.set_dnd` | `notifications` write | `notifications.write` | Turn Do Not Disturb on or off. |
| `power.action` | `power` write | `power.write` | Suspend, reboot, power off or lock. Always shows the consent prompt, for every caller. |
| `lock.set_idle` | `lock` write | `lock.write` | Set idle timeouts in seconds (0 = off) in ~/.config/grokbot/idle.conf and restart the idle watcher. |
| `input.set` | `input` write | `input.write` | Turn the Korean input method on (active=true) or off (fcitx5-remote). |
| `keyboard.layout.status` | `input` read | `input.read` | Chosen layout id, the layout sway reports, whether Korean input (hangul) is configured, and the allow-listed layouts |
| `keyboard.layout.set` | `input` write | `input.write` | `layout` from the allow-list: applied in sway, saved to ~/.config/grokbot/keyboard.conf, and set as the fcitx5 keyboard layout with hangul kept (한/영 still works) |
| `capture.screenshot` | `screen` write | `capture.write` | Take a full-screen screenshot into the screenshot folder; returns the file name and size, never image data. |
| `camera.session.start` | `camera` write | `camera.use` | Ask to use the camera. Always prompts; while the session is open the dock shows the camera-in-use indicator. Returns a session id. |
| `microphone.session.start` | `microphone` write | `microphone.use` | Ask to use the microphone. Always prompts; while the session is open the dock shows the microphone-in-use indicator. Returns a session id. |
| `media.session.stop` | (none) write | (none) | End a camera or microphone session (the caller's own; the local user may end any). |
| `privacy.status` | `permissions` read | `privacy.read` | Open camera and microphone sessions (who, what, since when) for the in-use indicator. |
| `permissions.list` | `permissions` read | `permissions.read` | Effective mode (allow/ask/deny) per scope for every known caller, with stored grants. |
| `permissions.set` | `permissions` write | `permissions.write` | Store a mode for one caller and one scope. Always shows the consent prompt. camera, microphone and power cannot be set to allow. |
| `permissions.revoke` | `permissions` write | `permissions.write` | Remove stored grants of a caller (one scope, or all). The caller falls back to the system default. |
| `permissions.request` | (none) write | (none) | Ask the user to grant the calling origin one scope. Shows the consent prompt. Answers: Always (stored allow), This session (allow in memory until grokbotd stops), Deny (stored deny). For camera, microphone and power: Allow (stored ask, so each use still prompts) or Deny. Result `{mode, until}` (`until`: `always` or `session`). Rate-limited. |
| `appdata.list` / `appdata.read` | `app-data` read | `appdata.read` | The calling installed app's own folder `~/.local/share/grokbot/app-data/<id>/` (paths relative to it). Read max 16 MB |
| `appdata.write` / `appdata.mkdir` / `appdata.delete` | `app-data` write | `appdata.write` | Atomic write (`overwrite` default true, `parents` default true), new folder, delete (`recursive`). 16 MB per file, 100 MB / 5000 entries per app |
| `files.list` | `files` read | `files.read` | Entries of a home-folder directory (`path`, default `/` = `~`): name, path, type, size, mtime, mime, writable. Hidden entries are left out and counted |
| `files.stat` | `files` read | `files.read` | One entry |
| `files.read` | `files` read | `files.read` | File content (max 16 MB), `encoding` `utf-8` (default) or `base64` |
| `files.write` | `files-write` write | `files.write` | Create a file, or replace it with `overwrite: true` (atomic rename). Max 16 MB |
| `files.mkdir` / `files.move` / `files.trash` | `files-write` write | `files.write` | New folder; rename or move (`path`, `to`); move to the freedesktop trash (`~/.local/share/Trash`) |
| `media.keys.wait` | `mediakeys` read | `mediakeys.read` | Long poll (`timeout` ≤ 55 s; audited once per subscription, not per poll) for a media key: `{key}` (`play-pause`, `play`, `pause`, `next`, `previous`, `stop`) or `{key: null}`. The newest waiter gets the key |
| `media.keys.press` | `mediakeys` write | `mediakeys.write` | Deliver a media key (sway's XF86Audio* bindings run `grokbot-os media-key KEY`; with no waiter it falls back to playerctl) |
| `bluetooth.status` | `bluetooth` read | `bluetooth.read` | `available` (an adapter exists), `service` (bluetoothd on the bus), `powered`, `adapters`, `devices` (paired, trusted or connected: address, name, icon, paired, trusted, connected, battery_percent), `connected` (names). One BlueZ D-Bus call |
| `bluetooth.set_power` | `bluetooth` write | `bluetooth.write` | Adapter on/off (`powered`); turning on lifts a soft rfkill block |
| `bluetooth.scan` | `bluetooth` write | `bluetooth.write` | Discover for `seconds` (2-30, default 8); returns unpaired devices, strongest first |
| `bluetooth.pair` | `bluetooth` write | `bluetooth.write` | Pair, trust and (unless `connect=false`) connect `address`. grokbotd registers its own BlueZ agent for that one pairing: passkey confirmation goes to the consent prompt, a code to type on the device is shown as a notification, and a typed PIN can be passed as `pin` (Settings asks for it when the device needs one) |
| `printers.list` | `printing` read | `printing.read` | CUPS queues plus driverless IPP Everywhere / AirPrint printers found on the network (`lpstat -p -v -e`): name, `state` (idle, printing, stopped), `default`, `driverless`, `connection`; the `default` name and your `jobs` (id, printer). `available: false` with a `reason` when CUPS is not installed or not running |
| `printers.set_default` | `printing` write | `printing.write` | Your default printer (`lpoptions -d`, per user; no admin rights) |
| `print.file` | `printing` write | `printing.write` | Print `path` from the home folder, or from an open USB drive with `volume` (files path rules), up to 64 MB; `copies` 1-99, `sides` `one-sided` / `two-sided-long-edge`. Returns the `job` id |
| `print.test_page` / `print.job.cancel` | `printing` write | `printing.write` | CUPS test page on `printer`; cancel one of your `job`s |
| `bluetooth.connect` / `bluetooth.disconnect` / `bluetooth.trust` / `bluetooth.remove` | `bluetooth` write | `bluetooth.write` | Connect, disconnect, set `trusted`, forget (unpair) a device by `address` (`AA:BB:CC:DD:EE:FF`, validated) |
| `storage.list` | `storage` read | `storage.read` | Removable volumes only (USB, SD, external; never the system disk) from UDisks2: `id` (sdb1), `name`, `label`, `drive`, `fs`, `size`, `mounted`, `mount_points`, `read_only`, `ejectable`, `encrypted`, `locked`, `backing`. A locked LUKS container is listed with `locked=true`; once unlocked its file system is a volume of its own (`dm_2d0`, `backing` = the container). exFAT (kernel `exfat`) and NTFS (kernel `ntfs3`, `ntfs-3g` fallback; `/etc/udisks2/mount_options.conf`) open like any other file system |
| `storage.mount` / `storage.unmount` | `storage` write | `storage.write` | Open a volume under `/run/media/<user>/`; close it, and with `eject=true` close the drive's other volumes (locking unlocked encrypted ones) and eject / power it off |
| `storage.unlock` | `storage` write | `storage.write` | Unlock a LUKS drive. The passphrase is typed into the secure prompt (grokbot-consent with a hidden field), never passed as a parameter, command-line argument, file or log entry; grokbotd hands it to UDisks2 `Encrypted.Unlock` over D-Bus in-process. That prompt is the consent (`x-secret-prompt`: no second allow prompt; `deny` still denies; no "always"). `mount` (default true) opens the file system |
| `storage.lock` | `storage` write | `storage.write` | Unmount an unlocked encrypted volume and lock its LUKS container |
| `power.profile.status` | `power-mode` read | `power-mode.read` | `available`, `active` (`power-saver`, `balanced`, `performance`), `profiles` offered, `degraded` (power-profiles D-Bus API, tuned-ppd) |
| `power.profile.set` | `power-mode` write | `power-mode.write` | Switch to `profile` (must be offered). Separate from `power` so it does not prompt every time; local default `allow` |
| `audit.list` | `audit` read | `audit.read` | Recent audit log entries, newest last. Filters: principal, decision, method. |

Wired and VPN profiles are system NetworkManager connections. `/usr/share/polkit-1/rules.d/50-grokbot-network.rules` lets the active local session user change them (`settings.modify.system`; hostname and global DNS stay admin-only); grokbotd asks before each change.

**App-data scope rules.** The app is identified by the calling origin (`<id>.app.localhost`); only installed web apps get `app-data`, with no prompt, unless the user denied it. Local callers are denied. Paths with `..`, `.`, NUL, backslash or over-long names are refused and every component is opened with `O_NOFOLLOW`, so symlinks cannot escape. `apps.uninstall` deletes the folder unless `keep_data`. JS helper: `/_grokbot/appdata.js` (`GrokAppData`).

**Files scope rules.** Paths are relative to the home folder (`/Documents/a.txt`, `~/Documents/a.txt` and `Documents/a.txt` are the same). Refused: `..`, any path that resolves outside `~` (symlinks included), and every hidden component (`.config`, `.local`, `.ssh`, ...), so a `files` grant can never read or rewrite grants, keys or other apps' data. Seeing (`files`) and changing (`files-write`) are separate scopes with separate grants.

Errors are JSON-RPC errors:

| Code | Meaning |
|---|---|
| -32700 | Parse error |
| -32600 | Invalid request |
| -32601 | Method not found |
| -32602 | Invalid parameters (checked against the schema) |
| -32001 | Permission denied: the scope's mode is `deny`, or the user answered Deny / did not answer the prompt. `error.data` has `scope`, `access`, `mode`, `capability` and, after a prompt, `consent` (`user`, `timeout`, `no_prompt`) |
| -32000 | Backend error (for example, sway is not running) |

## Transports

| Transport | Address | Who | Access |
|---|---|---|---|
| Unix socket | `$XDG_RUNTIME_DIR/grokbot/api.sock` (dir 0700, socket 0600) | The session user: the CLI, MCP, and Grok Bot through local-exec | `SO_PEERCRED` must match the daemon's uid. Every read is allowed; writes follow the `local` modes |
| HTTP | `127.0.0.1:7311` only | Web apps (and the Settings app) | The TCP peer must be the same uid (checked in `/proc/net/tcp`). `Origin` counts only from a host browser, and app origins also need the launcher cookie. Deny by default, per origin and scope |

The unix socket protocol is one JSON-RPC 2.0 request per line, with one
response per line.

The HTTP endpoints are:

- `POST /v1/rpc`: JSON-RPC 2.0. `Content-Type: application/json` is required.
- `GET /v1/health`: `{"ok": true, ...}`. Returns no OS data.
- `GET /v1/schema`: the API schema.

## Permission model

Permissions are per **OS function (scope)**, not per app, and there is no install-time blanket grant. Every method has a `scope` and an `access` (`read` or `write`) in the schema.

| Scope | 기능 / Function | Note |
|---|---|---|
| `system` | 시스템 정보 / System information |  |
| `windows` | 창과 작업 공간 / Windows and workspaces |  |
| `desktop` | 독과 배경화면 / Docks and wallpaper |  |
| `apps` | 앱 목록 / Apps |  |
| `display` | 화면 밝기 / Display |  |
| `audio` | 소리 / Sound |  |
| `network` | 네트워크와 Wi-Fi / Network and Wi-Fi |  |
| `bluetooth` | 블루투스 / Bluetooth | local default `ask`; Settings `allow` |
| `storage` | USB와 외장 저장장치 / USB and removable storage | local default `ask`; Settings `allow` |
| `power` | 전원(절전, 다시 시작, 끄기) / Power (suspend, restart, shut down) | always asks for writes |
| `power-mode` | 전원 모드(절전, 균형, 성능) / Power mode | local and Settings `allow` |
| `input` | 키보드와 한글 입력 / Keyboard and input method |  |
| `notifications` | 알림과 방해 금지 / Notifications and Do Not Disturb |  |
| `lock` | 화면 잠금과 대기 / Screen lock and idle |  |
| `screen` | 화면 캡처 / Screen capture |  |
| `files` | 파일 / Files | reserved, no methods yet |
| `camera` | 카메라 / Camera | always asks for writes |
| `microphone` | 마이크 / Microphone | always asks for writes |
| `location` | 위치 / Location | reserved, no methods yet |
| `permissions` | 권한 관리 / Permission management |  |
| `audit` | 감사 기록 / Audit log |  |

Each caller (principal) has one **mode per scope**:

- `allow`: the call runs without a prompt.
- **Local identity.** A unix-socket caller is identified by the kernel, not by what it says: grokbotd takes the peer pid from `SO_PEERCRED` and reads `/proc/<pid>/cgroup`, `exe`, `cmdline` and `cwd`. If the process runs in its own systemd unit (a `.service`, or an `app-*.scope` with its random suffix dropped) the principal is `local:uid=N:unit=<unit>`; otherwise `local:uid=N:exe=<path>`, plus `:script=<path>` (or `module:<name>`) for interpreters such as python, sh and node. Grants are stored for that principal. A caller that cannot be identified is `local:uid=N:unknown` and gets no "Always" button. `permissions.whoami` (and `grokbot-os whoami`) returns the caller's principal. Bare `local:uid=N` grants from 0.2.0 are no longer applied. HTTP callers keep their `Origin` principal.
- `ask`: every call shows the native consent prompt (`grokbot-consent`, a GTK layer-shell dialog on the overlay layer with exclusive keyboard). It says **who** (origin, or the local program as the daemon identified it, plus the name the client gave, marked as self-reported), **what scope**, and **what action** (title and redacted parameters). Buttons: 거부 / Deny (default, Esc); 이번 한 번만 / Allow once (this call only, nothing stored); 이번 세션 동안 / This session (kept in grokbotd memory until it stops: logout or reboot; not for camera, microphone, power or calls marked `consent: always`); 항상 허용 / Always allow (stored). `permissions.request` offers Deny / This session / Always (for camera, microphone and power: Deny / Allow, which stores `ask`). The prompt ignores clicks and keys for its first 0.6 s (so input meant for the window underneath cannot answer it), answers on button press as well as release, and re-asserts its exclusive keyboard grab every 0.7 s so a window that opens later cannot take the keyboard. No answer in 60 seconds, or no display to show it on, counts as Deny. Only one prompt is shown at a time.
- `deny`: the call fails with -32001.

Where the mode comes from (first match wins):

1. User grants in `~/.config/grokbot/api-grants.json` (0600). They are written only by grokbotd: the prompt's Always allow, `permissions.request`, `permissions.set` / `permissions.revoke`, `grokbot-os grant` / `revoke` and the Settings app.
2. System defaults in `/etc/grokbot/api-permissions.json`: `local` (modes for the user's own processes) and `origins` (`{"http://x.app.localhost:7311": {"audio": "ask"}}`). The phase-1 form, a list of capabilities, still works but grants **reads only**; `"*"` is ignored.
3. Built in: the local user may read everything and is asked for writes; anything else is denied.

The local user's **reads are always allowed**, whatever is stored (the dock polls status every 2 s); stored modes for `local` govern writes only.

Hard rules that no file can change:

- `camera`, `microphone` and `power` writes **always ask**, with no Always allow button; `permissions.set` cannot store `allow` for them.
- `power.action`, `camera.session.start`, `microphone.session.start` and `permissions.set` prompt on **every** call, even for the local user and even when the scope is `allow`.
- An origin with no grant for a scope is denied **without** a prompt, so a page cannot spam prompts. It may call `permissions.request {scope, reason}` once per 10 minutes per scope; the answer is stored (Always: allow, Once: ask, Deny: deny).
- HTTP callers without an `Origin`, and `Origin: null`, get nothing, and cannot trigger a prompt.

Camera and microphone: a client calls `camera.session.start` / `microphone.session.start` before using the device and `media.session.stop` when done (sessions also end after `duration_s`, at most 1 hour). Every start prompts. While a session is open, the dock status area shows a red camera or microphone indicator with who is using it (`privacy.status`). grokbotd does not sit between apps and `/dev/video*` or PipeWire, so this is a cooperative protocol for API clients, not enforcement (see SECURITY.md).

Revoke: `permissions.revoke {principal, scope?}`, `grokbot-os revoke <origin> [scope]`, or the Permissions page of the Settings app. Revoking removes the stored grant; the caller falls back to the system default.

## Security model

- **Loopback only.** The HTTP server binds 127.0.0.1, never 0.0.0.0. It runs as a systemd **user** service, never as root (`NoNewPrivileges`, address-family and namespace restrictions, `UMask=0077`). Power actions go through `systemctl` (logind and polkit decide, as for the session user).
- **Same user only.** The unix socket checks `SO_PEERCRED`. The HTTP port checks that the connecting TCP socket belongs to the daemon's uid (`/proc/net/tcp`), so another local user cannot forge an `Origin` and borrow a web app's grants.
- **Host check (DNS rebinding).** The `Host` header must be `127.0.0.1:7311`, `localhost:7311` or `<id>.app.localhost:7311`. Any other host gets 403.
- **Origin semantics.** <a id="origin-semantics"></a>`Origin` only identifies callers that are browsers: page scripts cannot change it, but any local program can write any `Origin`. So grokbotd believes it only when (1) the TCP peer process (found from the socket inode in `/proc/net/tcp` and `/proc/*/fd`) runs a browser binary (`firefox`, `chromium`, `chrome`, `grok-bot`, …) whose root is the host root, so not a Flatpak or other sandbox; and (2) for `http://<id>.app.localhost` origins, the request carries the app's HttpOnly cookie `gbt` = HMAC-SHA256(key, origin). The key is `~/.local/state/grokbot/webapp-key` (0600). The launchers (`grokbot-webapp`, `grokbot-settings`) open `<start_url>?gbt=<token>`; grokbotd sets the cookie (`SameSite=Strict`) and redirects to the clean URL. Otherwise the call is `http:no-origin`, which gets nothing, and the audit log records `origin_untrusted_peer` or `app_token_missing`. Limits: a same-uid host program can read the key or drive the browser; it could use the unix socket anyway (SECURITY.md item 1). Flatpak browsers' origins are not trusted.
- **CORS** headers are sent only to origins with some grant. Preflight from any other origin returns 403. Because `application/json` is required, a cross-site HTML form cannot send a "simple" request.
- **Secrets.** Parameters marked `x-secret` (the Wi-Fi password) are replaced by `***` in the audit log and the prompt. The Wi-Fi password goes to `nmcli` through a 0600 `passwd-file` in `$XDG_RUNTIME_DIR`, never on a command line.
- **Limits.** Bodies over 64 KB are rejected. The HTTP access log is off, because the audit log is the record.
- **Audit.** Every call is appended to `~/.local/state/grokbot/audit.jsonl` (mode 0600, rotated at 5 MB, 5 old generations `.1`–`.5`), whether it was allowed, denied or failed. Transport-level rejects that any web page can cause (bad Host, wrong Content-Type, refused preflight, foreign uid, ignored Origin) go to `audit-rejects.jsonl` instead, aggregated: the first per principal and error per minute, then one summary line with a `count`; at most 20 principals per minute, the rest as `*other*`. Every logged string is cut to 256 characters. Each line records the time, transport, principal, self-reported client, method, scope, access, mode and its source, the consent answer, redacted parameters for writes, decision and error. Read it with `audit.list` (scope `audit`), `grokbot-os audit` or the Settings app.

## System web apps

grokbotd serves static web apps from the read-only image, `/usr/share/grokbot/webapps/<id>/`, on their own origin `http://<id>.app.localhost:7311` (only `GET`, only files under that directory, no dotfiles or traversal, fixed content types). Every response carries a strict CSP (`script-src 'self'`, `connect-src 'self'`, no inline script, `frame-ancestors 'none'`), `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. The app reaches the OS only through `POST /v1/rpc` on the same origin, with that origin's grants; if a browser omits `Origin` on a same-origin request, `Sec-Fetch-Site: same-origin` plus a served `Host` identifies it.

System apps: **System Monitor** (`sysmon`, see [Web apps](#web-apps)) and **Settings** (`grokbot-settings`, `manual/settings.md`). Its system grant is in `/etc/grokbot/api-permissions.json`: `system`, `network`, `audio`, `display`, `notifications`, `lock`, `input`, `permissions`, `audit` allow, `power` ask; nothing else. It is shown in Firefox (already in the image; Chromium is not) with a dedicated profile, its tab strip and address bar hidden by userChrome.css, and app_id `grokbot-settings`, tiled by sway so the docks stay visible (`--kiosk` was tried and covers the docks).

## Web apps

Installed web apps are first-class apps: they show in the launcher and the dock (never on the desktop, which has no icons), open in their own window, keep their data offline, and reach the OS only with per-scope grants.

- **Sources.** `apps.install` takes a local bundle (`path`: a directory or `.zip` with a W3C `manifest.json`) or a `url` (`https://`, or `http://` on loopback). For a URL grokbotd reads the page's `<link rel="manifest">`, the manifest and one icon (size-limited, redirects re-checked); without a manifest it uses the page title. Bundles are checked before anything is copied: only web file types (html, js, css, images, fonts, json, wasm, txt), no dotfiles, no symlinks, no `..` in zips, at most 50 MB / 2000 files. A bundle's `start_url` must be a path inside it.
- **Manifest extension.** An optional `"grokbot"` member: `id` (`[a-z][a-z0-9-]{0,30}`), `name_ko`, and `scopes` (the OS functions it will ask for; unknown scopes and `*` are refused). Scopes are informational: shown at install time and in Settings, never granted by installing.
- **Origins.** A bundle is served by grokbotd on `http://<id>.app.localhost:7311` from `~/.local/share/grokbot/webapps/<id>/` (system apps in `/usr/share/grokbot/webapps/` win; their ids and `settings`, `api`, `www` are reserved). A URL app keeps the site's own origin. The origin is the principal for grants.
- **Consent.** Install and uninstall always prompt (no "Always" button), naming the app, its origin, source and requested scopes. After install the origin is *known* (it gets CORS answers, so it can call `permissions.request`) but every scope is still `deny` until the user grants it through the prompt (`permissions.request`, or Settings > Permissions).
- **Launcher.** Install writes `~/.local/share/applications/grokbot-webapp-<id>.desktop` (`Exec=grokbot-webapp <id>`, `StartupWMClass=grokbot-webapp-<id>`). `grokbot-webapp <id>` opens Firefox with app_id `grokbot-webapp-<id>`, a profile of its own in `~/.local/share/grokbot/webapp-profiles/<id>` and userChrome.css hiding the tab strip and address bar; sway tiles it on a new workspace (no fullscreen, the docks stay visible). One window per app.
- **Offline storage.** Because each app has its own profile, its service worker, Cache Storage, IndexedDB and localStorage are separate from every other app and the normal browser and survive restarts. The profile keeps storage on shutdown, auto-grants `navigator.storage.persist()`, and lists the app host in `dom.securecontext.allowlist` so service workers run on `http://<id>.app.localhost`. Uninstall deletes the profile unless `keep_data` is true.
- **Shipped apps.** Files (`files`: browse `~`, open text and images, edit and save text, new folder, rename, trash; asks for `files`, then `files-write` only if you want to change things), Notes (`notes`: no OS scope at all; notes stay in the app's IndexedDB and work offline), Media Player (`player`: plays files you pick or drop, which never leave the computer; asks for `mediakeys` to take the keyboard Play/Next/Previous keys through `media.keys.wait`). All ship with no grants and a Korean UI with an English toggle.
- System Monitor (`sysmon`, `/usr/share/grokbot/webapps/sysmon`, Korean UI with an English toggle) shows CPU, memory, disk, battery, network and an audit summary. It ships with **no grants**: on first run it asks for `system`, `power`, `network` and `audit` one prompt at a time, and each card offers to ask again. It keeps an hour of CPU/memory history in IndexedDB and its shell works offline through a service worker.

## CLI: grokbot-os

```
grokbot-os [--json] methods
grokbot-os [--json] <method> [key=value ...]    # grokbot-os system.info
grokbot-os [--json] <ns> <verb> [key=value ...] # grokbot-os windows list workspace=2
grokbot-os audit [-n N] [principal=P] [decision=allow|deny|error] [method=M] [access=write]
grokbot-os grants [principal]                    # modes per scope
grokbot-os grant <principal> <scope> allow|ask|deny  # always asks you to confirm
grokbot-os revoke <principal> [scope]
grokbot-os mcp                                   # MCP server on stdio
```

- `--json` prints `{"ok": true, "result": ...}` or `{"ok": false, "error": ...}`.
- Exit codes: 0 on success; 2 for an unknown method, invalid parameters or a denied call; 1 when the daemon is unreachable or the call failed.

## MCP

`grokbot-os mcp` is an MCP server (stdio, newline-delimited JSON-RPC, protocol 2025-06-18). It implements `initialize`, `ping`, `tools/list` and `tools/call`. Each API method is a tool, with dots replaced by underscores (`windows_list`), and its `inputSchema` is the method's params schema. Read tools carry `readOnlyHint: true`; write tools `false`, and `power_action` has `destructiveHint: true`. A call that the user denies returns `isError` with the -32001 error. The MCP client's `clientInfo.name` is shown in the prompt as a self-reported name. The server calls the daemon over the unix socket, so it has the user's access and every call is audited.

Grok Bot can use the API today through local-exec, with
`grokbot-os --json <method>`. Whether the Grok Bot desktop app can attach a local stdio MCP server directly is unconfirmed (see the audit).

## Examples

```
$ grokbot-os windows list
$ grokbot-os --json dock.get
$ curl -s 127.0.0.1:7311/v1/health
$ curl -s -H 'Origin: http://notes.app.localhost:7311' -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"system.info"}' 127.0.0.1:7311/v1/rpc
```

The last call always returns 403 (-32001): curl is not a browser, so its `Origin` is ignored (see [Origin semantics](#origin-semantics)).

```
$ grokbot-os audio.set volume_percent=40          # local, audio=allow: no prompt
$ grokbot-os network.wifi.connect ssid=Home password=-   # asks for the password; network=ask: prompt
$ grokbot-os power action action=suspend          # always prompts
$ grokbot-os grants http://notes.app.localhost:7311
$ grokbot-os revoke http://notes.app.localhost:7311 audio
$ grokbot-os audit decision=deny
```

## Service

```
systemctl --user status grokbotd
journalctl --user -u grokbotd
```

The build enables the service with `systemctl --global enable`. It finds the sway IPC socket in `$XDG_RUNTIME_DIR` when a call needs it, so it can start before sway. The sway config imports `WAYLAND_DISPLAY`, `SWAYSOCK` and `XDG_DATA_DIRS` into the user manager.

## Files

| Path | Purpose |
|---|---|
| `system_files/usr/share/grokbot/api/os-api.schema.json` | API schema |
| `system_files/usr/lib/grokbot/grokbotd/` | Daemon (python3 standard library only) |
| `system_files/usr/lib/grokbot/grokbot_os_cli.py`, `usr/local/bin/grokbot-os` | CLI and MCP |
| `system_files/usr/local/bin/grokbotd` | Daemon launcher |
| `system_files/usr/lib/systemd/user/grokbotd.service` | User service |
| `system_files/etc/grokbot/api-permissions.json` | System default modes (`local`, `origins`) |
| `system_files/usr/lib/grokbot/grokbot_consent.py`, `usr/local/bin/grokbot-consent` | Consent prompt |
| `~/.config/grokbot/api-grants.json` | User grants (written by grokbotd only) |
| `tests/grokbotd/test_grokbotd.py`, `tests/grokbotd/test_consent.py`, `tests/test-grokbotd.sh` | Tests (fake sway IPC, fake tools, fake prompt) |

Override variables for tests: `GROKBOT_API_SOCK`, `GROKBOT_API_PORT`, `GROKBOT_API_SCHEMA`, `GROKBOT_API_SYS_PERMISSIONS`, `GROKBOT_AUDIT_LOG`, `GROKBOT_API_GRANTS`, `GROKBOT_CONSENT_CMD`, `GROKBOT_CAPTURE_CMD`, `GROKBOT_LIB`, plus the usual `XDG_*` directories.
