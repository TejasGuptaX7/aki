#!/usr/bin/env bash
# infra/fly-deploy.sh — one-stop deploy for the Aki Fly footprint.
#
# What this does:
#   - apps        — create aki-api and aki-browser-harness if absent
#   - volumes     — create the api data volume in iad
#   - redis       — create Upstash for Redis on Fly and attach to aki-api
#   - deploy      — build + deploy both apps with `flyctl deploy --remote-only`
#   - privileged  — flip the api Machine to privileged=true so dockerd
#                   inside the Machine can actually start (see DEPLOY.md
#                   "Privileged mode")
#   - check       — confirm /health and /healthz return 200
#
# What this does NOT do:
#   - set any secrets (do that once, by hand, per infra/secrets-bootstrap.md;
#     this script aborts early if required secrets are missing)
#   - run alembic migrations (CI workflow handles that; for first deploy
#     run `alembic upgrade head` against $DATABASE_URL_SYNC by hand)
#   - touch DNS or Cloudflare (the cert + CNAME steps are manual one-time
#     ops documented in DEPLOY.md §"Domains")
#
# Idempotent: re-running skips anything already in the desired state.
# Usage:
#   infra/fly-deploy.sh [stage]
#     stage = all (default) | apps | volumes | redis | deploy | privileged | check
#
# Env:
#   FLY_ORG               required for `fly apps create` on first run
#   API_APP               default aki-api
#   PROXY_APP             default aki-browser-harness
#   REGION                default iad
#   API_VOLUME_NAME       default aki_api_data
#   API_VOLUME_SIZE_GB    default 50
#   REDIS_NAME            default aki-redis
#   REDIS_PLAN            default pay-as-you-go    (see `fly redis plans`)
#   SKIP_PRIVILEGED       set to 1 if your Fly org cannot use privileged
#                         Machines yet — the api Machine will boot but
#                         dockerd will fail; see DEPLOY.md for the
#                         Hetzner fallback path.

set -euo pipefail

API_APP=${API_APP:-aki-api}
PROXY_APP=${PROXY_APP:-aki-browser-harness}
REGION=${REGION:-iad}
API_VOLUME_NAME=${API_VOLUME_NAME:-aki_api_data}
API_VOLUME_SIZE_GB=${API_VOLUME_SIZE_GB:-50}
REDIS_NAME=${REDIS_NAME:-aki-redis}
REDIS_PLAN=${REDIS_PLAN:-pay-as-you-go}

