#!/usr/bin/env bash
# setup-r2.sh — idempotent bootstrap for the Cloudflare R2 bucket the harness
# uses for per-agent profile persistence.
#
# What it does (in order, each step is a no-op if already done):
#   1. Verify required env vars + tools are present
#   2. Check whether the R2 bucket exists (via Cloudflare API)
#   3. Create the bucket if missing
#   4. Print the env-var lines to paste into `flyctl secrets set` (or
#      copy into a .env file for local dev)
#
# What it does NOT do, because Cloudflare's API surface for these is either
# missing or not advisable to script (you only want to do them once):
#   - Generate the R2 API token. Tokens need the right "edit object"
#     permission and a TTL; do this manually in the dashboard:
#       Cloudflare → R2 → Manage R2 API Tokens → Create API Token
#       Permissions: Object Read & Write
#       Specify bucket: <bucket-name>
#       TTL: 1 year (rotate; set a calendar reminder)
#   - Public bucket / custom domain. The harness needs ONLY private S3
#     API access; don't make this public.
#
# Usage:
#   CF_ACCOUNT_ID=... CF_API_TOKEN=... R2_BUCKET=aki-browser-profiles \
#       bash scripts/setup-r2.sh
#
# CF_API_TOKEN here is a *Cloudflare account* token with "Account R2 Storage
# - Edit" permission. That's separate from the per-bucket R2 API token used
# by the harness at runtime; see step 4's output.

set -euo pipefail

log() { printf '\033[1;34m[setup-r2]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup-r2]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31m[setup-r2]\033[0m %s\n' "$*" >&2; }

# 1. Preconditions ---------------------------------------------------------

missing=()
[ -z "${CF_ACCOUNT_ID:-}" ] && missing+=("CF_ACCOUNT_ID")
[ -z "${CF_API_TOKEN:-}" ]  && missing+=("CF_API_TOKEN")
R2_BUCKET="${R2_BUCKET:-aki-browser-profiles}"

if [ "${#missing[@]}" -gt 0 ]; then
  err "missing required env vars: ${missing[*]}"
  err ""
  err "Get CF_ACCOUNT_ID from the Cloudflare dashboard sidebar (any zone)."
  err "Create CF_API_TOKEN at: My Profile → API Tokens → Create Token →"
  err "  Custom token → permission: Account → Account R2 Storage → Edit"
  exit 2
fi

for cmd in curl jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "required tool not found on PATH: $cmd"
    exit 2
  fi
done

log "account=${CF_ACCOUNT_ID} bucket=${R2_BUCKET}"

# 2. Check bucket ----------------------------------------------------------

api() {
  # $1 = method, $2 = path (relative to /accounts/$CF_ACCOUNT_ID), rest = curl extras
  local method="$1" path="$2"
  shift 2
  curl -sS -X "$method" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    "$@" \
    "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}${path}"
}

log "checking whether bucket ${R2_BUCKET} exists"
existing=$(api GET "/r2/buckets" \
  | jq -r --arg b "$R2_BUCKET" '.result.buckets[]? | select(.name == $b) | .name')

if [ "$existing" = "$R2_BUCKET" ]; then
  log "bucket ${R2_BUCKET} already exists — no action"
else
  # 3. Create bucket -------------------------------------------------------
  log "creating bucket ${R2_BUCKET}"
  resp=$(api POST "/r2/buckets" \
    --data "$(jq -nc --arg b "$R2_BUCKET" '{name: $b}')")
  ok=$(echo "$resp" | jq -r '.success // false')
  if [ "$ok" != "true" ]; then
    err "bucket creation failed:"
    echo "$resp" | jq . >&2
    exit 1
  fi
  log "bucket ${R2_BUCKET} created"
fi

# 4. Manual step + env-var template ---------------------------------------

R2_ENDPOINT="https://${CF_ACCOUNT_ID}.r2.cloudflarestorage.com"

cat <<MSG

✔ R2 bucket is ready.

Next (manual, one-time): create the R2 API token the harness will use at
runtime. Cloudflare's API doesn't expose token creation, so do it in the UI:

  1. Cloudflare dashboard → R2 → Manage R2 API Tokens
  2. Create API Token
       Token name:           aki-browser-harness
       Permissions:          Object Read & Write
       Specify bucket(s):    ${R2_BUCKET}
       TTL:                  365 days (set a calendar reminder to rotate)
  3. Save the Access Key ID and Secret Access Key — they're shown once.

Then set the harness secrets (Fly):

  flyctl secrets set --app aki-browser-harness \\
    BROWSER_HARNESS_R2_ENDPOINT='${R2_ENDPOINT}' \\
    BROWSER_HARNESS_R2_BUCKET='${R2_BUCKET}' \\
    BROWSER_HARNESS_R2_ACCESS_KEY='<from-step-3>' \\
    BROWSER_HARNESS_R2_SECRET_KEY='<from-step-3>' \\
    BROWSER_HARNESS_R2_REGION='auto'

Or for local dev, append to services/browser-harness/.env:

  BROWSER_HARNESS_R2_ENDPOINT=${R2_ENDPOINT}
  BROWSER_HARNESS_R2_BUCKET=${R2_BUCKET}
  BROWSER_HARNESS_R2_ACCESS_KEY=<from-step-3>
  BROWSER_HARNESS_R2_SECRET_KEY=<from-step-3>
  BROWSER_HARNESS_R2_REGION=auto

MSG
