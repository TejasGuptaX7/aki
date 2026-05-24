// Embedded hermes-agent launcher.
//
// Looks for the `hermes` binary on PATH (installed via `pip install
// hermes-agent==0.13.0`). Spawns it as a child process pointing at a
// per-user HERMES_HOME under ~/.aki-desktop/hermes/. Surfaces the
// chosen port + bearer to the UI so the chat surface can talk to it.
//
// If `hermes` isn't installed, returns a helpful error the UI can show.

use anyhow::{anyhow, Result};
use rand::{distributions::Alphanumeric, Rng};
use serde::Serialize;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::Stdio;
use tokio::process::Command;
use tokio::sync::Mutex;
use tracing::{info, warn};

static HANDLE: Mutex<Option<HandleInner>> = Mutex::const_new(None);

#[derive(Debug, Clone, Serialize)]
pub struct HermesHandle {
    pub base_url: String,
    pub api_key: String,
    pub pid: u32,
}

struct HandleInner {
    public: HermesHandle,
    pid: u32,
}

fn hermes_home() -> PathBuf {
    if let Some(home) = std::env::var_os("HOME") {
        PathBuf::from(home).join(".aki-desktop").join("hermes")
    } else {
        PathBuf::from(".aki-hermes")
    }
}

fn pick_free_port() -> Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn random_key() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(40)
        .map(char::from)
        .collect()
}

/// Idempotent: returns an existing handle if hermes is already running,
/// otherwise spawns one.
pub async fn start_or_attach() -> Result<HermesHandle> {
    let mut guard = HANDLE.lock().await;
    if let Some(inner) = guard.as_ref() {
        return Ok(inner.public.clone());
    }

    let home = hermes_home();
    std::fs::create_dir_all(&home)?;
    let port = pick_free_port()?;
    let api_key = random_key();

    let mut cmd = Command::new("hermes");
    cmd.args(["gateway", "run", "-v"])
        .env("HERMES_HOME", &home)
        .env("HOME", &home)
        .env("API_SERVER_HOST", "127.0.0.1")
        .env("API_SERVER_PORT", port.to_string())
        .env("API_SERVER_KEY", &api_key)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Ok(key) = std::env::var("OPENAI_API_KEY") {
        cmd.env("OPENAI_API_KEY", key);
    }

    let mut child = cmd.spawn().map_err(|e| {
        anyhow!(
            "couldn't spawn `hermes`: {e}. Install hermes-agent: \
             `pip install hermes-agent==0.13.0`"
        )
    })?;
    let pid = child.id().unwrap_or(0);

    let public = HermesHandle {
        base_url: format!("http://127.0.0.1:{port}"),
        api_key,
        pid,
    };

    // Wait for /v1/models to return 200; bail after 30s.
    wait_for_ready(&public).await?;

    // Spawn a reaper task so we detect crashes and clear the stale handle.
    tauri::async_runtime::spawn(async move {
        let exit = child.wait().await;
        let mut guard = HANDLE.lock().await;
        if let Some(inner) = guard.as_ref() {
            if inner.pid == pid {
                *guard = None;
            }
        }
        match exit {
            Ok(status) if status.success() => info!("local hermes exited cleanly (pid={pid})"),
            Ok(status) => warn!("local hermes exited with code={:?} (pid={pid})", status.code()),
            Err(e) => warn!("local hermes wait error (pid={pid}): {e}"),
        }
    });

    info!("local hermes started on pid={pid} port={port}");
    *guard = Some(HandleInner {
        public: public.clone(),
        pid,
    });
    Ok(public)
}

async fn wait_for_ready(h: &HermesHandle) -> Result<()> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        let r = client
            .get(format!("{}/v1/models", h.base_url))
            .bearer_auth(&h.api_key)
            .send()
            .await;
        if let Ok(resp) = r {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
    }
    Err(anyhow!("local hermes did not become ready within 30s"))
}
