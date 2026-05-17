"""aiohttp MCP server for the Aki browser harness.

Speaks MCP Streamable HTTP (JSON-RPC 2.0) on POST /mcp. Per-request flow:

  1. Validate Authorization + X-Aki-Org-Id + X-Aki-Agent-Id headers.
  2. Parse JSON-RPC envelope; dispatch by method.
  3. For tools/call, acquire the (org, agent) session from the pool,
     route the work via the daemon's IPC socket, and return the result
     wrapped as MCP content[].

The protocol contract is in PROTOCOL.md — this file is the implementation.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import fnmatch
import hmac
import io
import ipaddress
import json
import logging
import os
import re
import socket
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from aiohttp import web

from pool import BrowserPool, Session
from storage import ProfileStorage

PROTOCOL_VERSION = "2025-03-26"
SERVER_VERSION = "0.1.0"
SERVER_NAME = "aki-browser-harness"

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
SKILLS_ROOT = Path(
    os.environ.get("BROWSER_HARNESS_SKILLS_ROOT", "/var/lib/aki/browser-harness/skills")
).expanduser()
SHARED_SKILLS_DIR = "_shared"

DEFAULT_ALLOWED_HOSTS = tuple(
    h.strip().lower()
    for h in os.environ.get("BROWSER_HARNESS_ALLOWED_HOSTS", "").split(",")
    if h.strip()
)

# Pages that match these strings in their (visible) text or title are
# treated as captcha walls. The agent surfaces this as `captcha_required`
# so the caller can escalate to a human or a per-customer solver.
CAPTCHA_NEEDLES = (
    "verify you are human",
    "are you a robot",
    "checking your browser",
    "cloudflare to access",
    "captcha",
    "hcaptcha",
    "recaptcha",
    "please confirm you are not a robot",
)

log = logging.getLogger("browser-harness")


# ----- JSON-RPC helpers -------------------------------------------------------

def _jrpc_ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jrpc_err(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _tool_ok(value: Any, *, request_id: str, duration_ms: int) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(value, default=str)}],
        "isError": False,
        "_meta": {"request_id": request_id, "duration_ms": duration_ms},
    }


def _tool_err(code: str, detail: str, *, request_id: str, duration_ms: int, **extra) -> dict:
    payload = {"code": code, "detail": detail, **extra}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "isError": True,
        "_meta": {"request_id": request_id, "duration_ms": duration_ms},
    }


class ToolError(Exception):
    """Raised from inside a tool to bubble a structured error to the caller."""

    def __init__(self, code: str, detail: str, **extra):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.extra = extra


# ----- Daemon IPC (per-session) -----------------------------------------------

class DaemonClient:
    """Thin async client over the browser-harness daemon's Unix socket.

    We do socket I/O on the default executor — the daemon's request handler
    is sequential per-connection but cheap, and offloading keeps the aiohttp
    event loop responsive when CDP calls go slow."""

    def __init__(self, sess: Session):
        self.sess = sess
        self.sock_path = str(sess.runtime_dir / "bu.sock")

    async def _send(self, payload: dict, *, timeout: float = 30.0) -> dict:
        loop = asyncio.get_running_loop()

        def _blocking() -> dict:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                s.connect(self.sock_path)
                s.sendall((json.dumps(payload) + "\n").encode())
                data = b""
                while not data.endswith(b"\n"):
                    chunk = s.recv(1 << 16)
                    if not chunk:
                        break
                    data += chunk
                return json.loads(data or b"{}")
            finally:
                s.close()

        return await loop.run_in_executor(None, _blocking)

    async def cdp(
        self, method: str, params: Optional[dict] = None, *, session_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict:
        resp = await self._send(
            {"method": method, "params": params or {}, "session_id": session_id},
            timeout=timeout,
        )
        if "error" in resp:
            raise ToolError("cdp_error", str(resp["error"]))
        return resp.get("result", {})

    async def meta(self, name: str, **kwargs) -> dict:
        resp = await self._send({"meta": name, **kwargs})
        if "error" in resp:
            raise ToolError("daemon_error", str(resp["error"]))
        return resp


# ----- Tool implementations ---------------------------------------------------

async def _ensure_real_tab(d: DaemonClient) -> str:
    """Return the active session_id; if no real tab is attached, create one."""
    meta = await d.meta("session")
    if meta.get("session_id"):
        return meta["session_id"]
    # No active session — let the daemon attach a fresh tab
    targets = (await d.cdp("Target.getTargets")).get("targetInfos", [])
    real = [t for t in targets if t.get("type") == "page" and not _is_internal(t.get("url", ""))]
    if real:
        tid = real[0]["targetId"]
    else:
        tid = (await d.cdp("Target.createTarget", {"url": "about:blank"}))["targetId"]
    sid = (await d.cdp("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
    await d.meta("set_session", session_id=sid, target_id=tid)
    return sid


def _is_internal(url: str) -> bool:
    return url.startswith(("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:"))


def _check_url(url: str) -> None:
    """SSRF guard. Raises ToolError(ssrf_blocked) for private/metadata IPs.

    Allowlist via env BROWSER_HARNESS_ALLOWED_HOSTS (comma-sep, wildcards OK)
    bypasses the check — used for internal company tools."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise ToolError("bad_args", f"unparseable URL: {url!r}")
    if parsed.scheme not in ("http", "https"):
        raise ToolError("bad_args", f"only http/https URLs allowed, got {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ToolError("bad_args", "URL has no host")

    if any(fnmatch.fnmatch(host, pat) for pat in DEFAULT_ALLOWED_HOSTS):
        return

    # Resolve all addresses and reject if any is in a blocked range. We
    # block on the union (not the intersection) — if a hostname resolves
    # to both a public IP and a private one (DNS rebinding setup), we
    # refuse rather than let the request slip through on first-record-wins.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ToolError("ssrf_blocked", f"could not resolve {host!r}: {e}")
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise ToolError(
                "ssrf_blocked",
                f"{host} → {ip_str} is private/metadata; set BROWSER_HARNESS_ALLOWED_HOSTS to allow",
            )


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # ip_address covers the standard rfc1918/loopback/link-local/multicast
    # bits via these properties. We add the cloud metadata IP explicitly.
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return True
    return any([
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_unspecified,
        ip.is_reserved,
    ])


async def _maybe_detect_captcha(d: DaemonClient, sid: str) -> None:
    """If the page text or title looks like a captcha wall, raise."""
    try:
        title = (
            await d.cdp(
                "Runtime.evaluate",
                {"expression": "document.title", "returnByValue": True},
                session_id=sid,
                timeout=5,
            )
        ).get("result", {}).get("value", "")
        # innerText of body, truncated to keep the round trip small
        body = (
            await d.cdp(
                "Runtime.evaluate",
                {
                    "expression": "(document.body && document.body.innerText || '').slice(0, 4000)",
                    "returnByValue": True,
                },
                session_id=sid,
                timeout=5,
            )
        ).get("result", {}).get("value", "")
    except Exception:
        return
    haystack = f"{title}\n{body}".lower()
    for needle in CAPTCHA_NEEDLES:
        if needle in haystack:
            raise ToolError("captcha_required", f"page text contained {needle!r}", title=title)


# ---- per-tool handlers (return any JSON value or raise ToolError) ------------

async def tool_navigate(d: DaemonClient, args: dict) -> dict:
    url = _require(args, "url", str)
    _check_url(url)
    new_tab = bool(args.get("new_tab", False))
    do_wait = bool(args.get("wait_for_load", True))
    timeout = float(args.get("timeout", 15))

    if new_tab:
        tid = (await d.cdp("Target.createTarget", {"url": "about:blank"}))["targetId"]
        sid = (await d.cdp("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        await d.meta("set_session", session_id=sid, target_id=tid)
    else:
        await _ensure_real_tab(d)
        sid = (await d.meta("session"))["session_id"]

    nav = await d.cdp("Page.navigate", {"url": url}, session_id=sid)
    if nav.get("errorText"):
        raise ToolError("navigation_failed", nav["errorText"], url=url)
    if do_wait:
        await _wait_for_ready(d, sid, timeout)
    await _maybe_detect_captcha(d, sid)
    info = await _page_info(d, sid)
    return {"ok": True, "url": info.get("url"), "title": info.get("title")}


async def tool_click(d: DaemonClient, args: dict) -> dict:
    x = float(_require(args, "x", (int, float)))
    y = float(_require(args, "y", (int, float)))
    button = args.get("button", "left")
    if button not in ("left", "right", "middle"):
        raise ToolError("bad_args", f"button must be left/right/middle, got {button!r}")
    clicks = int(args.get("clicks", 1))
    sid = await _ensure_real_tab(d)
    await d.cdp(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": clicks},
        session_id=sid,
    )
    await d.cdp(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": clicks},
        session_id=sid,
    )
    return {"ok": True}


async def tool_type(d: DaemonClient, args: dict) -> dict:
    text = _require(args, "text", str)
    sid = await _ensure_real_tab(d)
    await d.cdp("Input.insertText", {"text": text}, session_id=sid)
    return {"ok": True}


async def tool_fill(d: DaemonClient, args: dict) -> dict:
    selector = _require(args, "selector", str)
    text = _require(args, "text", str)
    clear_first = bool(args.get("clear_first", True))
    timeout = float(args.get("timeout", 0))
    sid = await _ensure_real_tab(d)
    if timeout > 0:
        found = await _poll_js(d, sid, f"!!document.querySelector({json.dumps(selector)})", timeout)
        if not found:
            raise ToolError("element_not_found", selector)
    focused = await _eval(
        d, sid,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return false;e.focus();return true;}})()",
    )
    if not focused:
        raise ToolError("element_not_found", selector)
    if clear_first:
        mods = 4 if sys.platform == "darwin" else 2
        await d.cdp(
            "Input.dispatchKeyEvent",
            {"type": "rawKeyDown", "key": "a", "code": "KeyA", "modifiers": mods,
             "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65},
            session_id=sid,
        )
        await d.cdp(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": mods,
             "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65},
            session_id=sid,
        )
        await _press_key(d, sid, "Backspace")
    for ch in text:
        await _press_key(d, sid, ch)
    await _eval(
        d, sid,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return;"
        f"e.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"e.dispatchEvent(new Event('change',{{bubbles:true}}));}})();",
    )
    return {"ok": True}


