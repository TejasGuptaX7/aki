# Connect page — smoke tests

Tests the rewritten `/connect` flow against `services/api/app/routes/connections.py`.

## What changed

- `apps/web/src/app/connect/page.tsx` — Pipedream removed. Two sections:
  - **native · our own oauth** — `gmail`, `slack`, `notion`, `linear`, `hubspot`
    (+ Browser Mode card). Click → `POST /connections/oauth/start` →
    redirect to `auth_url`. Provider redirects back to
    `/connect/oauth/callback`.
  - **other · via arcade** — long-tail providers. Click →
    `POST /connections/arcade/start` → store `{auth_id, provider, agentId}`
    in `sessionStorage` → redirect to `auth_url`. Arcade redirects back to
    `/connect?arcade=ok` and we `arcade/status` then `arcade/record`.
- `apps/web/src/app/connect/oauth/callback/page.tsx` — new. Pulls
  `code` and `state` from the URL, `POST`s them to
  `/connections/oauth/callback`, then bounces back to `/connect` with
  `?ok=1` / `?err=…`.
- `apps/web/src/lib/api.ts` — `connectionsApi` now exposes
  `oauthStart`, `oauthCallback`, `arcadeStart`, `arcadeStatus`,
  `arcadeRecord`. Pipedream methods removed.

## Prereqs to run the API locally

```
cd services/api
source .venv/bin/activate
# Source .env stripping any trailing "# comment"
set -a; while IFS='=' read -r k v; do
  [[ -z "$k" || "$k" =~ ^# ]] && continue
  printf -v "$k" '%s' "$(printf '%s' "$v" | sed -E 's/[[:space:]]+#.*$//')"
  export "$k"
done < .env; set +a
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

The smokes below use `ALLOW_DEV_AUTH_BYPASS=true` (already on in
`services/api/.env`) — the API accepts an `X-Dev-Org-Id` header in
place of a Clerk bearer token. Don't ship this header to prod.

```
B=http://127.0.0.1:8765
ORG=$(uuidgen)
```

## 1. List (auth required)

```
curl -i $B/connections
```

Expect `401 missing bearer token`. With dev bypass:

```
curl -i -H "X-Dev-Org-Id: $ORG" $B/connections
```

Expect `200 []`.

## 2. Native OAuth start

Unknown provider should 400 with the list of registered handlers:

```
curl -i -H "X-Dev-Org-Id: $ORG" \
  -X POST "$B/connections/oauth/start?provider=bogus"
```

Observed: `400 {"detail":"unsupported provider; native handlers:
['gmail', 'hubspot', 'linear', 'notion', 'slack']"}`.

Valid provider, no client creds configured → 503 (caught
`NativeOAuthError`):

```
curl -i -H "X-Dev-Org-Id: $ORG" \
  -X POST "$B/connections/oauth/start?provider=gmail"
```

Observed: `503 {"detail":"oauth start failed: gmail OAuth client_id
not configured"}`.

Once `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` (and the equivalents
for `SLACK_*`, `NOTION_*`, `LINEAR_*`, `HUBSPOT_*`) are in `.env`,
the same call returns:

```
{
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?...&state=…",
  "state": "<signed-token>",
  "provider": "gmail",
  "agent_id": null
}
```

The frontend then does `window.location.href = auth_url`.

## 3. Native OAuth callback (state validation)

Malformed state must be rejected without trying to exchange the code:

```
curl -i -X POST -H "Content-Type: application/json" \
  -d '{"code":"foo","state":"not-a-valid-state"}' \
  $B/connections/oauth/callback
```

Observed: `400 {"detail":"malformed state: …"}`. This proves the
callback endpoint does NOT require a bearer token — it trusts only the
HMAC-signed state from `/oauth/start`. (Frontend at
`apps/web/src/app/connect/oauth/callback/page.tsx` still sends
`Authorization` if Clerk has a session, but the backend ignores it.)

To exercise the happy path you need a real `state` from step 2 plus a
real `code` from the provider redirect — easiest to drive in the
browser. The page will land on `/connect/oauth/callback?code=…&state=…`,
post both fields, and bounce to `/connect?ok=1`.

## 4. Arcade start / status / record

`/connections/arcade/start` reaches Arcade with our project key. With
`google_calendar` (an example slug from `ARCADE_CATALOG` in
`page.tsx`) but no matching dashboard auth provider:

```
curl -i -H "X-Dev-Org-Id: $ORG" \
  -H "Content-Type: application/json" \
  -X POST -d '{"provider":"google_calendar"}' \
  $B/connections/arcade/start
```

Observed: `502 {"detail":"upstream: arcade POST /v1/auth/authorize
failed"}`. Once the provider is registered in the Arcade dashboard the
same call returns:

```
{
  "auth_id":  "auth_xxx",
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
  "status":   "pending",
  "user_id":  "<org-uuid>",
  "agent_id": null
}
```

Status poll (server long-polls Arcade up to 59s):

```
curl -i -H "X-Dev-Org-Id: $ORG" \
  "$B/connections/arcade/status?auth_id=auth_bogus"
```

Observed: `502` for a bogus id (Arcade returns 404). Valid id returns
`{ "id": "...", "status": "pending"|"completed"|..., ... }`.

Record (must call after Arcade flow completes; we re-fetch status
server-side, so the frontend can't lie):

```
curl -i -H "X-Dev-Org-Id: $ORG" \
  -H "Content-Type: application/json" \
  -X POST -d '{"auth_id":"auth_bogus"}' \
  $B/connections/arcade/record
```

Observed: `502` for the bogus id. With a real, completed auth this
inserts a `Connection` row and returns it.

## 5. Frontend full flow (browser, not curl)

1. `cd apps/web && npm run dev`
2. Sign in via Clerk on `http://localhost:3000`.
3. Visit `/connect`.
4. **Native:** click "Connect Gmail" → redirect to Google → consent
   → land on `/connect/oauth/callback` → bounce to
   `/connect?ok=1&agent_id=…`. New `gmail` card shows up in `active`.
5. **Arcade:** click "Connect Google Calendar" (under *other · via
   arcade*) → redirect to Arcade-hosted Google consent → land on
   `/connect?arcade=ok` → the page reads `aki.arcade.pending` from
   sessionStorage, polls status, posts to `/arcade/record`, and shows
   a new `google_calendar` card in `active`. The `?arcade=ok` query
   param is stripped from the URL.

## What is NOT covered

- Native handler integration tests against real provider sandboxes —
  belongs in `services/api/tests/`, not here.
- Refresh-on-demand from `native_mcp.py` — separate test surface.
- Verification that Arcade dashboard slugs in `ARCADE_CATALOG`
  (page.tsx) match what's registered server-side. Add to that list
  only providers you've actually wired up in Arcade admin.
