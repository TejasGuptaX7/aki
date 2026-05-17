# v2 proxy image. Pure Python, no Chromium — the browsers run on
# Steel/Browserbase. Image is ~120 MB vs ~1.2 GB for the v1 image.
#
# Build from the repo root or from services/browser-harness/proxy/.
# Both work because the build context only needs files in this dir.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7901 \
    HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/aki

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY __init__.py server.py pool.py cdp.py router.py profile_store.py \
     steel_adapter.py browserbase_adapter.py ./

RUN groupadd --system --gid 1000 aki \
 && useradd  --system --uid 1000 --gid aki --home-dir /opt/aki --shell /usr/sbin/nologin aki \
 && chown -R aki:aki /opt/aki

USER aki

EXPOSE 7901

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