async def tool_press_key(d: DaemonClient, args: dict) -> dict:
    key = _require(args, "key", str)
    mods = int(args.get("modifiers", 0))
    sid = await _ensure_real_tab(d)
    await _press_key(d, sid, key, mods)
    return {"ok": True}


async def tool_scroll(d: DaemonClient, args: dict) -> dict:
    x = float(_require(args, "x", (int, float)))
    y = float(_require(args, "y", (int, float)))
    dy = float(args.get("dy", -300))
    dx = float(args.get("dx", 0))
    sid = await _ensure_real_tab(d)
    await d.cdp(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy},
        session_id=sid,
    )
    return {"ok": True}


async def tool_screenshot(d: DaemonClient, args: dict) -> dict:
    full = bool(args.get("full_page", False))
    max_dim = args.get("max_dim")
    sid = await _ensure_real_tab(d)
    r = await d.cdp(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": full},
        session_id=sid,
        timeout=30,
    )
    b64 = r.get("data", "")
    if max_dim:
        try:
            from PIL import Image
        except ImportError:
            pass
        else:
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            if max(img.size) > int(max_dim):
                img.thumbnail((int(max_dim), int(max_dim)))
                out = io.BytesIO()
                img.save(out, format="PNG")
                b64 = base64.b64encode(out.getvalue()).decode("ascii")
    return {"mime": "image/png", "base64": b64}


