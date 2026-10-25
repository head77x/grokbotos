# Grok Bot OS — i386 (32-bit) edition

Long-lived branch: **`edition/i386`**. It is never merged into `main`.
This is Roadmap Phase H: a browser-only Grok Bot for old 32-bit PCs
(reference machine: HP Compaq nw8000, Pentium M, ≤2 GB RAM).

## Design

| Piece | Choice | Why |
|---|---|---|
| Base | Debian 12 **bookworm** i386, debootstrap minbase | Debian 13 (trixie) no longer ships i386 kernels or installer; bookworm has LTS security support until mid-2028. Fedora and Chromium/Electron dropped 32-bit. |
| Kernel | `linux-image-686` (non-PAE) | Early Pentium M (Banias, and Dothan before the PAE-flag fix) do not report PAE. The 686 flavour boots on all of them. |
| Session | tty1 autologin → `sway` (wlroots **pixman** renderer) | No GL needed, so the nw8000's Radeon 9600 (r300) and QEMU's std VGA both work. `GROKBOT_GPU=1` in `/etc/default/grokbot` turns GL back on. |
| Browser | `firefox-esr` (i386) with Korean UI | Grok Bot is a web app. Firefox needs SSE2, which every Pentium M has. |
| Home | local splash `file:///usr/share/grokbot/splash/` | Shows the Grok Bot face (`/_grokbot/` `mascot.js`, shared with main) and an "Open Grok Bot" button to `https://grok.com/`. No SpaceXAI logos. |
| Bar | swaybar at the bottom, status script | No icons. Wi-Fi · battery · clock, small, at the right end. |
| Korean | `fcitx5` + `fcitx5-hangul`, GTK3/4 frontends | Toggle with **Shift+Space**, **Hangul (한/영)** or Ctrl+Space. Works in Firefox through the GTK IM module. |
| Fonts | `fonts-nanum` (≈20 MB, much smaller than Noto CJK) | |
| Network | NetworkManager (`nmcli`/`nmtui` from foot) | Intel 2200BG firmware (`firmware-ipw2x00`) included; build with `WIFI_FW=0` to leave out non-free firmware. |

Keys: `Super+Return` new browser window, `Ctrl+Alt+T` terminal (foot),
`Super+Q` close, `Super+Shift+E` power off / reboot. The browser is
relaunched if it is closed.

## Out of scope for i386 (for now)

The i386 edition is only a browser. These features of the main image are **not** included:

- `grokbotd` and the whole local API (`/_grokbot/api`): consent prompts, scopes, `files`, `app-data`, `apps.install/launch`, printers, storage (LUKS/exFAT/NTFS), Bluetooth, display/night light, audio, capture.
- Grok Bot Dock, Settings, Files, Notes, and the other bundled web apps.
- bootc/OCI image updates and rollback. Updates are `apt` (security archive) or a new ISO.
- Secure Boot and UEFI (the nw8000 is BIOS-only; the ISO is BIOS/GRUB).
- Installer to disk and persistent storage. The live ISO forgets everything at reboot, including logins. See next steps.

## Build

Needs podman (or `ENGINE=docker`) and root for a `--privileged` container. About 15–25 min, ~2 GB scratch.

```sh
sudo editions/i386/build.sh            # → editions/i386/out/grokbot-os-i386.iso
sudo WIFI_FW=0 editions/i386/build.sh  # without non-free Wi-Fi firmware
```

`build-in-container.sh` does the work: debootstrap → packages → `rootfs-overlay/` → squashfs → `grub-mkrescue`.

## Test in QEMU (TCG, no KVM)

```sh
qemu-system-i386 -accel tcg -cpu coreduo,-pae,-vmx -m 1024 -smp 1 \
  -cdrom editions/i386/out/grokbot-os-i386.iso -boot d \
  -vga std -nic user,model=e1000 -usb -device usb-tablet
```

`coreduo,-pae` gives a Pentium-M-like CPU: SSE2 (Firefox needs it) but no PAE, so it
proves the non-PAE kernel boots. CPUs without SSE2 (Pentium III and older) cannot run Firefox.

## Real hardware (nw8000)

Write the ISO to a CD or USB stick (`dd`). The nw8000 BIOS can boot USB on some
BIOS versions only; a CD always works. Wi-Fi: Intel PRO/Wireless 2200BG (ipw2200).

## CI

No GitHub Actions workflow on this branch yet. A future workflow would live only on
`edition/i386`: run `editions/i386/build.sh` on `ubuntu-latest` and upload the ISO as an artifact.
