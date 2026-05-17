"""Per-agent profile persistence to S3-compatible object storage (R2 by default).

Each agent's Chromium user-data-dir is tarred + uploaded on session close and
restored on next session open. Key shape: <org_id>/<agent_id>/profile.tar.gz.

The blob contains cookies (Cookies, Cookies-journal), localStorage
(Local Storage/leveldb/*), IndexedDB (IndexedDB/*), and the bare minimum of
Chrome state needed to resume a logged-in tab. We deliberately exclude:
caches, GPU shader caches, Service Worker scripts, and crash dumps — they
inflate the blob 10–50x for no functional gain.

If BROWSER_HARNESS_R2_* env vars are unset, storage is a no-op and profiles
live only on the local disk (dev mode without R2 emulator).
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tarfile
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# Subpaths inside a Chromium user-data-dir worth persisting. Profile names are
# typically "Default" or "Profile 1" — we capture both by walking each
# top-level profile dir we find.
PERSIST_GLOBS = (
    "Cookies",
    "Cookies-journal",
    "Login Data",
    "Login Data-journal",
    "Web Data",
    "Web Data-journal",
    "Preferences",
    "Local State",
    "Local Storage/**/*",
    "Session Storage/**/*",
    "IndexedDB/**/*",
    "databases/**/*",
    "Service Worker/Database/**/*",  # SW *registrations*, not script bodies
    "Extension State/**/*",
    "Extension Cookies",
    "Extension Cookies-journal",
)

# Skip everything under these dirs — caches, crashes, gpu.
SKIP_DIRS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "Service Worker/CacheStorage",
    "Service Worker/ScriptCache",
    "blob_storage",
    "File System",
    "Application Cache",
    "GrShaderCache",
    "ShaderCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "Crash Reports",
)


class ProfileStorage:
    """R2/S3 client + tar pack/unpack helpers, scoped to a single bucket.

    Initialize once at service startup. Methods are async-safe (real S3 calls
    happen on the default executor).
    """

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
        if not self.enabled:
            log.info("profile_storage_disabled (set BROWSER_HARNESS_R2_* env to enable)")
            self._client = None
            return
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            # Cloudflare R2 / minio compatibility — path-style addressing,
            # no AWS-specific virtual-host hacks, sigv4 always.
            config=BotoConfig(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )
        log.info(
            "profile_storage_enabled bucket=%s endpoint=%s", bucket, endpoint_url
        )

    @classmethod
    def from_env(cls) -> "ProfileStorage":
        return cls(
            endpoint_url=os.environ.get("BROWSER_HARNESS_R2_ENDPOINT"),
            access_key=os.environ.get("BROWSER_HARNESS_R2_ACCESS_KEY"),
            secret_key=os.environ.get("BROWSER_HARNESS_R2_SECRET_KEY"),
            bucket=os.environ.get("BROWSER_HARNESS_R2_BUCKET", "aki-browser-profiles"),
            region=os.environ.get("BROWSER_HARNESS_R2_REGION", "auto"),
        )

    @staticmethod
    def key(org_id: str, agent_id: str) -> str:
        return f"{org_id}/{agent_id}/profile.tar.gz"

    async def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist. No-op on real R2 (where bucket
        creation is a dashboard action), useful for minio in dev."""
        if not self.enabled:
            return
        loop = asyncio.get_running_loop()

        def _create():
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    try:
                        self._client.create_bucket(Bucket=self.bucket)
                        log.info("created_bucket bucket=%s", self.bucket)
                    except ClientError as ce:
                        if ce.response.get("Error", {}).get("Code") != "BucketAlreadyOwnedByYou":
                            raise

        await loop.run_in_executor(None, _create)

    async def download(self, org_id: str, agent_id: str, dest_dir: Path) -> bool:
        """Pull <org>/<agent>/profile.tar.gz and unpack into dest_dir.

        Returns True if a profile was restored, False if no key existed. Any
        other error raises — the caller decides whether to fall back to a
        fresh profile or fail the request.
        """
        if not self.enabled:
            return False
        loop = asyncio.get_running_loop()

        def _fetch() -> Optional[bytes]:
            try:
                obj = self._client.get_object(
                    Bucket=self.bucket, Key=self.key(org_id, agent_id)
                )
                return obj["Body"].read()
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    return None
                raise

        blob = await loop.run_in_executor(None, _fetch)
        if blob is None:
            return False

        dest_dir.mkdir(parents=True, exist_ok=True)

        def _unpack():
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                _safe_extract(tar, dest_dir)

        await loop.run_in_executor(None, _unpack)
        log.info(
            "profile_restored org=%s agent=%s bytes=%d", org_id, agent_id, len(blob)
        )
        return True

    async def upload(self, org_id: str, agent_id: str, src_dir: Path) -> int:
        """Tar.gz src_dir (filtered) and push to <org>/<agent>/profile.tar.gz.

        Returns uploaded byte count. No-op (returns 0) if storage is disabled
        or src_dir doesn't exist.
        """
        if not self.enabled or not src_dir.exists():
            return 0
        loop = asyncio.get_running_loop()

        def _pack_and_push() -> int:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
                _pack_profile(tar, src_dir)
            size = buf.tell()
            buf.seek(0)
            self._client.put_object(
                Bucket=self.bucket,
                Key=self.key(org_id, agent_id),
                Body=buf,
                ContentType="application/gzip",
                Metadata={"org_id": org_id, "agent_id": agent_id},
            )
            return size

        size = await loop.run_in_executor(None, _pack_and_push)
        log.info(
            "profile_persisted org=%s agent=%s bytes=%d", org_id, agent_id, size
        )
        return size

    async def delete(self, org_id: str, agent_id: str) -> bool:
        """Remove an agent's persisted profile. Used when the agent is deleted."""
        if not self.enabled:
            return False
        loop = asyncio.get_running_loop()

        def _del() -> bool:
            try:
                self._client.delete_object(
                    Bucket=self.bucket, Key=self.key(org_id, agent_id)
                )
                return True
            except ClientError:
                return False

        return await loop.run_in_executor(None, _del)


