// Local SQLite journal of notes and chat turns captured on the desktop.
// Synced to the cloud Brain via POST /v1/brain/ingest by sync::sync_loop.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};
use serde::Serialize;
use std::path::PathBuf;
use uuid::Uuid;

fn journal_path() -> PathBuf {
    if let Some(home) = std::env::var_os("HOME") {
        PathBuf::from(home).join(".aki-desktop").join("journal.db")
    } else {
        PathBuf::from(".aki-journal.db")
    }
}

pub struct Journal {
    conn: Connection,
}

#[derive(Debug, Serialize)]
pub struct JournalRow {
    pub id: String,
    pub kind: String,
    pub title: Option<String>,
    pub content: String,
    pub created_at: DateTime<Utc>,
}

impl Journal {
    pub fn open() -> Result<Self> {
        let path = journal_path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let conn = Connection::open(&path)
            .with_context(|| format!("open journal at {:?}", path))?;
        conn.execute_batch(
            "create table if not exists notes (
                id text primary key,
                kind text not null,
                title text,
                content text not null,
                created_at text not null,
                sent_at text
            );
            create index if not exists ix_notes_unsent on notes (sent_at) where sent_at is null;",
        )?;
        Ok(Self { conn })
    }

    pub fn add(&self, kind: &str, title: Option<&str>, content: &str) -> Result<String> {
        let id = Uuid::new_v4().to_string();
        let now = Utc::now().to_rfc3339();
        self.conn.execute(
            "insert into notes (id, kind, title, content, created_at)
             values (?1, ?2, ?3, ?4, ?5)",
            params![id, kind, title, content, now],
        )?;
        Ok(id)
    }

    pub fn pending(&self, limit: u32) -> Result<Vec<JournalRow>> {
        let mut stmt = self.conn.prepare(
            "select id, kind, title, content, created_at
             from notes where sent_at is null
             order by created_at asc limit ?1",
        )?;
        let rows = stmt
            .query_map([limit], |r| {
                let created: String = r.get(4)?;
                Ok(JournalRow {
                    id: r.get(0)?,
                    kind: r.get(1)?,
                    title: r.get(2)?,
                    content: r.get(3)?,
                    created_at: DateTime::parse_from_rfc3339(&created)
                        .unwrap_or_else(|_| chrono::DateTime::<Utc>::MIN_UTC.into())
                        .with_timezone(&Utc),
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    pub fn mark_sent(&self, id: &str) -> Result<()> {
        let now = Utc::now().to_rfc3339();
        self.conn.execute(
            "update notes set sent_at = ?1 where id = ?2",
            params![now, id],
        )?;
        Ok(())
    }
}
