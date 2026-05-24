// Aki desktop — Tauri tray app entrypoint.
//
// Responsibilities:
//   1. Register a system tray icon and a global ⌘⇧Space shortcut to
//      toggle the chat window.
//   2. On first run, generate an Ed25519 keypair, store the private key
//      in the OS keychain, and surface the public key to the UI for
//      pairing.
//   3. Run the pair-complete RPC against the cloud control plane and
//      stash the returned device JWT in the keychain.
//   4. Embed a local hermes-agent subprocess, maintain a SQLite journal,
//      and batch-sync to /v1/brain/ingest.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

mod auth;
mod hermes;
mod journal;
mod sync;

use serde::{Deserialize, Serialize};
use tauri::{
    ipc::Channel,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

#[derive(Debug, Serialize, Deserialize)]
struct PairCompleteRequest {
    code: String,
    name: String,
    pubkey: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct PairCompleteResponse {
    device_id: String,
    device_jwt: String,
    expires_at: String,
}

#[derive(Clone, serde::Serialize)]
struct SseChunk {
    text: String,
}

#[tauri::command]
async fn pair_device(
    code: String,
    name: String,
    api_base: String,
) -> Result<PairCompleteResponse, String> {
    // 1. Read or generate the Ed25519 keypair via auth::ensure_keypair.
    // 2. POST {code, name, pubkey} to /v1/devices/pair/complete.
    // 3. Store the returned device_jwt in the OS keychain.
    let kp = auth::ensure_keypair().map_err(|e| e.to_string())?;
    let pubkey_pem = kp.public_pem;

    let client = reqwest::Client::new();
    let r = client
        .post(format!("{}/v1/devices/pair/complete", api_base))
        .json(&PairCompleteRequest {
            code,
            name,
            pubkey: pubkey_pem,
        })
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if !r.status().is_success() {
        return Err(format!("pair failed: {}", r.status()));
    }
    let resp: PairCompleteResponse = r.json().await.map_err(|e| e.to_string())?;
    auth::store_device_jwt(&resp.device_jwt).map_err(|e| e.to_string())?;
    Ok(resp)
}

#[tauri::command]
fn open_chat(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    Ok(())
}

#[tauri::command]
fn add_journal_note(kind: String, title: Option<String>, content: String) -> Result<String, String> {
    let j = journal::Journal::open().map_err(|e| e.to_string())?;
    j.add(&kind, title.as_deref(), &content).map_err(|e| e.to_string())
}

#[tauri::command]
fn is_paired() -> Result<bool, String> {
    Ok(auth::load_device_jwt().map_err(|e| e.to_string())?.is_some())
}

#[tauri::command]
async fn start_local_hermes() -> Result<hermes::HermesHandle, String> {
    hermes::start_or_attach().await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn send_chat_message(
    messages: Vec<serde_json::Value>,
    on_chunk: Channel<SseChunk>,
) -> Result<(), String> {
    let handle = hermes::start_or_attach().await.map_err(|e| e.to_string())?;

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .post(format!("{}/v1/chat/completions", handle.base_url))
        .bearer_auth(&handle.api_key)
        .json(&serde_json::json!({
            "model": "hermes-agent",
            "messages": messages,
            "stream": true,
        }))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("chat {status}: {body}"));
    }

    let mut buf: Vec<u8> = Vec::new();
    while let Some(chunk) = resp.chunk().await.map_err(|e| e.to_string())? {
        buf.extend_from_slice(&chunk);
        while let Some(end) = buf.windows(2).position(|w| w == b"\n\n").map(|i| i + 2) {
            let text = String::from_utf8_lossy(&buf[..end]).to_string();
            on_chunk.send(SseChunk { text }).map_err(|e| e.to_string())?;
            buf.drain(..end);
        }
    }

    if !buf.is_empty() {
        let text = String::from_utf8_lossy(&buf).to_string();
        on_chunk.send(SseChunk { text }).map_err(|e| e.to_string())?;
    }

    Ok(())
}

fn main() {
    tracing_subscriber::fmt::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            pair_device, open_chat, add_journal_note, is_paired, start_local_hermes, send_chat_message
        ])
        .setup(|app| {
            // ⌘⇧Space → show/focus the chat window.
            let app_handle = app.handle().clone();
            let shortcut = Shortcut::new(
                Some(Modifiers::SUPER | Modifiers::SHIFT),
                Code::Space,
            );
            app.global_shortcut().on_shortcut(shortcut, move |_, _, _| {
                if let Some(w) = app_handle.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            })?;

            // Tray icon + minimal menu (Open / Quit).
            let menu = Menu::with_items(
                app,
                &[
                    &MenuItem::with_id(app, "open", "Open Aki", true, None::<&str>)?,
                    &MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?,
                ],
            )?;
            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(|app, event| {
                    if event.id.as_ref() == "quit" {
                        app.exit(0);
                    } else if event.id.as_ref() == "open" {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // If the device isn't paired yet, show the window immediately
            // so the user sees the pairing screen on first launch.
            if auth::load_device_jwt().unwrap_or(None).is_none() {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }

            // Background sync loop.
            tauri::async_runtime::spawn(sync::sync_loop());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running aki-desktop");
}