async def tool_extract_text(d: DaemonClient, args: dict) -> dict:
    selector = str(args.get("selector", "body"))
    max_chars = int(args.get("max_chars", 8000))
    sid = await _ensure_real_tab(d)
    expr = (
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return null;return (e.innerText||e.textContent||'').slice(0,{max_chars + 1});}})()"
    )
    val = await _eval(d, sid, expr)
    if val is None:
        raise ToolError("element_not_found", selector)
    truncated = len(val) > max_chars
    return {"text": val[:max_chars], "truncated": truncated}


async def tool_extract_html(d: DaemonClient, args: dict) -> dict:
    selector = str(args.get("selector", "html"))
    max_chars = int(args.get("max_chars", 64000))
    sid = await _ensure_real_tab(d)
    expr = (
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return null;return e.outerHTML.slice(0,{max_chars + 1});}})()"
    )
    val = await _eval(d, sid, expr)
    if val is None:
        raise ToolError("element_not_found", selector)
    truncated = len(val) > max_chars
    return {"html": val[:max_chars], "truncated": truncated}


async def tool_page_info(d: DaemonClient, args: dict) -> dict:
    sid = await _ensure_real_tab(d)
    dialog = (await d.meta("pending_dialog")).get("dialog")
    if dialog:
        return {"dialog": dialog}
    return await _page_info(d, sid)


async def tool_list_tabs(d: DaemonClient, args: dict) -> dict:
    include_internal = bool(args.get("include_internal", False))
    targets = (await d.cdp("Target.getTargets")).get("targetInfos", [])
    tabs = []
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url", "")
        if not include_internal and _is_internal(url):
            continue
        tabs.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": url})
    return {"tabs": tabs}


