#!/usr/bin/env bash
# Boot order for the Fly api Machine:
#   1. start dockerd in the background, write a pid file
#   2. wait for /var/run/docker.sock to be ready
#   3. pre-pull the Hermes image so the first chat doesn't pay the cold
#      pull on the request path (best-effort; missing creds = skip)
#   4. exec uvicorn as PID 1's child
#
# This script is intentionally simple. supervisord would also work and is
# installed in the image, but a 30-line bash script is easier to debug at
# 2am when dockerd is wedged.
set -euo pipefail

DOCKERD_LOG=${DOCKERD_LOG:-/var/log/dockerd.log}
DOCKERD_SOCK=${DOCKERD_SOCK:-/var/run/docker.sock}
HERMES_IMAGE=${HERMES_IMAGE:-ghcr.io/akiapp/aki-hermes:0.13.0}
HERMES_PULL_TIMEOUT_S=${HERMES_PULL_TIMEOUT_S:-90}

log() { printf '[aki-entrypoint] %s\n' "$*"; }

# 1. dockerd in the background ------------------------------------------------
log "starting dockerd (logs -> ${DOCKERD_LOG})"
mkdir -p "$(dirname "${DOCKERD_LOG}")"
# --iptables=true is the default but we set it explicitly so a future
# debug session knows the bridge networking is on purpose.
# --storage-driver=overlay2 needs /var/lib/docker on an overlayfs-capable
# filesystem; Fly volumes (ext4) qualify.
dockerd \
    --host="unix://${DOCKERD_SOCK}" \
    --iptables=true \
    --storage-driver=overlay2 \
    >"${DOCKERD_LOG}" 2>&1 &
DOCKERD_PID=$!
echo "${DOCKERD_PID}" > /run/dockerd.pid

# 2. wait for the socket ------------------------------------------------------
for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
        log "dockerd ready after ${i}s"
        break
    fi
    if ! kill -0 "${DOCKERD_PID}" 2>/dev/null; then
        log "dockerd exited during startup — tail of ${DOCKERD_LOG}:"
        tail -n 50 "${DOCKERD_LOG}" || true
        exit 1
    fi
    sleep 1
done
if ! docker info >/dev/null 2>&1; then
    log "dockerd never became ready — tail of ${DOCKERD_LOG}:"
    tail -n 50 "${DOCKERD_LOG}" || true
    exit 1
fi

# 3. warm pull of the Hermes image -------------------------------------------
# Skipped if GHCR creds aren't present — the first chat will pay the cold
# pull instead and we'll see it in the dashboard, no crash.
if [[ -n "${GHCR_PULL_TOKEN:-}" && -n "${GHCR_PULL_USERNAME:-}" ]]; then
    log "logging in to GHCR"
    echo "${GHCR_PULL_TOKEN}" \
        | docker login ghcr.io -u "${GHCR_PULL_USERNAME}" --password-stdin
fi
log "pre-pulling ${HERMES_IMAGE} (timeout ${HERMES_PULL_TIMEOUT_S}s)"
if ! timeout "${HERMES_PULL_TIMEOUT_S}" docker pull "${HERMES_IMAGE}"; then
    log "Hermes pre-pull failed — continuing; cold start will retry on first chat"
fi

# Graceful shutdown: forward SIGTERM to both processes.
shutdown() {
    log "received shutdown signal — stopping uvicorn then dockerd"
    if [[ -n "${UVICORN_PID:-}" ]]; then
        kill -TERM "${UVICORN_PID}" 2>/dev/null || true
        wait "${UVICORN_PID}" 2>/dev/null || true
    fi
    kill -TERM "${DOCKERD_PID}" 2>/dev/null || true
    wait "${DOCKERD_PID}" 2>/dev/null || true
    exit 0
}
trap shutdown TERM INT

# 4. uvicorn in the foreground -----------------------------------------------
log "starting uvicorn"
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
UVICORN_PID=$!

# Wait on either child; whichever exits first takes the Machine down so
# Fly restarts us with both clean.
wait -n "${UVICORN_PID}" "${DOCKERD_PID}"
EXIT=$?
log "child process exited (${EXIT}) — triggering shutdown"
shutdown
