#!/usr/bin/env bash
# smoke-test-prod.sh — verify a deployed browser-harness is healthy and
# end-to-end functional. Used by:
#   - the GitHub Actions deploy workflow as its post-deploy gate
#   - operators after a manual `flyctl deploy`
#
# Idempotent. Safe to re-run. Uses a single throwaway (org, agent) UUID
# pair per run so concurrent invocations don't fight over the same
# Chromium session.
#
# Usage:
#   BROWSER_HARNESS_URL=https://aki-browser-harness.fly.dev \
#   BROWSER_HARNESS_API_KEY=<prod-secret> \
#       bash scripts/smoke-test-prod.sh
#
# Exit codes:
#   0  — all checks passed
#   1  — a check failed (look at the printed step)
#   2  — preconditions not met (missing env / tools)

set -euo pipefail

URL="${BROWSER_HARNESS_URL:-https://aki-browser-harness.fly.dev}"
KEY="${BROWSER_HARNESS_API_KEY:-}"

if [ -z "$KEY" ]; then
  echo "BROWSER_HARNESS_API_KEY env var is required (the prod shared secret)" >&2
  exit 2
fi
for cmd in curl jq python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "required tool not found: $cmd" >&2
    exit 2
  fi
done

# Fresh org/agent per run — keeps profile isolation across concurrent runs.
ORG=$(python3 -c 'import uuid; print(uuid.uuid4())')
AGENT=$(python3 -c 'import uuid; print(uuid.uuid4())')
RUN_ID="smoke-$(date +%s)-$$"

cleanup() {
  # Always try to release the session, even on failure — leaves no orphan
  # Chromium burning the per-second bill.
  set +e
  mcp release_session '{}' >/dev/null 2>&1
}
trap cleanup EXIT

mcp() {
  # $1 = tool name, $2 = JSON args. Echos the result.content[0].text
  # (already JSON-stringified by the harness) parsed back to JSON. Fails
  # the script if isError=true.
  local tool="$1" args="$2"
  local body
  body=$(jq -nc --arg n "$tool" --argjson a "$args" \
    '{jsonrpc:"2.0",id:1,method:"tools/call",params:{name:$n,arguments:$a}}')
  local resp
  resp=$(curl -sS --fail-with-body -X POST \
    -H "Authorization: Bearer ${KEY}" \
    -H "X-Aki-Org-Id: ${ORG}" \
    -H "X-Aki-Agent-Id: ${AGENT}" \
    -H "X-Aki-Request-Id: ${RUN_ID}-${tool}" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "${URL}/mcp")
  local is_err
  is_err=$(echo "$resp" | jq -r '.result.isError // false')
  local text
  text=$(echo "$resp" | jq -r '.result.content[0].text // empty')
  if [ "$is_err" = "true" ]; then
    echo "  ✗ tool '$tool' returned isError=true:" >&2
    echo "    $text" >&2
    return 1
  fi
  echo "$text"
}

step() { printf '\033[1;34m[%s]\033[0m %s\n' "$1" "$2"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }

step "1/6" "healthz"
curl -fsS "${URL}/healthz" >/dev/null
ok "healthz returned 200"

step "2/6" "MCP tools/list (no tool call)"
tools_count=$(curl -sS --fail-with-body -X POST \
  -H "Authorization: Bearer ${KEY}" \
  -H "X-Aki-Org-Id: ${ORG}" \
  -H "X-Aki-Agent-Id: ${AGENT}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  "${URL}/mcp" | jq '.result.tools | length')
if [ -z "$tools_count" ] || [ "$tools_count" -lt 20 ]; then
  echo "  ✗ expected >=20 tools, got $tools_count" >&2
  exit 1
fi
ok "tools/list returned ${tools_count} tools"

step "3/6" "navigate https://example.com (cold start)"
mcp navigate '{"url":"https://example.com","wait_for_load":true,"timeout":20}' \
  | jq -e '.ok == true' >/dev/null
ok "navigated to example.com"

step "4/6" "extract <title>"
title=$(mcp extract_text '{"selector":"h1","max_chars":200}' | jq -r '.text')
if ! echo "$title" | grep -qi "example"; then
  echo "  ✗ extracted text didn't contain 'example': $title" >&2
  exit 1
fi
ok "extracted: '${title}'"

step "5/6" "SSRF guard blocks 169.254.169.254 (metadata IP)"
ssrf_resp=$(curl -sS --fail-with-body -X POST \
  -H "Authorization: Bearer ${KEY}" \
  -H "X-Aki-Org-Id: ${ORG}" \
  -H "X-Aki-Agent-Id: ${AGENT}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"navigate","arguments":{"url":"http://169.254.169.254/"}}}' \
  "${URL}/mcp")
code=$(echo "$ssrf_resp" | jq -r '.result.content[0].text | fromjson | .code')
if [ "$code" != "ssrf_blocked" ]; then
  echo "  ✗ expected code=ssrf_blocked, got $code" >&2
  echo "    full response: $ssrf_resp" >&2
  exit 1
fi
ok "SSRF guard returned code=ssrf_blocked"

step "6/6" "release_session"
mcp release_session '{"persist":false}' | jq -e '.ok == true' >/dev/null
ok "session released"

printf '\n\033[1;32mall checks passed\033[0m  (url=%s, run_id=%s)\n' "$URL" "$RUN_ID"