async def tool_switch_tab(d: DaemonClient, args: dict) -> dict:
    tid = _require(args, "target_id", str)
    await d.cdp("Target.activateTarget", {"targetId": tid})
    sid = (await d.cdp("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
    await d.meta("set_session", session_id=sid, target_id=tid)
    return {"ok": True, "session_id": sid}


async def tool_new_tab(d: DaemonClient, args: dict) -> dict:
    url = str(args.get("url", "about:blank"))
    if url != "about:blank":
        _check_url(url)
    tid = (await d.cdp("Target.createTarget", {"url": "about:blank"}))["targetId"]
    sid = (await d.cdp("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
    await d.meta("set_session", session_id=sid, target_id=tid)
    if url != "about:blank":
        nav = await d.cdp("Page.navigate", {"url": url}, session_id=sid)
        if nav.get("errorText"):
            raise ToolError("navigation_failed", nav["errorText"], url=url)
    return {"target_id": tid, "url": url}


async def tool_close_tab(d: DaemonClient, args: dict) -> dict:
    tid = args.get("target_id")
    if not tid:
        info = await d.meta("current_tab")
        tid = info.get("targetId")
    if not tid:
        raise ToolError("not_attached", "no current tab to close")
    await d.cdp("Target.closeTarget", {"targetId": tid})
    return {"ok": True}


async def tool_wait_for_load(d: DaemonClient, args: dict) -> dict:
    timeout = float(args.get("timeout", 15))
    sid = await _ensure_real_tab(d)
    ok = await _wait_for_ready(d, sid, timeout)
    return {"loaded": ok}


async def tool_wait_for_element(d: DaemonClient, args: dict) -> dict:
    selector = _require(args, "selector", str)
    timeout = float(args.get("timeout", 10))
    visible = bool(args.get("visible", False))
    sid = await _ensure_real_tab(d)
    if visible:
        check = (
            f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
            f"if(!e)return false;"
            f"if(typeof e.checkVisibility==='function')"
            f"return e.checkVisibility({{checkOpacity:true,checkVisibilityCSS:true}});"
            f"const s=getComputedStyle(e);"
            f"return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'}})()"
        )
    else:
        check = f"!!document.querySelector({json.dumps(selector)})"
    found = await _poll_js(d, sid, check, timeout)
    return {"found": found}


async def tool_wait_for_network_idle(d: DaemonClient, args: dict) -> dict:
    timeout = float(args.get("timeout", 10))
    idle_ms = int(args.get("idle_ms", 500))
    sid = await _ensure_real_tab(d)
    deadline = time.monotonic() + timeout
    last = time.monotonic()
    inflight: set[str] = set()
    active_session = sid
    while time.monotonic() < deadline:
        events = (await d.meta("drain_events")).get("events", [])
        for e in events:
            if e.get("session_id") != active_session:
                continue
            m = e.get("method", "")
            p = e.get("params", {}) or {}
            if m == "Network.requestWillBeSent":
                inflight.add(p.get("requestId"))
                last = time.monotonic()
            elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                inflight.discard(p.get("requestId"))
                last = time.monotonic()
            elif m.startswith("Network."):
                last = time.monotonic()
        if not inflight and (time.monotonic() - last) * 1000 >= idle_ms:
            return {"idle": True}
        await asyncio.sleep(0.1)
    return {"idle": False}


async def tool_js(d: DaemonClient, args: dict) -> dict:
    expression = _require(args, "expression", str)
    await_promise = bool(args.get("await_promise", True))
    sid = await _ensure_real_tab(d)
    try:
        val = await _eval(d, sid, expression, await_promise=await_promise)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError("js_error", str(e))
    return {"value": val}


async def tool_upload_file(d: DaemonClient, args: dict) -> dict:
    selector = _require(args, "selector", str)
    paths = args.get("paths") or []
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ToolError("bad_args", "paths must be list[str]")
    # Resolve every path against the per-agent profile dir; reject anything
    # that escapes it. The agent must stage uploads inside its own profile.
    agent_root = d.sess.profile_dir.parent
    resolved = []
    for p in paths:
        candidate = (agent_root / p).resolve()
        if agent_root.resolve() not in candidate.parents and candidate != agent_root.resolve():
            raise ToolError("bad_args", f"upload path {p!r} escapes agent dir")
        if not candidate.is_file():
            raise ToolError("bad_args", f"upload path {p!r} not found under agent dir")
        resolved.append(str(candidate))
    sid = await _ensure_real_tab(d)
    doc = await d.cdp("DOM.getDocument", {"depth": -1}, session_id=sid)
    nid = (await d.cdp(
        "DOM.querySelector",
        {"nodeId": doc["root"]["nodeId"], "selector": selector},
        session_id=sid,
    )).get("nodeId")
    if not nid:
        raise ToolError("element_not_found", selector)
    await d.cdp("DOM.setFileInputFiles", {"files": resolved, "nodeId": nid}, session_id=sid)
    return {"ok": True}


async def tool_http_get(d: DaemonClient, args: dict) -> dict:
    url = _require(args, "url", str)
    _check_url(url)
    headers = args.get("headers") or {}
    if not isinstance(headers, dict):
        raise ToolError("bad_args", "headers must be object")
    timeout = float(args.get("timeout", 20))
    max_bytes = 4 * 1024 * 1024
    loop = asyncio.get_running_loop()

    def _do():
        import gzip
        import urllib.request as ur

        h = {"User-Agent": "AkiBrowserHarness/0.1", "Accept-Encoding": "gzip"}
        h.update({str(k): str(v) for k, v in headers.items()})
        req = ur.Request(url, headers=h)
        with ur.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes + 1)
            truncated = len(data) > max_bytes
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    data = gzip.decompress(data[:max_bytes])
                except OSError:
                    pass
            return r.getcode(), data[:max_bytes], truncated

    status, body, truncated = await loop.run_in_executor(None, _do)
    return {"status": status, "body": body.decode("utf-8", errors="replace"), "truncated": truncated}


async def tool_cdp(d: DaemonClient, args: dict) -> dict:
    method = _require(args, "method", str)
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise ToolError("bad_args", "params must be object")
    sid = await _ensure_real_tab(d) if not method.startswith("Target.") else None
    result = await d.cdp(method, params, session_id=sid)
    return {"result": result}


async def tool_run_skill(d: DaemonClient, args: dict) -> dict:
    name = _require(args, "name", str)
    if not SKILL_NAME_RE.match(name):
        raise ToolError("bad_args", f"invalid skill name {name!r}")
    skill_args = args.get("args") or {}
    path = _resolve_skill(d.sess.org_id, d.sess.agent_id, name)
    if path is None:
        raise ToolError("element_not_found", f"skill {name!r} not found")
    code = path.read_text()
    loop = asyncio.get_running_loop()
    ns = _skill_namespace(d, skill_args, loop)
    out = io.StringIO()
    compiled = compile(code, str(path), "exec")

    # Run the exec on a worker thread. The sync wrappers in `ns` use
    # asyncio.run_coroutine_threadsafe back into `loop`, which would
    # deadlock if exec ran on the loop thread itself.
    def _run_skill_blocking():
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            exec(compiled, ns, ns)

    try:
        await loop.run_in_executor(None, _run_skill_blocking)
    except ToolError:
        raise
    except Exception as e:
        tb = traceback.format_exc(limit=4)
        raise ToolError("skill_error", str(e), traceback=tb.splitlines()[-4:])
    return {
        "ok": True,
        "return_value": ns.get("result"),
        "stdout": out.getvalue()[:16384],
    }


async def tool_list_skills(d: DaemonClient, args: dict) -> dict:
    out = []
    for base in (SKILLS_ROOT / d.sess.org_id / d.sess.agent_id, SKILLS_ROOT / SHARED_SKILLS_DIR):
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.py")):
            description = _skill_description(p)
            out.append({"name": p.stem, "path": str(p), "description": description})
    return {"skills": out}


async def tool_session_info(d: DaemonClient, args: dict) -> dict:
    sess = d.sess
    now = time.monotonic()
    return {
        "org_id": sess.org_id,
        "agent_id": sess.agent_id,
        "bu_name": sess.bu_name,
        "started_at_ago_seconds": int(now - sess.started_at),
        "idle_at_ago_seconds": int(now - sess.idle_at),
        "ttl_seconds": sess.ttl_seconds,
        "chrome_pid": sess.chrome_proc.pid,
        "daemon_pid": sess.daemon_proc.pid,
        "cdp_port": sess.cdp_port,
    }


# ---- handler registry --------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "navigate": {
        "description": "Navigate to a URL. Opens a new tab if requested, else uses the current tab. SSRF-blocked URLs (private/metadata IPs) error with code 'ssrf_blocked'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "new_tab": {"type": "boolean", "default": False},
                "wait_for_load": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 15},
            },
            "required": ["url"],
        },
        "handler": tool_navigate,
    },
    "click": {
        "description": "Click at viewport coordinates (x, y). Goes through iframes / shadow DOM via Input.dispatchMouseEvent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number"}, "y": {"type": "number"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "clicks": {"type": "integer", "default": 1},
            },
            "required": ["x", "y"],
        },
        "handler": tool_click,
    },
    "type": {
        "description": "Insert text at the current focus point via Input.insertText.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": tool_type,
    },
    "fill": {
        "description": "Focus a selector, optionally clear, type the text with synthetic input+change events so framework state updates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"}, "text": {"type": "string"},
                "clear_first": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 0},
            },
            "required": ["selector", "text"],
        },
        "handler": tool_fill,
    },
    "press_key": {
        "description": "Dispatch a keyboard event. modifiers is a bitfield: 1=Alt, 2=Ctrl, 4=Meta(Cmd), 8=Shift.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "modifiers": {"type": "integer", "default": 0}},
            "required": ["key"],
        },
        "handler": tool_press_key,
    },
    "scroll": {
        "description": "Dispatch a mouse wheel event at (x, y). Negative dy scrolls down by convention here (matches the upstream helper).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number"}, "y": {"type": "number"},
                "dy": {"type": "number", "default": -300},
                "dx": {"type": "number", "default": 0},
            },
            "required": ["x", "y"],
        },
        "handler": tool_scroll,
    },
    "screenshot": {
        "description": "Capture a PNG of the current viewport (or full page). Returns base64.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "full_page": {"type": "boolean", "default": False},
                "max_dim": {"type": ["integer", "null"], "default": None},
            },
        },
        "handler": tool_screenshot,
    },
    "extract_text": {
        "description": "innerText of a selector (default body), truncated to max_chars.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "default": "body"},
                "max_chars": {"type": "integer", "default": 8000},
            },
        },
        "handler": tool_extract_text,
    },
    "extract_html": {
        "description": "outerHTML of a selector (default html), truncated to max_chars.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "default": "html"},
                "max_chars": {"type": "integer", "default": 64000},
            },
        },
        "handler": tool_extract_html,
    },
    "page_info": {
        "description": "URL/title/viewport/scroll/page size. Returns {dialog: {...}} if a native dialog is open.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_page_info,
    },
    "list_tabs": {
        "description": "List page targets. include_internal=true to see chrome:// pages too.",
        "inputSchema": {
            "type": "object",
            "properties": {"include_internal": {"type": "boolean", "default": False}},
        },
        "handler": tool_list_tabs,
    },
    "switch_tab": {
        "description": "Activate and attach to a target.",
        "inputSchema": {
            "type": "object",
            "properties": {"target_id": {"type": "string"}},
            "required": ["target_id"],
        },
        "handler": tool_switch_tab,
    },
    "new_tab": {
        "description": "Open a new tab and attach; optionally navigate to url.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "default": "about:blank"}},
        },
        "handler": tool_new_tab,
    },
    "close_tab": {
        "description": "Close a tab (defaults to current).",
        "inputSchema": {
            "type": "object",
            "properties": {"target_id": {"type": "string"}},
        },
        "handler": tool_close_tab,
    },
    "wait_for_load": {
        "description": "Poll document.readyState === 'complete' until satisfied or timeout (seconds).",
        "inputSchema": {
            "type": "object",
            "properties": {"timeout": {"type": "number", "default": 15}},
        },
        "handler": tool_wait_for_load,
    },
    "wait_for_element": {
        "description": "Poll querySelector(selector) until it exists (or is visible) or timeout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
                "visible": {"type": "boolean", "default": False},
            },
            "required": ["selector"],
        },
        "handler": tool_wait_for_element,
    },
    "wait_for_network_idle": {
        "description": "Wait until no Network.* events fire for idle_ms ms (or timeout). Useful after form submit or SPA route change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {"type": "number", "default": 10},
                "idle_ms": {"type": "integer", "default": 500},
            },
        },
        "handler": tool_wait_for_network_idle,
    },
    "js": {
        "description": "Eval a JS expression in the active tab. Top-level `return` is auto-wrapped in an IIFE.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "await_promise": {"type": "boolean", "default": True},
            },
            "required": ["expression"],
        },
        "handler": tool_js,
    },
    "upload_file": {
        "description": "Set files on a file input. Paths are resolved against the per-agent profile dir; absolute paths and paths escaping the dir are rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["selector", "paths"],
        },
        "handler": tool_upload_file,
    },
    "http_get": {
        "description": "Pure HTTP fetch (no browser). 4 MiB cap. SSRF-checked. Returns {status, body, truncated}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "headers": {"type": "object"},
                "timeout": {"type": "number", "default": 20},
            },
            "required": ["url"],
        },
        "handler": tool_http_get,
    },
    "cdp": {
        "description": "Raw CDP escape hatch. cdp('DOM.getDocument', {depth: -1}). Browser-scope methods (Target.*) auto-omit the session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["method"],
        },
        "handler": tool_cdp,
    },
    "run_skill": {
        "description": "Exec a .py skill from the per-agent skills dir (or _shared/). Helpers are pre-imported; `result` and stdout are returned.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "args": {"type": "object"},
            },
            "required": ["name"],
        },
        "handler": tool_run_skill,
    },
    "list_skills": {
        "description": "List skills available to this agent (agent-scoped + _shared).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_list_skills,
    },
    "session_info": {
        "description": "Diagnostics for the active session: PIDs, port, age, TTL.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_session_info,
    },
    "release_session": {
        "description": "Persist (default) and tear down the current session. Next call gets a fresh Chromium.",
        "inputSchema": {
            "type": "object",
            "properties": {"persist": {"type": "boolean", "default": True}},
        },
        # release_session needs to run *outside* the session lock — handled
        # in dispatch.
        "handler": None,
    },
}


