# Aki Platform — Frontend Build Prompt

Build the web frontend for **Aki**, an enterprise AI agent platform. This is a Next.js 16 app using the app router.

## Tech Stack
- **Framework**: Next.js 16 + React 19 + TypeScript
- **Auth**: Clerk (`@clerk/nextjs`) with JWT template named `"aki"`
- **Styling**: **Inline styles only** — no Tailwind, no CSS-in-JS libraries. Every component uses a `theme` object and `style={{...}}` props.
- **Fonts**: Source Serif 4 (display), Geist (body), JetBrains Mono (mono) — already wired in `layout.tsx`

## Design System

Use these exact tokens for every page:

```typescript
const theme = {
  bg: "#15161a",
  bgSoft: "#1d1f24",
  ink: "#f1ede0",
  inkLede: "#e3dcc5",
  inkDim: "rgba(241,237,224,0.66)",
  inkFaint: "rgba(241,237,224,0.36)",
  hair: "rgba(241,237,224,0.12)",
  hairSoft: "rgba(241,237,224,0.06)",
  accent: "#c5ec4f",
  accentDim: "rgba(197,236,79,0.18)",
  display: "var(--font-display), 'Times New Roman', serif",
  body: "var(--font-body), system-ui, sans-serif",
  mono: "var(--font-mono), ui-monospace, monospace",
};
```

**Visual rules:**
- Dark background (`theme.bg`), light text (`theme.ink`)
- Accent color is lime green (`#c5ec4f`) — used for buttons, active states, highlights
- Borders use `theme.hair` (subtle)
- Cards use `theme.bgSoft` with 1px `theme.hair` border
- Display font (Source Serif) for headlines and italic accents
- Mono font for metadata, timestamps, labels, code
- Rounded buttons: `borderRadius: 999`
- Section labels: uppercase, `letterSpacing: "0.22em"`, `fontSize: 11`, mono font

## API Base URL
```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
```

## Auth Pattern
Every page is `"use client"` and fetches the token like this:
```typescript
import { useAuth } from "@clerk/nextjs";
const { getToken } = useAuth();
const token = await getToken({ template: "aki" });
const res = await fetch(`${API_URL}/v1/...`, {
  headers: { Authorization: `Bearer ${token}` },
  ...
});
```

## Pages to Build

Build ALL of the following pages. Each should be a complete, production-ready page file.

---

### 1. `/chat` — AI Chat Interface

**Layout:** Full-height chat with message history, input box at bottom, status bar.

**Features:**
- Message list (user messages right-aligned, assistant left-aligned)
- Streaming SSE response from `POST /v1/chat/completions` with `stream: true`
- Parse SSE chunks: `data: {...}` lines containing OpenAI-style deltas
- Extract `hermes.tool.*` events from SSE and show them as tool-call cards
- Input textarea with "Enter to send, Shift+Enter for newline"
- Send button (lime green, rounded pill)
- Status bar showing: connection state, current model, cost of last turn
- Copy-to-clipboard button on assistant messages
- Empty state when no messages yet

**States:** `idle` → `connecting` → `streaming` → `idle`

---

### 2. `/jobs` — Async Job Manager

**Layout:** List view with create modal.

**Features:**
- Fetch `GET /v1/jobs` — returns `Job[]`
- Each job card shows: brief (truncated), status badge, created_at, cost
- Status badges: queued (gray), running (lime pulse), done (green), failed (red), cancelled (orange)
- "New Job" button opens modal with textarea for brief + optional cron schedule
- `POST /v1/jobs` to create
- Polling refresh every 5 seconds when jobs are running
- Click job to navigate to `/jobs/[id]` detail page

---

### 3. `/jobs/[id]` — Job Detail

**Features:**
- Fetch `GET /v1/jobs/{id}` and `GET /v1/jobs/{id}/events`
- SSE stream for live events if job is running
- Event timeline: timestamp + kind + payload
- Cancel button for running jobs (`POST /v1/jobs/{id}/cancel`)
- Result summary display when done

---

### 4. `/connect` — SaaS Connections

**Layout:** Grid of available connectors.

**Features:**
- Fetch `GET /v1/connections` — returns active connections
- OAuth start: `POST /connections/oauth/start?provider=gmail` (etc.)
- Browser Use toggle: `POST /connections/browser/enable` and `/disable`
- Cards per provider with icon, name, status, connect/disconnect button
- Status: pending (yellow dot), active (lime dot), disabled (gray dot)

