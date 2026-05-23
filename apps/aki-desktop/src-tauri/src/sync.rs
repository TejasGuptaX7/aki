// Background sync: every N seconds, flush local journal rows into
// the cloud Brain via POST /v1/brain/ingest using the device JWT.

use crate::auth::load_device_jwt;
use crate::journal::Journal;
use anyhow::{anyhow, Result};
use serde::Serialize;
use std::time::Duration;
use tracing::{info, warn};

const SYNC_INTERVAL: Duration = Duration::from_secs(60);
const BATCH_SIZE: u32 = 10;

fn api_base() -> String {
    std::env::var("AKI_API_BASE")
        .unwrap_or_else(|_| "http://localhost:8000".to_string())
}

#[derive(Debug, Serialize)]
struct IngestBody<'a> {
    scope: &'a str,
    kind: &'a str,
    origin: &'a str,
    uri: Option<&'a str>,
    title: Option<&'a str>,
    content: &'a str,
}

pub async fn sync_loop() {
    loop {
        match tick().await {
            Ok(n) if n > 0 => info!("sync tick: flushed {} rows", n),
            Ok(_) => {}
            Err(e) => warn!("sync tick failed: {}", e),
        }
        tokio::time::sleep(SYNC_INTERVAL).await;
    }
}

async fn tick() -> Result<u32> {
    let jwt = match load_device_jwt()? {
        Some(j) => j,
        None => return Ok(0), // not paired yet; nothing to sync
    };

    let journal = Journal::open()?;
    let pending = journal.pending(BATCH_SIZE)?;
    if pending.is_empty() {
        return Ok(0);
    }

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()?;

    let mut flushed = 0u32;
    for row in pending {
        let uri = format!("aki-desktop://{}", row.id);
        let body = IngestBody {
            scope: "user",
            kind: &row.kind,
            origin: "aki",
            uri: Some(&uri),
            title: row.title.as_deref(),
            content: &row.content,
        };
        let r = client
            .post(format!("{}/v1/brain/ingest", api_base()))
            .bearer_auth(&jwt)
            .json(&body)
            .send()
            .await;
        match r {
            Ok(resp) if resp.status().is_success() => {
                journal.mark_sent(&row.id)?;
                flushed += 1;
            }
            Ok(resp) => {
                let status = resp.status();
                let text = resp.text().await.unwrap_or_default();
                if status == 401 {
                    // JWT expired or revoked; stop until the user re-pairs.
                    return Err(anyhow!("device JWT rejected ({status}); needs re-pair: {text}"));
                }
                warn!("ingest row {} returned {}: {}", row.id, status, text);
                break; // back off — try again next tick
            }
            Err(e) => {
                warn!("ingest network error for {}: {}", row.id, e);
                break;
            }
        }
    }
    Ok(flushed)
}