# ---- low-level helpers -------------------------------------------------------

def _require(args: dict, key: str, typ) -> Any:
    if key not in args:
        raise ToolError("bad_args", f"missing required arg {key!r}")
    val = args[key]
    if not isinstance(val, typ):
        raise ToolError("bad_args", f"{key!r} must be {typ}, got {type(val).__name__}")
    return val


async def _eval(d: DaemonClient, sid: str, expression: str, await_promise: bool = True) -> Any:
    """Runtime.evaluate with the same auto-IIFE-wrap upstream helpers use."""
    if _has_return(expression) and not expression.strip().startswith("("):
        expression = f"(function(){{{expression}}})()"
    r = await d.cdp(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        session_id=sid,
        timeout=30,
    )
    details = r.get("exceptionDetails")
    result = r.get("result", {})
    if details or result.get("subtype") == "error":
        desc = (
            result.get("description")
            or (details and (details.get("exception", {}) or {}).get("description"))
            or (details and details.get("text"))
            or "JavaScript evaluation failed"
        )
        raise ToolError("js_error", desc)
    if "value" in result:
        return result["value"]
    return None


def _has_return(expression: str) -> bool:
    """Cheap detection so `js("return foo()")` works — same logic as upstream
    helpers.py:_has_return_statement, simplified for the most-common cases."""
    if "return" not in expression:
        return False
    # Walk with quote tracking so we don't misfire inside strings
    i, n, state, quote = 0, len(expression), "code", ""
    while i < n:
        ch = expression[i]
        nxt = expression[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch in ("'", '"', "`"):
                state, quote, i = "string", ch, i + 1
                continue
            if ch == "/" and nxt == "/":
                state, i = "line_comment", i + 2
                continue
            if ch == "/" and nxt == "*":
                state, i = "block_comment", i + 2
                continue
            if expression.startswith("return", i):
                before = expression[i - 1] if i > 0 else ""
                after = expression[i + 6] if i + 6 < n else ""
                if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                    return True
            i += 1
            continue
        if state == "line_comment":
            if ch == "\n":
                state = "code"
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state, i = "code", i + 2
                continue
            i += 1
            continue
        if state == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                state, quote = "code", ""
            i += 1
    return False


async def _press_key(d: DaemonClient, sid: str, key: str, mods: int = 0) -> None:
    SPECIAL = {
        "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"),
        "Backspace": (8, "Backspace", ""), "Escape": (27, "Escape", ""),
        "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
        "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
        "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
        "Home": (36, "Home", ""), "End": (35, "End", ""),
        "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
    }
    vk, code, text = SPECIAL.get(
        key, (ord(key[0]) if len(key) == 1 else 0, key, key if len(key) == 1 else "")
    )
    base = {
        "key": key, "code": code, "modifiers": mods,
        "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
    }
    down = {**base, **({"text": text} if text else {})}
    await d.cdp("Input.dispatchKeyEvent", {"type": "keyDown", **down}, session_id=sid)
    if text and len(text) == 1:
        await d.cdp("Input.dispatchKeyEvent", {"type": "char", "text": text, **base}, session_id=sid)
    await d.cdp("Input.dispatchKeyEvent", {"type": "keyUp", **base}, session_id=sid)


