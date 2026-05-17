#!/usr/bin/env bash
# smoke-test-v2.sh — end-to-end verification of the v2 proxy layer.
#
# Two runs, each going through the SAME MCP endpoint (the proxy decides
# which vendor to use):
#
#   Run A  — Steel.dev backend
#            Forces platform="default" → Steel via the default routing
#            rule. Navigates example.com and asserts the title.
#
#   Run B  — Browserbase backend
#            Forces platform="linkedin" via X-Aki-Platform header → routes
#            to Browserbase (per the default routing table in
#            PROTOCOL_v2.md). Hits a public URL still (we don't want to
#            actually scrape LinkedIn in a smoke test), then sets a cookie,
#            releases the session, opens a fresh one, and verifies the
#            cookie persisted via the Browserbase Context.
#
# Idempotent. Each run uses a fresh org/agent UUID pair so concurrent
# invocations don't fight. Trap-releases sessions on exit so a failed
# run doesn't leak billable vendor time.
#
# Usage (run from the founder's laptop):
#
#   export STEEL_API_KEY=...                  # from https://app.steel.dev
#   export BROWSERBASE_API_KEY=...            # from https://browserbase.com/settings
#   export BROWSERBASE_PROJECT_ID=...         # also from Browserbase settings
#   export BROWSER_HARNESS_API_KEY=...        # the proxy's shared secret
#   export BROWSER_HARNESS_URL=http://localhost:7901   # or the deployed Fly URL
#
#   bash services/browser-harness/scripts/smoke-test-v2.sh

set -euo pipefail

URL="${BROWSER_HARNESS_URL:-http://localhost:7901}"
KEY="${BROWSER_HARNESS_API_KEY:-}"

if [ -z "$KEY" ]; then
  echo "BROWSER_HARNESS_API_KEY must be set" >&2
  exit 2
fi
for c in curl jq python3; do
  command -v "$c" >/dev/null 2>&1 || { echo "missing tool: $c" >&2; exit 2; }
done

# Vendor key sanity check — not strictly required (the proxy will return
# vendor_quota_exhausted / vendor_unavailable when keys are missing),
# but bailing here is friendlier than scrolling past one failed run.
if [ -z "${STEEL_API_KEY:-}" ]; then
  echo "WARNING: STEEL_API_KEY unset — Steel run will return vendor_unavailable" >&2
fi
if [ -z "${BROWSERBASE_API_KEY:-}" ] || [ -z "${BROWSERBASE_PROJECT_ID:-}" ]; then
  echo "WARNING: BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID unset — Browserbase run will return vendor_unavailable" >&2
fi

