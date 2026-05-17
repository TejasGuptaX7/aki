"""Per-(org, agent, platform) manifest store in R2.

A manifest names the vendor-side container the proxy attaches new
sessions to (Steel profile id or Browserbase context id). The actual
cookies/localStorage/IndexedDB are persisted server-side by the
vendor — we just track the handle.

Key shape: `<org_id>/<agent_id>/<platform>/manifest.json`
Body:
  {"backend": "steel",       "steel_profile_id": "prf_..."}
  {"backend": "browserbase", "browserbase_context_id": "ctx_..."}

If R2 isn't configured the store falls back to in-memory (process
lifetime only) — fine for the smoke test, surfaces clearly in logs in
prod.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

PLATFORM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class Manifest:
    backend: str  # "steel" | "browserbase"
    steel_profile_id: Optional[str] = None
    browserbase_context_id: Optional[str] = None

    def to_json(self) -> str:
        # Drop None fields so manifest stays tidy and forward-compatible.
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "Manifest":
        d = json.loads(raw)
        return cls(
            backend=d["backend"],
            steel_profile_id=d.get("steel_profile_id"),
            browserbase_context_id=d.get("browserbase_context_id"),
        )


class ProfileStore:
    """R2-backed key-value for manifests. Async-safe; the boto3 calls run
    on the default executor."""

    def __init__(
        self,
        endpoint_url: Optional[str],
        access_key: Optional[str],
        secret_key: Optional[str],
        bucket: Optional[str],
        region: str = "auto",
    ):
        self.bucket = bucket
        self.enabled = bool(endpoint_url and access_key and secret_key and bucket)
        self._mem: dict[str, Manifest] = {}  # fallback when storage disabled
        if not self.enabled:
            log.warning(
                "profile_store_disabled — manifests live in-process only; "
                "set BROWSER_HARNESS_R2_* env to enable durable storage"
            )
            self._client = None
            return
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5, read_timeout=15,
            ),
        )
        log.info("profile_store_enabled bucket=%s endpoint=%s", bucket, endpoint_url)

    @classmethod
    def from_env(cls) -> "ProfileStore":
        return cls(
            endpoint_url=os.environ.get("BROWSER_HARNESS_R2_ENDPOINT"),
            access_key=os.environ.get("BROWSER_HARNESS_R2_ACCESS_KEY"),
            secret_key=os.environ.get("BROWSER_HARNESS_R2_SECRET_KEY"),
            bucket=os.environ.get("BROWSER_HARNESS_R2_BUCKET", "aki-browser-profiles"),
            region=os.environ.get("BROWSER_HARNESS_R2_REGION", "auto"),
        )

    @staticmethod
    def _key(org_id: str, agent_id: str, platform: str) -> str:
        if not PLATFORM_RE.match(platform):
            raise ValueError(f"invalid platform name {platform!r}")
        return f"{org_id}/{agent_id}/{platform}/manifest.json"

    async def get(
        self, org_id: str, agent_id: str, platform: str
    ) -> Optional[Manifest]:
        k = self._key(org_id, agent_id, platform)
        if not self.enabled:
            return self._mem.get(k)
        loop = asyncio.get_running_loop()

        def _fetch() -> Optional[Manifest]:
            try:
                obj = self._client.get_object(Bucket=self.bucket, Key=k)
                return Manifest.from_json(obj["Body"].read().decode("utf-8"))
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    return None
                raise
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.error("manifest_corrupt key=%s err=%s", k, e)
                return None

        return await loop.run_in_executor(None, _fetch)

    async def put(
        self, org_id: str, agent_id: str, platform: str, manifest: Manifest
    ) -> None:
        k = self._key(org_id, agent_id, platform)
        if not self.enabled:
            self._mem[k] = manifest
            return
        loop = asyncio.get_running_loop()

        def _put():
            self._client.put_object(
                Bucket=self.bucket, Key=k,
                Body=manifest.to_json().encode("utf-8"),
                ContentType="application/json",
                Metadata={"org_id": org_id, "agent_id": agent_id, "platform": platform},
            )

        await loop.run_in_executor(None, _put)
        log.info(
            "manifest_persisted org=%s agent=%s platform=%s backend=%s",
            org_id, agent_id, platform, manifest.backend,
        )

    async def delete(self, org_id: str, agent_id: str, platform: str) -> bool:
        k = self._key(org_id, agent_id, platform)
        if not self.enabled:
            return self._mem.pop(k, None) is not None
        loop = asyncio.get_running_loop()

        def _del() -> bool:
            try:
                self._client.delete_object(Bucket=self.bucket, Key=k)
                return True
            except ClientError:
                return False

        return await loop.run_in_executor(None, _del)
