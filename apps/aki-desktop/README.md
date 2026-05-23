# Aki desktop

Tauri 2.x tray app. Per-employee local agent that pairs with the cloud
control plane and syncs into Brain.

## What's here today (scaffold)

- `src-tauri/` — Rust core skeleton: tray icon registration, global
  shortcut (⌘⇧Space → toggle the chat window), keyring access for the
  device JWT, HTTP client to the cloud API.
- `src/` — Vite + React UI: pairing onboarding (enter 6-digit code from
  the web app), chat surface, settings.
- `aki-mcp-mac/` — placeholder for the macOS MCP server (osascript/EventKit
  wrappers). Not implemented yet.

## What's missing (Phase 3 follow-up)

- Embedded `hermes-agent` subprocess launcher. Today the chat surface
  forwards to the cloud `/v1/chat/completions`; a true local agent
  embeds `hermes-agent` 0.13 and serves its OpenAI-compatible API on
  localhost.
- Local SQLite journal of conversations + notes, with periodic batch
  sync to `POST /v1/brain/ingest` (origin="aki").
- macOS MCP server: calendar (EventKit), mail (osascript), notes,
  shell, filesystem.
- `whisper.cpp` hold-to-talk dictation in the tray.
- Auto-update via Tauri's updater.

## Build (requires Rust + Node)

```bash
cd apps/aki-desktop
npm install
npm run tauri dev
```

To bundle release:

```bash
npm run tauri build
```

The first build downloads the Tauri Rust toolchain (~5min). After that,
incremental dev rebuilds are ~2s.

## Pairing

1. In the web app at `localhost:3000/devices`, click "Generate pairing
   code" — a 6-digit code appears with a 5-minute TTL.
2. Launch Aki desktop. On first run it generates an Ed25519 keypair and
   stores the private key in the OS keychain. It then prompts for the
   6-digit code.
3. The desktop POSTs `{code, name, pubkey}` to
   `/v1/devices/pair/complete` and receives a 30-day device JWT, which
   it stores in the keychain alongside the private key.
4. The web app's device list updates within ~5s to show the new device.

## Architecture

```
┌──────────────────────────────────────────┐
│            Aki desktop                    │
│  ┌────────────────────────────────────┐  │
│  │  Tauri tray (Rust)                  │  │
│  │  - global shortcut                  │  │
│  │  - keychain (device JWT + privkey)  │  │
│  │  - HTTP client to cloud API         │  │
│  │  - SQLite journal                   │  │
│  │  - bg sync → /v1/brain/ingest       │  │
│  └────────┬───────────────────────────┘  │
│           │ Tauri IPC                     │
│  ┌────────▼───────────────────────────┐  │
│  │  React UI (Vite)                    │  │
│  │  - pairing onboarding               │  │
│  │  - chat surface                     │  │
│  │  - settings                         │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
                  │ HTTPS
                  ▼
        ┌─────────────────────┐
        │  Cloud control plane │
        │  (services/api)      │
        └─────────────────────┘
```
