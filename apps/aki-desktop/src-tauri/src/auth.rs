// Keypair + device-JWT storage backed by the OS keychain.
//
// macOS:  Keychain
// Windows: Credential Manager
// Linux:   GNOME secret-service / KWallet
//
// Falls back to a file under the app's local data dir if the keyring
// crate can't locate a provider (headless CI, some Linux containers).
// The file fallback is logged loudly so it doesn't surprise anyone.

use anyhow::{anyhow, Context, Result};
use ed25519_dalek::pkcs8::{DecodePrivateKey, EncodePrivateKey, EncodePublicKey, LineEnding};
use ed25519_dalek::{SigningKey, VerifyingKey};
use rand::rngs::OsRng;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tracing::warn;

const SERVICE: &str = "ai.aki.desktop";
const ITEM_PRIVKEY: &str = "device-privkey";
const ITEM_JWT: &str = "device-jwt";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DeviceKeypair {
    pub private_pem: String,
    pub public_pem: String,
}

fn fallback_dir() -> PathBuf {
    if let Some(home) = std::env::var_os("HOME") {
        PathBuf::from(home).join(".aki-desktop")
    } else if let Some(appdata) = std::env::var_os("APPDATA") {
        PathBuf::from(appdata).join("Aki")
    } else {
        PathBuf::from(".aki-desktop")
    }
}

fn fallback_path(name: &str) -> PathBuf {
    let dir = fallback_dir();
    fs::create_dir_all(&dir).ok();
    dir.join(name)
}

fn keyring_entry(item: &str) -> Result<keyring::Entry> {
    keyring::Entry::new(SERVICE, item)
        .map_err(|e| anyhow!("keyring entry init failed: {e}"))
}

fn read_secret(item: &str) -> Result<Option<String>> {
    match keyring_entry(item).and_then(|e| {
        match e.get_password() {
            Ok(s) => Ok(Some(s)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(other) => Err(anyhow!("keyring read: {other}")),
        }
    }) {
        Ok(v) => Ok(v),
        Err(e) => {
            warn!("keyring unavailable for {item} ({e}); falling back to file");
            let path = fallback_path(item);
            if path.exists() {
                Ok(Some(fs::read_to_string(path)?))
            } else {
                Ok(None)
            }
        }
    }
}

fn write_secret(item: &str, value: &str) -> Result<()> {
    match keyring_entry(item).and_then(|e| {
        e.set_password(value).map_err(|err| anyhow!("keyring write: {err}"))
    }) {
        Ok(()) => Ok(()),
        Err(e) => {
            warn!("keyring unavailable for {item} ({e}); falling back to file");
            fs::write(fallback_path(item), value)?;
            Ok(())
        }
    }
}

pub fn ensure_keypair() -> Result<DeviceKeypair> {
    if let Some(pem) = read_secret(ITEM_PRIVKEY)? {
        let sk = SigningKey::from_pkcs8_pem(&pem)
            .map_err(|e| anyhow!("invalid private key in keychain: {e}"))?;
        let pubkey_pem = sk
            .verifying_key()
            .to_public_key_pem(LineEnding::LF)
            .context("encode pubkey")?;
        return Ok(DeviceKeypair {
            private_pem: pem,
            public_pem: pubkey_pem,
        });
    }

    let sk = SigningKey::generate(&mut OsRng);
    let priv_pem = sk
        .to_pkcs8_pem(LineEnding::LF)
        .context("encode privkey")?
        .to_string();
    let pub_pem = sk
        .verifying_key()
        .to_public_key_pem(LineEnding::LF)
        .context("encode pubkey")?;
    write_secret(ITEM_PRIVKEY, &priv_pem)?;

    Ok(DeviceKeypair {
        private_pem: priv_pem,
        public_pem: pub_pem,
    })
}

pub fn store_device_jwt(jwt: &str) -> Result<()> {
    write_secret(ITEM_JWT, jwt)
}

pub fn load_device_jwt() -> Result<Option<String>> {
    read_secret(ITEM_JWT)
}

pub fn verifying_key_from_pem(pem: &str) -> Result<VerifyingKey> {
    VerifyingKey::from_public_key_pem(pem)
        .map_err(|e| anyhow!("bad pubkey pem: {e}"))
}
