# Aki browser-harness service.
#
# One image, one process. The process owns a pool of per-(org, agent)
# Chromium subprocesses and per-agent browser-harness daemons; see pool.py.
#
# Resource caps:
#   - The image itself does NOT set cgroup limits — that's the runtime's job
#     (docker run --memory --cpus, k8s requests/limits). What we do here is
#     give Chromium the right flags so it stays inside whatever budget the
#     runtime hands us (--js-flags=--max-old-space-size, --disable-dev-shm).
#   - Run as a non-root user. Chromium's own sandbox is disabled
#     (--no-sandbox in pool.py) since the container IS the sandbox.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BROWSER_HARNESS_CHROMIUM=/usr/bin/chromium \
    BROWSER_HARNESS_PROFILE_ROOT=/var/lib/aki/browser-profiles \
    BROWSER_HARNESS_SKILLS_ROOT=/var/lib/aki/browser-harness/skills \
    PORT=7900 \
    HOST=0.0.0.0

# System deps:
#   - chromium + fonts so headless renders text correctly
#   - libnss3 / libatk-bridge etc. — Chromium's runtime libs (slim image
#     skips most of these). The explicit list is the union of `ldd
#     /usr/bin/chromium` on a fresh debian-slim install.
#   - tini reaps zombie subprocesses (we spawn Chromium + bh daemons)
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-sandbox \
        ca-certificates \
        curl \
        tini \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-noto-cjk \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/aki

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY server.py pool.py storage.py ./
COPY skills /opt/aki/skills.bootstrap

# Profile/skills volumes — empty on first boot, mounted from the host in
# production so per-agent state survives container restarts.
RUN mkdir -p /var/lib/aki/browser-profiles /var/lib/aki/browser-harness/skills \
    && groupadd --system --gid 1000 aki \
    && useradd  --system --uid 1000 --gid aki --home-dir /opt/aki --shell /usr/sbin/nologin aki \
    && chown -R aki:aki /opt/aki /var/lib/aki

USER aki

EXPOSE 7900

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