STAGE=${1:-all}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[deploy]\033[0m %s\n' "$*" >&2; exit 1; }

require_bin() {
    command -v "$1" >/dev/null 2>&1 || fail "missing required binary: $1"
}

require_bin flyctl
require_bin curl
require_bin jq

# ---------------------------------------------------------------------------
# Stage: apps -- create the two Fly apps if they don't already exist.
# ---------------------------------------------------------------------------
ensure_app() {
    local name=$1
    if flyctl apps list --json | jq -e --arg n "$name" '.[] | select(.Name == $n)' >/dev/null; then
        log "app ${name} exists"
    else
        [[ -n "${FLY_ORG:-}" ]] || fail "FLY_ORG must be set to create ${name}"
        log "creating app ${name} in org ${FLY_ORG}"
        flyctl apps create "${name}" --org "${FLY_ORG}"
    fi
}

stage_apps() {
    ensure_app "${API_APP}"
    ensure_app "${PROXY_APP}"

    # api needs a v4 IP for Cloudflare to CNAME to (Cloudflare proxy can't
    # follow a v6-only origin in many setups). proxy can stay v6-only —
    # it sits behind the api via .internal DNS.
    if ! flyctl ips list --app "${API_APP}" --json | jq -e '.[] | select(.Type=="v4")' >/dev/null; then
        log "allocating shared v4 IP for ${API_APP}"
        flyctl ips allocate-v4 --shared --app "${API_APP}"
    fi
}

# ---------------------------------------------------------------------------
# Stage: volumes -- one persistent volume for the api Machine.
# ---------------------------------------------------------------------------
stage_volumes() {
    if flyctl volumes list --app "${API_APP}" --json \
         | jq -e --arg n "${API_VOLUME_NAME}" --arg r "${REGION}" \
              '.[] | select(.Name == $n and .Region == $r)' >/dev/null; then
        log "volume ${API_VOLUME_NAME} (${REGION}) exists on ${API_APP}"
    else
        log "creating volume ${API_VOLUME_NAME} (${API_VOLUME_SIZE_GB} GB, ${REGION}) on ${API_APP}"
        flyctl volumes create "${API_VOLUME_NAME}" \
            --app "${API_APP}" \
            --region "${REGION}" \
            --size "${API_VOLUME_SIZE_GB}" \
            --yes
    fi
}

# ---------------------------------------------------------------------------
# Stage: redis -- Upstash on Fly, attached to the api so REDIS_URL is set
# as a secret automatically.
# ---------------------------------------------------------------------------
stage_redis() {
    # `fly redis list` prints names in column 1; greppable on exact match.
    if flyctl redis list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "${REDIS_NAME}"; then
        log "redis ${REDIS_NAME} exists"
    else
        log "creating redis ${REDIS_NAME} (${REDIS_PLAN}) in ${REGION}"
        flyctl redis create \
            --name "${REDIS_NAME}" \
            --region "${REGION}" \
            --plan "${REDIS_PLAN}" \
            --no-replicas
    fi

    # Attach is also idempotent on flyctl's side: if REDIS_URL is already
    # set on the app, attach prints an error we tolerate.
    log "attaching ${REDIS_NAME} to ${API_APP} (sets REDIS_URL secret)"
    flyctl redis attach "${REDIS_NAME}" --app "${API_APP}" 2>&1 \
        | grep -v "already attached" || true
}

# ---------------------------------------------------------------------------
# Stage: deploy -- build + ship both images.
# ---------------------------------------------------------------------------
require_secrets() {
    local app=$1; shift
    local missing=()
    local have
    have=$(flyctl secrets list --app "${app}" --json | jq -r '.[].Name')
    for s in "$@"; do
        grep -Fxq "$s" <<<"$have" || missing+=("$s")
    done
    if (( ${#missing[@]} > 0 )); then
        fail "missing secrets on ${app}: ${missing[*]} — see infra/secrets-bootstrap.md"
    fi
}

stage_deploy() {
    require_secrets "${API_APP}" \
        DATABASE_URL DATABASE_URL_SYNC \
        CLERK_SECRET_KEY CLERK_WEBHOOK_SECRET CLERK_JWKS_URL CLERK_JWT_ISSUER \
        OPENAI_API_KEY \
        BROWSER_HARNESS_API_KEY BROWSER_HARNESS_URL
    # REDIS_URL is set by `fly redis attach`; checked separately so the
    # error message points to the right fix.
    flyctl secrets list --app "${API_APP}" --json \
        | jq -e '.[] | select(.Name=="REDIS_URL")' >/dev/null \
        || fail "REDIS_URL not set on ${API_APP} — run \`$0 redis\` first"

    require_secrets "${PROXY_APP}" \
        BROWSER_HARNESS_API_KEY \
        BROWSER_HARNESS_R2_ENDPOINT BROWSER_HARNESS_R2_ACCESS_KEY \
        BROWSER_HARNESS_R2_SECRET_KEY \
        STEEL_API_KEY

    log "deploying ${API_APP}"
    flyctl deploy \
        --app "${API_APP}" \
        --config infra/fly/api.toml \
        --remote-only

    log "deploying ${PROXY_APP}"
    # cd into the proxy dir so the Dockerfile's relative COPYs work; the
    # toml lives in infra/fly/proxy.toml but the build context is the
    # proxy source tree.
    ( cd services/browser-harness/proxy \
        && flyctl deploy \
            --app "${PROXY_APP}" \
            --config "${REPO_ROOT}/infra/fly/proxy.toml" \
            --dockerfile Dockerfile \
            --remote-only )
}

# ---------------------------------------------------------------------------
# Stage: privileged -- flip the api Machine to privileged=true so the
# in-Machine dockerd has the capabilities it needs (CAP_SYS_ADMIN,
# CAP_NET_ADMIN, etc.). fly.toml has no field for this today; we patch
# the Machine config through the Fly Machines REST API.
#
# This requires the Fly org to have privileged Machines enabled. If your
# org doesn't, the PATCH returns 403 — set SKIP_PRIVILEGED=1 to no-op
# and use the Hetzner fallback host (see DEPLOY.md).
# ---------------------------------------------------------------------------
stage_privileged() {
    if [[ "${SKIP_PRIVILEGED:-0}" == "1" ]]; then
        warn "SKIP_PRIVILEGED=1 — skipping privileged flip; api dockerd will not start"
        return 0
    fi

    require_bin flyctl
    local token
    token=$(flyctl auth token)

    local machines
    machines=$(curl -fsSL \
        -H "Authorization: Bearer ${token}" \
        "https://api.machines.dev/v1/apps/${API_APP}/machines")

    local count
    count=$(jq 'length' <<<"${machines}")
    if (( count == 0 )); then
        fail "no machines on ${API_APP} — run \`$0 deploy\` first"
    fi
    if (( count > 1 )); then
        warn "${API_APP} has ${count} machines; ADR-0002 expects a single Machine"
    fi

    while read -r mid; do
        log "patching machine ${mid} → privileged=true"
        local cfg
        cfg=$(jq -r --arg id "${mid}" '.[] | select(.id == $id) | .config' <<<"${machines}")
        # Merge privileged=true into guest, leave everything else untouched.
        local new_cfg
        new_cfg=$(jq '.guest.privileged = true' <<<"${cfg}")
        curl -fsSL -X POST \
            -H "Authorization: Bearer ${token}" \
            -H "Content-Type: application/json" \
            "https://api.machines.dev/v1/apps/${API_APP}/machines/${mid}" \
            --data "$(jq -n --argjson c "${new_cfg}" '{config: $c}')" \
            >/dev/null
    done < <(jq -r '.[].id' <<<"${machines}")

    log "privileged flag set; restarting api machines"
    flyctl machines restart --app "${API_APP}" --select --yes 2>/dev/null \
        || flyctl machine restart --app "${API_APP}"
}

# ---------------------------------------------------------------------------
# Stage: check -- smoke the public + internal endpoints.
# ---------------------------------------------------------------------------
stage_check() {
    local api_url="https://${API_APP}.fly.dev/health"
    local proxy_url="https://${PROXY_APP}.fly.dev/healthz"
    log "GET ${api_url}"
    curl -fsSL --max-time 30 "${api_url}"; echo
    log "GET ${proxy_url}"
    curl -fsSL --max-time 30 "${proxy_url}"; echo
    log "deploy looks healthy"
}

case "${STAGE}" in
    apps)       stage_apps ;;
    volumes)    stage_volumes ;;
    redis)      stage_redis ;;
    deploy)     stage_deploy ;;
    privileged) stage_privileged ;;
    check)      stage_check ;;
    all)
        stage_apps
        stage_volumes
        stage_redis
        stage_deploy
        stage_privileged
        stage_check
        ;;
    *)
        fail "unknown stage: ${STAGE} (expected: apps|volumes|redis|deploy|privileged|check|all)"
        ;;
esac
