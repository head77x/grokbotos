#!/bin/sh
# Build the Grok Bot OS i386 live ISO in a throwaway Debian container.
# usage: editions/i386/build.sh [outdir]   (needs podman or docker; root for --privileged)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
out=${1:-$here/out}
mkdir -p "$out"
eng=${ENGINE:-podman}
exec $eng run --rm --privileged --network=host \
  -v "$repo:/src:ro" -v "$out:/out" \
  -e SUITE="${SUITE:-bookworm}" -e MIRROR="${MIRROR:-http://deb.debian.org/debian}" \
  -e WIFI_FW="${WIFI_FW:-1}" -e DEBUG="${DEBUG:-0}" \
  docker.io/library/debian:bookworm sh /src/editions/i386/build-in-container.sh
