# Pin the OCI image index, not only the mutable 3.13-bookworm tag.
# Update the FROM digest and PUBLISHER_BASE_IMAGE_REF together after review.
FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d

# These values are recorded in the runtime lock and checked on every container start.
ENV PUBLISHER_BASE_IMAGE_REF="mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:ac334d90ca71f23b58820c90a440b400d175b77d642d312cf67ff0cc9cb2056d"
ENV PUBLISHER_BUILD_PLATFORM="linux/amd64"

# Immutable Debian archive state used to validate the APT metadata source.
ARG DEBIAN_SNAPSHOT=20261107T000000Z
ENV DEBIAN_SNAPSHOT=${DEBIAN_SNAPSHOT}

COPY .devcontainer/debian-snapshot.sources.in /tmp/debian-snapshot.sources.in
COPY .devcontainer/install-apt-snapshot.sh /usr/local/sbin/install-apt-snapshot.sh
COPY .devcontainer/verify-apt-state.sh /usr/local/sbin/verify-apt-state.sh

# Debian Bookworm's digest-pinned base image already contains Git. The Debian
# `git` package ships /usr/lib/git-core/git-subtree; there is no separate
# `git-subtree` package. The installer verifies the package owner/version,
# links the existing helper into `git --exec-path`, and records a v3 lock.
RUN set -eux; \
    rm -f /etc/apt/sources.list; \
    if [ -d /etc/apt/sources.list.d ]; then \
        find /etc/apt/sources.list.d -maxdepth 1 -type f \
            \( -name '*.list' -o -name '*.sources' \) -delete; \
    fi; \
    sed "s/@DEBIAN_SNAPSHOT@/${DEBIAN_SNAPSHOT}/g" \
        /tmp/debian-snapshot.sources.in \
        > /etc/apt/sources.list.d/debian-snapshot.sources; \
    bash /usr/local/sbin/install-apt-snapshot.sh; \
    bash /usr/local/sbin/verify-apt-state.sh; \
    rm -f /tmp/debian-snapshot.sources.in; \
    rm -rf /var/lib/apt/lists/*