step() { printf '\033[1;34m[%s]\033[0m %s\n' "$1" "$2"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m  ✗\033[0m %s\n' "$*"; exit 1; }

# Each "run" gets its own org/agent so the Browserbase test's manifest doesn't
# carry into the Steel test (they share a backing R2 if configured but the
# (org,agent,platform) key keeps them isolated). The shared trap cleans both.
ORG_STEEL=$(python3 -c 'import uuid; print(uuid.uuid4())')
AGENT_STEEL=$(python3 -c 'import uuid; print(uuid.uuid4())')
ORG_BB=$(python3 -c 'import uuid; print(uuid.uuid4())')
AGENT_BB=$(python3 -c 'import uuid; print(uuid.uuid4())')

cleanup() {
  set +e
  for pair in "$ORG_STEEL $AGENT_STEEL" "$ORG_BB $AGENT_BB"; do
    set -- $pair
    curl -sS -X POST \
      -H "Authorization: Bearer ${KEY}" \
      -H "X-Aki-Org-Id: $1" -H "X-Aki-Agent-Id: $2" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"release_session","arguments":{"persist":true}}}' \
      "${URL}/mcp" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

# ----- helper ------------------------------------------------------------

mcp_call() {
  # $1 org $2 agent $3 tool $4 args(json) [$5 platform-header]
  local org="$1" agent="$2" tool="$3" args="$4" plat="${5:-}"
  local body
  body=$(jq -nc --arg n "$tool" --argjson a "$args" \
    '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:$n,arguments:$a}}')
  local extra=()
  if [ -n "$plat" ]; then extra+=(-H "X-Aki-Platform: $plat"); fi
  curl -sS --fail-with-body -X POST \
    -H "Authorization: Bearer ${KEY}" \
    -H "X-Aki-Org-Id: $org" -H "X-Aki-Agent-Id: $agent" \
    -H "Content-Type: application/json" \
    "${extra[@]}" \
    -d "$body" \
    "${URL}/mcp"
}

assert_ok() {
  # $1 raw mcp response — exits if isError true. Echoes parsed inner text.
  local resp="$1"
  local is_err
  is_err=$(echo "$resp" | jq -r '.result.isError // .error // false')
  if [ "$is_err" = "true" ] || [ "$is_err" != "false" ] && [ "$is_err" != "null" ]; then
    echo "  raw response: $resp" >&2
    fail "tool returned error: $is_err"
  fi
  echo "$resp" | jq -r '.result.content[0].text // empty'
}

# ----- run A: Steel ------------------------------------------------------

step "A/1" "healthz reachable"
curl -fsS "${URL}/healthz" >/dev/null
ok "healthz 200"

step "A/2" "navigate example.com via Steel (platform=default)"
raw=$(mcp_call "$ORG_STEEL" "$AGENT_STEEL" navigate \
        '{"url":"https://example.com","wait_for_load":true,"timeout":20}')
text=$(assert_ok "$raw")
meta_platform=$(echo "$raw" | jq -r '.result._meta.platform // ""')
title=$(echo "$text" | jq -r '.title // ""')
if ! echo "$title" | grep -qi example; then
  fail "title doesn't look like example.com: '$title'  (raw: $raw)"
fi
if [ "$meta_platform" != "default" ]; then
  fail "expected platform=default, got '$meta_platform'"
fi
ok "Steel navigate succeeded — title='$title' platform=$meta_platform"

step "A/3" "extract_text confirms 'Example Domain'"
raw=$(mcp_call "$ORG_STEEL" "$AGENT_STEEL" extract_text '{"selector":"h1","max_chars":200}')
text=$(assert_ok "$raw" | jq -r '.text')
if ! echo "$text" | grep -qi "example domain"; then
  fail "extract_text didn't find 'Example Domain': '$text'"
fi
ok "Steel extract_text returned: '$text'"

step "A/4" "list_platforms shows one Steel session bound"
raw=$(mcp_call "$ORG_STEEL" "$AGENT_STEEL" list_platforms '{}')
parsed=$(assert_ok "$raw")
backend=$(echo "$parsed" | jq -r '.platforms[0].backend // ""')
if [ "$backend" != "steel" ]; then
  fail "expected backend=steel, got '$backend'  (parsed: $parsed)"
fi
ok "list_platforms confirms backend=steel"

# ----- run B: Browserbase ------------------------------------------------

step "B/1" "navigate example.com via Browserbase (X-Aki-Platform: linkedin → BB by default route)"
raw=$(mcp_call "$ORG_BB" "$AGENT_BB" navigate \
        '{"url":"https://example.com","wait_for_load":true,"timeout":20}' \
        "linkedin")
text=$(assert_ok "$raw")
meta_platform=$(echo "$raw" | jq -r '.result._meta.platform // ""')
if [ "$meta_platform" != "linkedin" ]; then
  fail "expected platform=linkedin, got '$meta_platform'"
fi
ok "Browserbase navigate succeeded under platform=$meta_platform"

step "B/2" "set a cookie via js"
raw=$(mcp_call "$ORG_BB" "$AGENT_BB" js \
        '{"expression":"document.cookie=\"aki_v2=hello; path=/; max-age=3600\"; document.cookie"}' \
        "linkedin")
cookie=$(assert_ok "$raw" | jq -r '.value // ""')
if ! echo "$cookie" | grep -q "aki_v2=hello"; then
  fail "didn't set/echo aki_v2 cookie: '$cookie'"
fi
ok "cookie set: '$cookie'"

step "B/3" "release_platform (persist=true) → Browserbase Context retains state"
raw=$(mcp_call "$ORG_BB" "$AGENT_BB" release_platform \
        '{"platform":"linkedin","persist":true}' \
        "linkedin")
released=$(assert_ok "$raw" | jq -r '.released // false')
if [ "$released" != "true" ]; then
  fail "release_platform returned released=$released"
fi
ok "platform released, manifest retained"

step "B/4" "re-navigate; new session attaches to same Context → cookie should persist"
raw=$(mcp_call "$ORG_BB" "$AGENT_BB" navigate \
        '{"url":"https://example.com","wait_for_load":true,"timeout":20}' \
        "linkedin")
assert_ok "$raw" >/dev/null

raw=$(mcp_call "$ORG_BB" "$AGENT_BB" js '{"expression":"document.cookie"}' "linkedin")
cookie=$(assert_ok "$raw" | jq -r '.value // ""')
if ! echo "$cookie" | grep -q "aki_v2=hello"; then
  fail "cookie did NOT persist across release: got '$cookie'"
fi
ok "cookie persisted across release — Browserbase Context is doing its job"

printf '\n\033[1;32mboth runs passed\033[0m  (steel run org=%s agent=%s; bb run org=%s agent=%s)\n' \
       "$ORG_STEEL" "$AGENT_STEEL" "$ORG_BB" "$AGENT_BB"
