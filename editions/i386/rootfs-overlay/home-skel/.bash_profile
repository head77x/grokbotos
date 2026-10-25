# Grok Bot OS i386: start the kiosk session on tty1 only.
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
  exec /usr/local/bin/grokbot-session
fi