---

### 5. `/devices` — Aki Desktop Devices

**Features:**
- Fetch `GET /v1/devices`
- "Generate Pair Code" button → `POST /v1/devices/pair/start` → shows 6-digit code with 10-min countdown
- List paired devices with name, last seen, revoke button
- Revoke: `POST /v1/devices/{id}/revoke`
- Polling for new devices every 5 seconds

---

### 6. `/audit` — Audit Log Viewer

**Features:**
- Fetch `GET /v1/audit?limit=100`
- Table with: timestamp, actor, action, target, expandable payload row
- Show hash chain: each row's `content_hash` and `prev_hash`
- Summary stats at top: total events, events today, top actions

---

### 7. `/brain` — Brain Memory (Semantic Search + Ingest)

**Layout:** Two-column. Left = search + results, Right = ingest + sources.

**Features:**
- **Search**: input + "Search" button → `POST /v1/brain/retrieve` with `{query, principals: [org_id]}`
- Results show: score, content snippet, source title/kind
- **Ingest**: title input + textarea + "Ingest" button → `POST /v1/brain/ingest`
- **Sources list**: `GET /v1/brain/sources` — auto-refresh after ingest

---

### 8. `/admin` — Admin Dashboard

**Features:**
- Stats cards: total users, total cost 30d, active departments, total connections
- Navigation cards linking to: Settings, Users, Departments, Usage, GDPR
- Fetch `GET /v1/admin/audit-summary` for top-line stats

---

### 9. `/admin/settings` — Org Settings

**Features:**
- Fetch `GET /v1/admin/org`
- Form fields: org name, hermes model name, idle minutes, spend cap hard, spend cap soft, data retention days
- Save: `PATCH /v1/admin/org`
- Success toast on save

---

### 10. `/admin/users` — User Management

**Features:**
- Fetch `GET /v1/admin/users`
- Table: clerk_user_id, email, role, created_at
- Roles shown as colored badges: owner (lime), admin (blue), member (gray), viewer (faint)

---

### 11. `/admin/departments` — Department Management

**Features:**
- Fetch `GET /v1/departments`
- List with name, slug, model, idle minutes
- "Create Department" modal: name, slug (auto-generated from name), model, slack channel
- `POST /v1/departments`
- Add member modal: clerk_user_id + role (owner/admin/member/viewer)

---

### 12. `/admin/usage` — Usage Analytics

**Features:**
- Fetch `GET /v1/admin/usage`
- Top summary cards: cost 30d, chats, jobs, tool calls
- Daily breakdown table
- Top departments by cost

---

### 13. `/admin/gdpr` — Data Export & Deletion

**Features:**
- "Export Data" button → `GET /v1/gdpr/export` → triggers browser download of NDJSON
- "Delete Account" button with `confirm()` dialog → `POST /v1/gdpr/delete`
- Red danger-zone styling on deletion card

---

### 14. `/billing` — Billing & Usage

**Features:**
- Fetch `GET /v1/billing/usage?days=30`
- Summary cards: total cost, chats, jobs, tool calls
- Daily breakdown table with cost per day

---

### 15. `/me` — User Profile

**Features:**
- Fetch `GET /me`
- Show user info card + org info card
- Link to `/admin`

---

## Shared Components (create these too)

### `AppShell` — Layout wrapper
- 240px sticky left sidebar
- Main nav: Chat, Jobs, Connect, Devices, Audit
- Admin nav (collapsible): Dashboard, Settings, Users, Departments, Usage, GDPR
- Active route highlighted with accent color
- Top bar with page title

### `SectionHeader` — Page title component
- Kicker label (mono, uppercase, faint) + large display font title

### `ErrorBanner` — Error display
- Red border, soft red background, error message + retry button

## Code Style Rules

1. Every page file is a default export function
2. Every page is `"use client"`
3. Use `const [loading, setLoading] = useState(false)` and `const [err, setErr] = useState<string | null>(null)`
4. Use `useEffect` for data fetching on mount
5. No external UI libraries — pure inline styles
6. No `any` types — use proper TypeScript interfaces
7. Handle all API errors with `ErrorBanner`
8. Show loading skeletons/spinners during fetches

## Output Format

Generate each page as a complete, copy-paste-ready TypeScript file. Include:
- Full imports
- Complete component implementation
- All handlers and state
- Inline style objects using the `theme` tokens above

Start with `/chat`, `/brain`, `/admin`, and `/jobs` as the highest priority.