async def _wait_for_ready(d: DaemonClient, sid: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = await _eval(d, sid, "document.readyState")
        except ToolError:
            state = ""
        if state == "complete":
            return True
        await asyncio.sleep(0.3)
    return False


async def _poll_js(d: DaemonClient, sid: str, expression: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await _eval(d, sid, expression):
                return True
        except ToolError:
            pass
        await asyncio.sleep(0.3)
    return False


async def _page_info(d: DaemonClient, sid: str) -> dict:
    expr = (
        "JSON.stringify({url:location.href,title:document.title,"
        "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,"
        "pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})"
    )
    raw = await _eval(d, sid, expr)
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


def _resolve_skill(org_id: str, agent_id: str, name: str) -> Optional[Path]:
    for base in (SKILLS_ROOT / org_id / agent_id, SKILLS_ROOT / SHARED_SKILLS_DIR):
        p = base / f"{name}.py"
        if p.is_file():
            return p
    return None


def _skill_description(p: Path) -> Optional[str]:
    """First non-empty line of the docstring, or None."""
    try:
        src = p.read_text()
    except OSError:
        return None
    m = re.search(r'^\s*[ru]?"""(.+?)"""', src, re.S | re.M)
    if not m:
        return None
    for line in m.group(1).splitlines():
        line = line.strip()
        if line:
            return line[:240]
    return None


def _skill_namespace(d: DaemonClient, args: dict, loop: asyncio.AbstractEventLoop) -> dict:
    """Namespace exposed to skills. Helpers are *synchronous wrappers* that
    block on the daemon — skills shouldn't have to know about asyncio.

    `loop` is the event loop running the MCP server; the wrappers schedule
    coroutines on it via run_coroutine_threadsafe. The skill itself must
    execute on a worker thread (see tool_run_skill)."""

    def _sync(coro):
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    ns: dict[str, Any] = {
        "args": args, "result": None,
        "session": d.sess,
        # Browser primitives, sync interface
        "navigate": lambda url, **kw: _sync(tool_navigate(d, {"url": url, **kw})),
        "click": lambda x, y, **kw: _sync(tool_click(d, {"x": x, "y": y, **kw})),
        "type_text": lambda text: _sync(tool_type(d, {"text": text})),
        "fill": lambda selector, text, **kw: _sync(tool_fill(d, {"selector": selector, "text": text, **kw})),
        "press_key": lambda key, modifiers=0: _sync(tool_press_key(d, {"key": key, "modifiers": modifiers})),
        "scroll": lambda x, y, dy=-300, dx=0: _sync(tool_scroll(d, {"x": x, "y": y, "dy": dy, "dx": dx})),
        "screenshot": lambda **kw: _sync(tool_screenshot(d, kw)),
        "extract_text": lambda **kw: _sync(tool_extract_text(d, kw)),
        "page_info": lambda: _sync(tool_page_info(d, {})),
        "js": lambda expression, await_promise=True: _sync(tool_js(d, {"expression": expression, "await_promise": await_promise})),
        "wait_for_load": lambda timeout=15: _sync(tool_wait_for_load(d, {"timeout": timeout})),
        "wait_for_element": lambda selector, **kw: _sync(tool_wait_for_element(d, {"selector": selector, **kw})),
        "wait_for_network_idle": lambda **kw: _sync(tool_wait_for_network_idle(d, kw)),
        "http_get": lambda url, **kw: _sync(tool_http_get(d, {"url": url, **kw})),
        "cdp": lambda method, **params: _sync(tool_cdp(d, {"method": method, "params": params})),
    }
    return ns


# ----- HTTP handlers ----------------------------------------------------------

def _struct_log(level: int, msg: str, **fields) -> None:
    """Single JSON-line structured log."""
    rec = {"ts": time.time(), "msg": msg, **fields}
    log.log(level, json.dumps(rec, default=str))


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def readyz(request: web.Request) -> web.Response:
    pool: BrowserPool = request.app["pool"]
    if pool._reaper_task is None or pool._reaper_task.done():
        return web.json_response({"status": "not_ready"}, status=503)
    return web.json_response({"status": "ok"})


def _check_auth(request: web.Request, expected_key: str) -> tuple[str, str, str]:
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "missing Bearer token"}),
            content_type="application/json",
        )
    token = hdr.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, expected_key):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "invalid token"}),
            content_type="application/json",
        )
    org_id = request.headers.get("X-Aki-Org-Id", "")
    agent_id = request.headers.get("X-Aki-Agent-Id", "")
    if not UUID_RE.match(org_id):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "missing or invalid X-Aki-Org-Id"}),
            content_type="application/json",
        )
    if not UUID_RE.match(agent_id):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "missing or invalid X-Aki-Agent-Id"}),
            content_type="application/json",
        )
    req_id = request.headers.get("X-Aki-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
    return org_id, agent_id, req_id


async def mcp_endpoint(request: web.Request) -> web.Response:
    if request.method != "POST":
        return web.Response(status=405, text="POST only")
    expected_key: str = request.app["api_key"]
    org_id, agent_id, request_id = _check_auth(request, expected_key)

    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        return web.json_response(
            _jrpc_err(None, -32700, f"parse error: {e}"), status=400
        )

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return web.json_response(
            _jrpc_err(body.get("id") if isinstance(body, dict) else None,
                      -32600, "invalid request"), status=400
        )

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    pool: BrowserPool = request.app["pool"]
    start = time.monotonic()

    try:
        if method == "initialize":
            return web.json_response(_jrpc_ok(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }))
        if method == "notifications/initialized":
            # Notifications don't get a response per JSON-RPC spec.
            return web.Response(status=202)
        if method == "tools/list":
            tools = [
                {"name": n, "description": meta["description"], "inputSchema": meta["inputSchema"]}
                for n, meta in TOOLS.items()
            ]
            return web.json_response(_jrpc_ok(req_id, {"tools": tools}))
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in TOOLS:
                return web.json_response(
                    _jrpc_err(req_id, -32601, f"unknown tool {name!r}")
                )
            duration = lambda: int((time.monotonic() - start) * 1000)

            # release_session takes a different path: closes the session
            # *without* holding the session lock (the close is the lock).
            if name == "release_session":
                persist = bool(args.get("persist", True))
                ok = await pool.release(org_id, agent_id, persist=persist)
                _struct_log(
                    logging.INFO, "tool_call",
                    org_id=org_id, agent_id=agent_id, tool=name,
                    duration_ms=duration(), status="ok", request_id=request_id,
                )
                return web.json_response(
                    _jrpc_ok(req_id, _tool_ok(
                        {"ok": True, "persisted": persist and ok},
                        request_id=request_id, duration_ms=duration(),
                    ))
                )

            handler: Callable[[DaemonClient, dict], Awaitable[Any]] = TOOLS[name]["handler"]

            try:
                async with pool.acquire(org_id, agent_id) as sess:
                    d = DaemonClient(sess)
                    value = await handler(d, args)
            except ToolError as te:
                _struct_log(
                    logging.WARNING, "tool_call",
                    org_id=org_id, agent_id=agent_id, tool=name, url=args.get("url"),
                    duration_ms=duration(), status="tool_error", code=te.code,
                    detail=te.detail, request_id=request_id,
                )
                return web.json_response(
                    _jrpc_ok(req_id, _tool_err(
                        te.code, te.detail, request_id=request_id,
                        duration_ms=duration(), **te.extra,
                    ))
                )
            except asyncio.TimeoutError:
                _struct_log(
                    logging.WARNING, "tool_call",
                    org_id=org_id, agent_id=agent_id, tool=name,
                    duration_ms=duration(), status="timeout", request_id=request_id,
                )
                return web.json_response(
                    _jrpc_ok(req_id, _tool_err(
                        "timeout", f"{name} exceeded internal timeout",
                        request_id=request_id, duration_ms=duration(),
                    ))
                )
            except Exception as e:
                tb = traceback.format_exc(limit=4)
                _struct_log(
                    logging.ERROR, "tool_call",
                    org_id=org_id, agent_id=agent_id, tool=name,
                    duration_ms=duration(), status="internal_error", error=str(e),
                    traceback=tb.splitlines()[-3:], request_id=request_id,
                )
                return web.json_response(
                    _jrpc_ok(req_id, _tool_err(
                        "internal_error", str(e),
                        request_id=request_id, duration_ms=duration(),
                    ))
                )

            _struct_log(
                logging.INFO, "tool_call",
                org_id=org_id, agent_id=agent_id, tool=name, url=args.get("url"),
                duration_ms=duration(), status="ok", request_id=request_id,
            )
            return web.json_response(
                _jrpc_ok(req_id, _tool_ok(
                    value, request_id=request_id, duration_ms=duration(),
                ))
            )

        return web.json_response(_jrpc_err(req_id, -32601, f"unknown method {method!r}"))
    except web.HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc(limit=4)
        _struct_log(
            logging.ERROR, "mcp_error",
            org_id=org_id, agent_id=agent_id, method=method,
            error=str(e), traceback=tb.splitlines()[-3:], request_id=request_id,
        )
        return web.json_response(_jrpc_err(req_id, -32603, "internal error", str(e)))


# ----- App factory ------------------------------------------------------------

async def _on_startup(app: web.Application) -> None:
    await app["pool"].start()


async def _on_cleanup(app: web.Application) -> None:
    await app["pool"].stop()


def make_app() -> web.Application:
    api_key = os.environ.get("BROWSER_HARNESS_API_KEY")
    if not api_key:
        raise SystemExit(
            "BROWSER_HARNESS_API_KEY env var is required (shared secret with the API gateway)"
        )

    storage = ProfileStorage.from_env()
    pool = BrowserPool(storage)

    app = web.Application(client_max_size=8 * 1024 * 1024)  # 8 MiB request cap
    app["pool"] = pool
    app["api_key"] = api_key
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", readyz)
    app.router.add_post("/mcp", mcp_endpoint)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(message)s",  # struct_log already emits JSON
        stream=sys.stdout,
    )
    port = int(os.environ.get("PORT", "7900"))
    host = os.environ.get("HOST", "0.0.0.0")
    web.run_app(make_app(), host=host, port=port, access_log=None)


if __name__ == "__main__":
    main()