def _pack_profile(tar: tarfile.TarFile, src_dir: Path) -> None:
    """Add only the subset of files defined by PERSIST_GLOBS, skipping caches."""
    skip_abs = {str(src_dir / s) for s in SKIP_DIRS}

    def _under_skip(p: Path) -> bool:
        sp = str(p)
        return any(sp.startswith(s + os.sep) or sp == s for s in skip_abs)

    seen: set[Path] = set()
    for pattern in PERSIST_GLOBS:
        # rglob handles both literal files (Cookies) and nested globs
        # ("Local Storage/**/*"). Path.glob with ** matches subdirectories;
        # rglob with the bare pattern matches anywhere — we want glob from
        # the profile root for accuracy.
        for path in src_dir.glob(pattern):
            if path in seen or not path.is_file() or _under_skip(path):
                continue
            seen.add(path)
            arcname = path.relative_to(src_dir).as_posix()
            try:
                tar.add(path, arcname=arcname, recursive=False)
            except (OSError, ValueError) as e:
                log.warning("profile_pack_skipped path=%s err=%s", path, e)


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """tarfile.extractall with a path-traversal guard.

    Without this, a malicious .tar.gz could contain '../../etc/passwd' and
    escape dest. Since profiles round-trip through R2, treat them as
    untrusted input even though we produced them.
    """
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        # Reject absolute paths and any '..' traversal segments
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            log.warning("profile_extract_rejected member=%s", member.name)
            continue
        target = (dest_resolved / member.name).resolve()
        if dest_resolved not in target.parents and target != dest_resolved:
            log.warning("profile_extract_outside_dest member=%s", member.name)
            continue
        # Skip symlinks/hardlinks — they're not in the persist set, but be
        # paranoid: a tampered tar could include them.
        if member.issym() or member.islnk():
            continue
        tar.extract(member, dest_resolved)
