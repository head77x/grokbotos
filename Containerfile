# Allow build scripts to be referenced without being copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY grokbot-app /grokbot-app

# Base Image
# quay.io/fedora/fedora-bootc: minimal Fedora Atomic (bootc) image with no
# desktop environment, published multi-arch (x86_64 + aarch64). Switched
# from ghcr.io/ublue-os/base-main (2026-07-09): base-main is amd64-only,
# which blocks building/testing this image on arm64 (e.g. Apple Silicon
# Macs via UTM). See docs/DECISIONS.md for the full history.
# Pinned by digest (security review #8): the multi-arch index that
# quay.io/fedora/fedora-bootc:latest pointed to on 2026-10-24. To update,
# resolve the tag again and replace the digest in one reviewed commit:
#   skopeo inspect --raw docker://quay.io/fedora/fedora-bootc:latest | sha256sum
FROM quay.io/fedora/fedora-bootc:latest@sha256:1a17d180491130098b6881300ff3bbe74d37cc40968af4fbf3d5945a9779bb73

# Grok Bot Linux app. Empty SOURCE selects the pinned RPM for TARGETARCH
# (amd64 and arm64). GROKBOT_DISABLE_BUNDLED_APP=1 keeps the placeholder.
# See docs/GROKBOT_APP.md and build_files/install-grokbot-app.sh.
ARG GROKBOT_APP_SOURCE=
ARG GROKBOT_APP_SHA256=
ARG GROKBOT_APP_KIND=auto
ARG GROKBOT_APP_EXEC=
ARG GROKBOT_FLATPAK_ID=
ARG GROKBOT_WEB_URL=
ARG GROKBOT_TARGET_ARCH
ARG GROKBOT_DISABLE_BUNDLED_APP
# Set by podman/buildah from the build platform. amd64 or arm64.
ARG TARGETARCH

### MODIFICATIONS
## make modifications desired in your image and install packages by modifying the build.sh script
## the following RUN directive does all the things required to run "build.sh" as recommended.

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    /ctx/build.sh

### LINTING
## Verify final image and contents are correct.
RUN bootc container lint
