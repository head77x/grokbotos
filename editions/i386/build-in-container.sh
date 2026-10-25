#!/bin/sh
# Runs inside debian:bookworm (amd64 host is fine: i386 binaries run natively).
set -eux
export DEBIAN_FRONTEND=noninteractive
echo "Acquire::Retries \"8\";" > /etc/apt/apt.conf.d/80retries
for i in 1 2 3 4 5; do apt-get update && break; sleep 15; done
apt-get install -y --no-install-recommends debootstrap squashfs-tools xorriso mtools \
  grub-pc-bin grub-common ca-certificates
R=/build/rootfs; rm -rf /build; mkdir -p $R /build/iso/live /build/iso/boot/grub
debootstrap --arch=i386 --variant=minbase --components=main,contrib,non-free-firmware \
  "$SUITE" $R "$MIRROR"
cat > $R/etc/apt/sources.list <<SRC
deb $MIRROR $SUITE main contrib non-free non-free-firmware
deb $MIRROR $SUITE-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security $SUITE-security main contrib non-free non-free-firmware
SRC
echo grokbot > $R/etc/hostname
for d in proc sys dev dev/pts; do mount --bind /$d $R/$d; done
trap 'for d in dev/pts dev sys proc; do umount -l $R/$d || true; done' EXIT
fw=""
if [ "$WIFI_FW" = 1 ]; then
  # Intel 2200BG/2915ABG (nw8000) firmware needs its licence accepted.
  echo "firmware-ipw2x00 firmware-ipw2x00/license/accepted boolean true" | chroot $R debconf-set-selections
  fw="firmware-ipw2x00 firmware-iwlwifi firmware-realtek firmware-atheros firmware-misc-nonfree"
fi
echo "Acquire::Retries \"8\";" > $R/etc/apt/apt.conf.d/80retries
for i in 1 2 3 4 5; do chroot $R apt-get update && break; sleep 15; done
chroot $R apt-get install -y --no-install-recommends \
  linux-image-686 live-boot systemd-sysv libpam-systemd udev dbus dbus-user-session kmod procps sudo locales \
  sway swaybg foot xwayland fonts-nanum \
  firefox-esr firefox-esr-l10n-ko \
  fcitx5 fcitx5-hangul fcitx5-frontend-gtk3 fcitx5-frontend-gtk4 fcitx5-config-qt- \
  network-manager iw wpasupplicant pipewire pipewire-pulse wireplumber \
  zram-tools acpi-support-base acpid upower ca-certificates $fw
sed -i 's/^# *ko_KR.UTF-8/ko_KR.UTF-8/; s/^# *en_US.UTF-8/en_US.UTF-8/' $R/etc/locale.gen
chroot $R locale-gen
echo LANG=ko_KR.UTF-8 > $R/etc/default/locale
ln -sf /usr/share/zoneinfo/Asia/Seoul $R/etc/localtime
# overlay
O=/src/editions/i386/rootfs-overlay
cp -a $O/etc/. $R/etc/; cp -a $O/usr/. $R/usr/
# Firefox reads default prefs from this dir (not from all of /etc/firefox-esr)
cp $O/firefox-prefs.js $R/usr/lib/firefox-esr/browser/defaults/preferences/grokbot.js
mkdir -p $R/usr/share/grokbot/design $R/usr/share/grokbot/splash
cp /src/system_files/usr/share/grokbot/design/mascot.js /src/system_files/usr/share/grokbot/design/tokens.css \
   /src/system_files/usr/share/grokbot/design/base.css $R/usr/share/grokbot/design/
cp /src/editions/i386/splash/* $R/usr/share/grokbot/splash/
cp -a $O/home-skel/. $R/etc/skel/
# user (no password; passwordless sudo only for power actions is handled by logind)
chroot $R useradd -m -s /bin/bash -G audio,video,netdev,sudo grokbot
chroot $R passwd -d grokbot
# trim
chroot $R apt-get clean
rm -rf $R/var/lib/apt/lists/* $R/usr/share/doc/* $R/usr/share/man/* $R/var/cache/debconf/*-old
find $R/usr/share/locale -mindepth 1 -maxdepth 1 ! -name ko ! -name en\* ! -name locale.alias -exec rm -rf {} +
for d in dev/pts dev sys proc; do umount -l $R/$d; done; trap - EXIT
du -sh $R | tee /out/rootfs-size.txt
cp $R/boot/vmlinuz-* /build/iso/live/vmlinuz; cp $R/boot/initrd.img-* /build/iso/live/initrd.img
mksquashfs $R /build/iso/live/filesystem.squashfs -comp xz -e boot -noappend
dbg=""
if [ "${DEBUG:-0}" = 1 ]; then
  # test builds only: root shell on the serial port (never ship this)
  dbg="console=tty0 console=ttyS0 systemd.debug_shell=ttyS0"
fi
cat > /build/iso/boot/grub/grub.cfg <<CFG
set timeout=3
menuentry "Grok Bot OS (i386)" {
  linux /live/vmlinuz boot=live components quiet splash $dbg
  initrd /live/initrd.img
}
menuentry "Grok Bot OS (i386, safe graphics)" {
  linux /live/vmlinuz boot=live components nomodeset
  initrd /live/initrd.img
}
CFG
grub-mkrescue -o /out/grokbot-os-i386.iso /build/iso -- -volid GROKBOT_I386
ls -l /out
