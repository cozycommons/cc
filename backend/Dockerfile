# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
ARG INSTALL_PLAYWRIGHT=true

# Keep apt archives so BuildKit --mount=type=cache mounts can reuse them across builds.
# (Debian/Ubuntu base images normally delete apt caches via docker-clean.)
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# System packages needed at runtime (ffmpeg, poppler-utils for pdftoppm).
# apt caches are mounted so repeat builds don't re-download .deb files.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg poppler-utils curl ca-certificates xz-utils

# Install tectonic (single static binary, auto-fetches TeX packages on first
# compile). We pin to a specific release for reproducibility.
ARG TECTONIC_VERSION=0.15.0
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64) tarball="tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" ;; \
        aarch64) tarball="tectonic-${TECTONIC_VERSION}-aarch64-unknown-linux-musl.tar.gz" ;; \
        *) echo "unsupported arch $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/${tarball}"; \
    curl -fsSL "$url" -o /tmp/tectonic.tar.gz; \
    tar -xzf /tmp/tectonic.tar.gz -C /tmp; \
    install -m 0755 /tmp/tectonic /usr/local/bin/tectonic; \
    rm -rf /tmp/tectonic /tmp/tectonic.tar.gz; \
    tectonic --version

# Install Typst CLI (used by resume-builder to compile .typ → PDF).
ARG TYPST_VERSION=0.13.1
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64)  triple="x86_64-unknown-linux-musl" ;; \
        aarch64) triple="aarch64-unknown-linux-musl" ;; \
        *) echo "unsupported arch $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${triple}.tar.xz"; \
    curl -fsSL "$url" -o /tmp/typst.tar.xz; \
    tar -xJf /tmp/typst.tar.xz -C /tmp; \
    install -m 0755 /tmp/typst-${triple}/typst /usr/local/bin/typst; \
    rm -rf /tmp/typst* ; \
    typst --version

# Install Python deps first, before copying source, so unrelated code changes
# don't bust this (expensive) layer. pip's wheel cache is mounted (not baked
# into the image), keeping the image size the same while making rebuilds fast.
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Install Playwright browsers + their apt deps. Chromium itself is installed
# under PLAYWRIGHT_BROWSERS_PATH (baked into the image, not into the cache
# mount), while apt package downloads reuse the cache mount above.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/root/.cache/pip \
    python -m playwright install --with-deps chromium

# Application source comes last: changes here invalidate only this layer.
COPY . /app/

RUN mkdir -p /app/.secrets

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
