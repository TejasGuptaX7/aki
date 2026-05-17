"""aiohttp MCP server for the v2 proxy layer.

Wire-compatible with v1 (see PROTOCOL_v2.md §5) plus three v2-only
tools (switch_platform, list_platforms, release_platform). Inside, every
tool call routes through pool.acquire(org, agent, route) which decides
Steel vs Browserbase based on the URL or the X-Aki-Platform header and
drives the chosen vendor over raw CDP.
"""
from __future__ import annotations

import asyncio
import base64
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
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from aiohttp import web

from browserbase_adapter import BrowserbaseAdapter
from cdp import CDPError
from pool import BrowserPoolV2, Session, VendorError
from profile_store import ProfileStore
from router import Route, route_for_platform, route_for_url
from steel_adapter import SteelAdapter

PROTOCOL_VERSION = "2025-03-26"
SERVER_VERSION = "2.0.0"
SERVER_NAME = "aki-browser-harness-proxy"

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PLATFORM_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

DEFAULT_ALLOWED_HOSTS = tuple(
    h.strip().lower()
    for h in os.environ.get("BROWSER_HARNESS_ALLOWED_HOSTS", "").split(",")
    if h.strip()
)

CAPTCHA_NEEDLES = (
    "verify you are human", "are you a robot", "checking your browser",
    "cloudflare to access", "captcha", "hcaptcha", "recaptcha",
    "please confirm you are not a robot",
)

log = logging.getLogger("browser-harness-v2")


# ----- JSON-RPC helpers (same shapes as v1) ----------------------------------

def _jrpc_ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jrpc_err(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _tool_ok(value: Any, *, request_id: str, duration_ms: int, platform: Optional[str] = None) -> dict:
    meta = {"request_id": request_id, "duration_ms": duration_ms}
    if platform:
        meta["platform"] = platform
    return {
        "content": [{"type": "text", "text": json.dumps(value, default=str)}],
        "isError": False,
        "_meta": meta,
    }


def _tool_err(code: str, detail: str, *, request_id: str, duration_ms: int, **extra) -> dict:
    payload = {"code": code, "detail": detail, **extra}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "isError": True,
        "_meta": {"request_id": request_id, "duration_ms": duration_ms},
    }


class ToolError(Exception):
    def __init__(self, code: str, detail: str, **extra):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.extra = extra


def _struct_log(level: int, msg: str, **fields) -> None:
    rec = {"ts": time.time(), "msg": msg, **fields}
    log.log(level, json.dumps(rec, default=str))


# ----- SSRF + captcha (same as v1) -------------------------------------------

def _check_url(url: str) -> None:
    try:
        parsed = urlparse(url)
    except Exception:
        raise ToolError("bad_args", f"unparseable URL: {url!r}")
    if parsed.scheme not in ("http", "https"):
        raise ToolError("bad_args", f"only http/https allowed, got {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ToolError("bad_args", "URL has no host")
    if any(fnmatch.fnmatch(host, pat) for pat in DEFAULT_ALLOWED_HOSTS):
        return
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


def _is_blocked_ip(ip) -> bool:
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return True
    return any([
        ip.is_private, ip.is_loopback, ip.is_link_local,
        ip.is_multicast, ip.is_unspecified, ip.is_reserved,
    ])


async def _captcha_check(sess: Session) -> None:
    try:
        title = (await sess.cdp.send(
            "Runtime.evaluate",
            {"expression": "document.title", "returnByValue": True},
            session_id=sess.cdp_session_id, timeout=5,
        )).get("result", {}).get("value", "")
        body = (await sess.cdp.send(
            "Runtime.evaluate",
            {"expression": "(document.body && document.body.innerText || '').slice(0, 4000)",
             "returnByValue": True},
            session_id=sess.cdp_session_id, timeout=5,
        )).get("result", {}).get("value", "")
    except Exception:
        return
    hay = f"{title}\n{body}".lower()
    for needle in CAPTCHA_NEEDLES:
        if needle in hay:
            raise ToolError("captcha_required", f"page text contained {needle!r}", title=title)


# ----- Tool implementations --------------------------------------------------

async def _eval(sess: Session, expression: str, await_promise: bool = True) -> Any:
    if _has_return(expression) and not expression.strip().startswith("("):
        expression = f"(function(){{{expression}}})()"
    r = await sess.cdp.send(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        session_id=sess.cdp_session_id, timeout=30,
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
    return result.get("value")


def _has_return(expression: str) -> bool:
    """Same auto-IIFE-wrap heuristic as v1 server.py:_has_return."""
    if "return" not in expression:
        return False
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


async def _wait_ready(sess: Session, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = await _eval(sess, "document.readyState")
        except ToolError:
            state = ""
        if state == "complete":
            return True
        await asyncio.sleep(0.3)
    return False


async def _poll_js(sess: Session, expression: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await _eval(sess, expression):
                return True
        except ToolError:
            pass
        await asyncio.sleep(0.3)
    return False


async def _page_info(sess: Session) -> dict:
    raw = await _eval(
        sess,
        "JSON.stringify({url:location.href,title:document.title,"
        "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,"
        "pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})",
    )
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


# ---- per-tool handlers (route is preselected by dispatch) -------------------

async def tool_navigate(sess: Session, args: dict) -> dict:
    url = args.get("url")
    if not isinstance(url, str):
        raise ToolError("bad_args", "url must be string")
    _check_url(url)
    wait = bool(args.get("wait_for_load", True))
    timeout = float(args.get("timeout", 15))
    nav = await sess.cdp.send(
        "Page.navigate", {"url": url}, session_id=sess.cdp_session_id, timeout=20,
    )
    if nav.get("errorText"):
        raise ToolError("navigation_failed", nav["errorText"], url=url)
    if wait:
        await _wait_ready(sess, timeout)
    await _captcha_check(sess)
    info = await _page_info(sess)
    return {"ok": True, "url": info.get("url"), "title": info.get("title")}


async def tool_click(sess: Session, args: dict) -> dict:
    x = float(args.get("x", -1)); y = float(args.get("y", -1))
    if x < 0 or y < 0:
        raise ToolError("bad_args", "x, y required (non-negative numbers)")
    button = args.get("button", "left")
    clicks = int(args.get("clicks", 1))
    for ev in ("mousePressed", "mouseReleased"):
        await sess.cdp.send(
            "Input.dispatchMouseEvent",
            {"type": ev, "x": x, "y": y, "button": button, "clickCount": clicks},
            session_id=sess.cdp_session_id,
        )
    return {"ok": True}


async def tool_type(sess: Session, args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str):
        raise ToolError("bad_args", "text required")
    await sess.cdp.send(
        "Input.insertText", {"text": text}, session_id=sess.cdp_session_id,
    )
    return {"ok": True}


async def tool_fill(sess: Session, args: dict) -> dict:
    selector = args.get("selector")
    text = args.get("text")
    if not isinstance(selector, str) or not isinstance(text, str):
        raise ToolError("bad_args", "selector + text required")
    timeout = float(args.get("timeout", 0))
    clear_first = bool(args.get("clear_first", True))
    if timeout > 0:
        if not await _poll_js(sess, f"!!document.querySelector({json.dumps(selector)})", timeout):
            raise ToolError("element_not_found", selector)
    focused = await _eval(
        sess,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return false;e.focus();return true;}})()",
    )
    if not focused:
        raise ToolError("element_not_found", selector)
    if clear_first:
        await _eval(
            sess,
            f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
            f"if(e&&'value' in e)e.value='';}})()",
        )
    for ch in text:
        await sess.cdp.send(
            "Input.insertText", {"text": ch}, session_id=sess.cdp_session_id,
        )
    await _eval(
        sess,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return;e.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"e.dispatchEvent(new Event('change',{{bubbles:true}}));}})();",
    )
    return {"ok": True}


async def tool_press_key(sess: Session, args: dict) -> dict:
    key = args.get("key")
    if not isinstance(key, str):
        raise ToolError("bad_args", "key required")
    mods = int(args.get("modifiers", 0))
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
    base = {"key": key, "code": code, "modifiers": mods,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    down = {**base, **({"text": text} if text else {})}
    await sess.cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", **down},
                        session_id=sess.cdp_session_id)
    if text and len(text) == 1:
        await sess.cdp.send("Input.dispatchKeyEvent", {"type": "char", "text": text, **base},
                            session_id=sess.cdp_session_id)
    await sess.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **base},
                        session_id=sess.cdp_session_id)
    return {"ok": True}


async def tool_scroll(sess: Session, args: dict) -> dict:
    x = float(args.get("x", 0)); y = float(args.get("y", 0))
    dx = float(args.get("dx", 0)); dy = float(args.get("dy", -300))
    await sess.cdp.send(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy},
        session_id=sess.cdp_session_id,
    )
    return {"ok": True}


async def tool_screenshot(sess: Session, args: dict) -> dict:
    full = bool(args.get("full_page", False))
    max_dim = args.get("max_dim")
    r = await sess.cdp.send(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": full},
        session_id=sess.cdp_session_id, timeout=30,
    )
    b64 = r.get("data", "")
    if max_dim:
        try:
            from PIL import Image
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            if max(img.size) > int(max_dim):
                img.thumbnail((int(max_dim), int(max_dim)))
                out = io.BytesIO()
                img.save(out, format="PNG")
                b64 = base64.b64encode(out.getvalue()).decode("ascii")
        except ImportError:
            pass
    return {"mime": "image/png", "base64": b64}


async def tool_extract_text(sess: Session, args: dict) -> dict:
    selector = str(args.get("selector", "body"))
    max_chars = int(args.get("max_chars", 8000))
    val = await _eval(
        sess,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return null;return (e.innerText||e.textContent||'').slice(0,{max_chars + 1});}})()",
    )
    if val is None:
        raise ToolError("element_not_found", selector)
    return {"text": val[:max_chars], "truncated": len(val) > max_chars}


async def tool_extract_html(sess: Session, args: dict) -> dict:
    selector = str(args.get("selector", "html"))
    max_chars = int(args.get("max_chars", 64000))
    val = await _eval(
        sess,
        f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
        f"if(!e)return null;return e.outerHTML.slice(0,{max_chars + 1});}})()",
    )
    if val is None:
        raise ToolError("element_not_found", selector)
    return {"html": val[:max_chars], "truncated": len(val) > max_chars}


async def tool_page_info(sess: Session, args: dict) -> dict:
    return await _page_info(sess)


async def tool_list_tabs(sess: Session, args: dict) -> dict:
    include_internal = bool(args.get("include_internal", False))
    targets = (await sess.cdp.send("Target.getTargets")).get("targetInfos", [])
    tabs = []
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url", "")
        if not include_internal and url.startswith(
            ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")
        ):
            continue
        tabs.append({"targetId": t["targetId"], "title": t.get("title", ""), "url": url})
    return {"tabs": tabs}


async def tool_new_tab(sess: Session, args: dict) -> dict:
    url = str(args.get("url", "about:blank"))
    if url != "about:blank":
        _check_url(url)
    tid = (await sess.cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
    sid = (await sess.cdp.send(
        "Target.attachToTarget", {"targetId": tid, "flatten": True}
    ))["sessionId"]
    # Switch the session's bound page to the new tab and re-enable domains
    sess.cdp_session_id = sid
    await asyncio.gather(
        sess.cdp.send("Page.enable", session_id=sid),
        sess.cdp.send("Runtime.enable", session_id=sid),
        sess.cdp.send("DOM.enable", session_id=sid),
        sess.cdp.send("Network.enable", session_id=sid),
        return_exceptions=True,
    )
    if url != "about:blank":
        nav = await sess.cdp.send("Page.navigate", {"url": url}, session_id=sid)
        if nav.get("errorText"):
            raise ToolError("navigation_failed", nav["errorText"], url=url)
    return {"target_id": tid, "url": url}


async def tool_switch_tab(sess: Session, args: dict) -> dict:
    tid = args.get("target_id")
    if not isinstance(tid, str):
        raise ToolError("bad_args", "target_id required")
    await sess.cdp.send("Target.activateTarget", {"targetId": tid})
    sid = (await sess.cdp.send(
        "Target.attachToTarget", {"targetId": tid, "flatten": True}
    ))["sessionId"]
    sess.cdp_session_id = sid
    return {"ok": True, "session_id": sid}


async def tool_close_tab(sess: Session, args: dict) -> dict:
    tid = args.get("target_id")
    if not tid:
        # Close current — find via Target.getTargetInfo on the attached session
        info = await sess.cdp.send(
            "Target.getTargetInfo", session_id=sess.cdp_session_id,
        )
        tid = (info.get("targetInfo") or {}).get("targetId")
    if not tid:
        raise ToolError("not_attached", "no current tab to close")
    await sess.cdp.send("Target.closeTarget", {"targetId": tid})
    return {"ok": True}


async def tool_wait_for_load(sess: Session, args: dict) -> dict:
    timeout = float(args.get("timeout", 15))
    return {"loaded": await _wait_ready(sess, timeout)}


async def tool_wait_for_element(sess: Session, args: dict) -> dict:
    selector = args.get("selector")
    if not isinstance(selector, str):
        raise ToolError("bad_args", "selector required")
    timeout = float(args.get("timeout", 10))
    visible = bool(args.get("visible", False))
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
    return {"found": await _poll_js(sess, check, timeout)}


async def tool_js(sess: Session, args: dict) -> dict:
    expression = args.get("expression")
    if not isinstance(expression, str):
        raise ToolError("bad_args", "expression required")
    await_promise = bool(args.get("await_promise", True))
    return {"value": await _eval(sess, expression, await_promise=await_promise)}


async def tool_cdp(sess: Session, args: dict) -> dict:
    method = args.get("method")
    if not isinstance(method, str):
        raise ToolError("bad_args", "method required")
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise ToolError("bad_args", "params must be object")
    # Target.* runs at the browser scope (no sessionId); everything else
    # goes through the attached page session.
    sid = None if method.startswith("Target.") else sess.cdp_session_id
    return {"result": await sess.cdp.send(method, params, session_id=sid)}


async def tool_session_info(sess: Session, args: dict) -> dict:
    now = time.monotonic()
    return {
        "org_id": sess.org_id, "agent_id": sess.agent_id,
        "platform": sess.platform, "backend": sess.backend,
        "vendor_session_id": sess.vendor_session_id,
        "cdp_session_id": sess.cdp_session_id,
        "started_at_ago_seconds": int(now - sess.started_at),
        "idle_at_ago_seconds": int(now - sess.idle_at),
    }


# ---- v1 tools that v2 doesn't implement yet (return not_implemented_in_v2) --

async def tool_not_implemented(sess: Session, args: dict) -> dict:
    raise ToolError(
        "not_implemented_in_v2",
        "this tool was in v1 but is stubbed in v2.0.0; will land in v2.1",
    )


# ---- per-(org, agent) tools (no Session arg) --------------------------------

async def tool_release_session(pool: BrowserPoolV2, org_id: str, agent_id: str, args: dict) -> dict:
    """Releases ALL platform sessions for the (org, agent). Wire-compatible
    with v1's release_session, which had no concept of platforms."""
    persist = bool(args.get("persist", True))
    released = 0
    for sess in pool.active_platforms(org_id, agent_id):
        if await pool.release_platform(org_id, agent_id, sess.platform, persist=persist):
            released += 1
    return {"ok": True, "persisted": persist, "released_count": released}


async def tool_release_platform(pool: BrowserPoolV2, org_id: str, agent_id: str, args: dict) -> dict:
    platform = args.get("platform")
    if not isinstance(platform, str) or not PLATFORM_RE.match(platform):
        raise ToolError("bad_args", "platform name required")
    persist = bool(args.get("persist", True))
    ok = await pool.release_platform(org_id, agent_id, platform, persist=persist)
    return {"ok": True, "released": ok, "persisted": persist}


async def tool_list_platforms(pool: BrowserPoolV2, org_id: str, agent_id: str, args: dict) -> dict:
    now = time.monotonic()
    bound = pool.current_platform(org_id, agent_id)
    return {
        "platforms": [
            {
                "platform": s.platform, "backend": s.backend,
                "vendor_session_id": s.vendor_session_id,
                "started_at_ago_seconds": int(now - s.started_at),
                "idle_at_ago_seconds": int(now - s.idle_at),
                "bound": s.platform == bound,
            }
            for s in pool.active_platforms(org_id, agent_id)
        ],
        "current_platform": bound,
    }


async def tool_switch_platform(pool: BrowserPoolV2, org_id: str, agent_id: str, args: dict) -> dict:
    platform = args.get("platform")
    if not isinstance(platform, str) or not PLATFORM_RE.match(platform):
        raise ToolError("bad_args", "platform name required")
    route = route_for_platform(platform)
    async with pool.acquire(org_id, agent_id, route) as sess:
        return {
            "ok": True, "platform": route.platform, "backend": route.backend,
            "session_id": sess.cdp_session_id,
        }


# ---- tool registry ----------------------------------------------------------

# Tools that take a Session — dispatched inside a pool.acquire() block.
SESSION_TOOLS: dict[str, dict[str, Any]] = {
    "navigate": {"handler": tool_navigate, "description": "Navigate to a URL. SSRF-blocked URLs error with 'ssrf_blocked'.", "inputSchema": {"type":"object","properties":{"url":{"type":"string"},"wait_for_load":{"type":"boolean","default":True},"timeout":{"type":"number","default":15}},"required":["url"]}},
    "click": {"handler": tool_click, "description": "Click at viewport (x, y).", "inputSchema": {"type":"object","properties":{"x":{"type":"number"},"y":{"type":"number"},"button":{"type":"string","default":"left"},"clicks":{"type":"integer","default":1}},"required":["x","y"]}},
    "type": {"handler": tool_type, "description": "Insert text at the focused element.", "inputSchema": {"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}},
    "fill": {"handler": tool_fill, "description": "Focus selector, optionally clear, type with input+change events.", "inputSchema": {"type":"object","properties":{"selector":{"type":"string"},"text":{"type":"string"},"clear_first":{"type":"boolean","default":True},"timeout":{"type":"number","default":0}},"required":["selector","text"]}},
    "press_key": {"handler": tool_press_key, "description": "Dispatch a keyboard event. modifiers: 1=Alt,2=Ctrl,4=Meta,8=Shift.", "inputSchema": {"type":"object","properties":{"key":{"type":"string"},"modifiers":{"type":"integer","default":0}},"required":["key"]}},
    "scroll": {"handler": tool_scroll, "description": "Mouse wheel scroll at (x, y).", "inputSchema": {"type":"object","properties":{"x":{"type":"number"},"y":{"type":"number"},"dy":{"type":"number","default":-300},"dx":{"type":"number","default":0}},"required":["x","y"]}},
    "screenshot": {"handler": tool_screenshot, "description": "Capture PNG (base64).", "inputSchema": {"type":"object","properties":{"full_page":{"type":"boolean","default":False},"max_dim":{"type":["integer","null"],"default":None}}}},
    "extract_text": {"handler": tool_extract_text, "description": "innerText of selector (default body).", "inputSchema": {"type":"object","properties":{"selector":{"type":"string","default":"body"},"max_chars":{"type":"integer","default":8000}}}},
    "extract_html": {"handler": tool_extract_html, "description": "outerHTML of selector (default html).", "inputSchema": {"type":"object","properties":{"selector":{"type":"string","default":"html"},"max_chars":{"type":"integer","default":64000}}}},
    "page_info": {"handler": tool_page_info, "description": "URL/title/viewport/scroll.", "inputSchema": {"type":"object","properties":{}}},
    "list_tabs": {"handler": tool_list_tabs, "description": "List page targets.", "inputSchema": {"type":"object","properties":{"include_internal":{"type":"boolean","default":False}}}},
    "new_tab": {"handler": tool_new_tab, "description": "Open + attach to a new tab.", "inputSchema": {"type":"object","properties":{"url":{"type":"string","default":"about:blank"}}}},
    "switch_tab": {"handler": tool_switch_tab, "description": "Activate + attach to a target.", "inputSchema": {"type":"object","properties":{"target_id":{"type":"string"}},"required":["target_id"]}},
    "close_tab": {"handler": tool_close_tab, "description": "Close current or named tab.", "inputSchema": {"type":"object","properties":{"target_id":{"type":"string"}}}},
    "wait_for_load": {"handler": tool_wait_for_load, "description": "Poll readyState='complete'.", "inputSchema": {"type":"object","properties":{"timeout":{"type":"number","default":15}}}},
    "wait_for_element": {"handler": tool_wait_for_element, "description": "Poll querySelector(selector) until present (or visible).", "inputSchema": {"type":"object","properties":{"selector":{"type":"string"},"timeout":{"type":"number","default":10},"visible":{"type":"boolean","default":False}},"required":["selector"]}},
    "js": {"handler": tool_js, "description": "Eval JS in the attached tab. Top-level `return` auto-wrapped.", "inputSchema": {"type":"object","properties":{"expression":{"type":"string"},"await_promise":{"type":"boolean","default":True}},"required":["expression"]}},
    "cdp": {"handler": tool_cdp, "description": "Raw CDP escape hatch.", "inputSchema": {"type":"object","properties":{"method":{"type":"string"},"params":{"type":"object"}},"required":["method"]}},
    "session_info": {"handler": tool_session_info, "description": "Diagnostics for the active (org,agent,platform) session.", "inputSchema": {"type":"object","properties":{}}},
    # not-implemented stubs for v1 wire compat
    "wait_for_network_idle": {"handler": tool_not_implemented, "description": "[v2 stub] not implemented in v2.0.0", "inputSchema": {"type":"object"}},
    "upload_file": {"handler": tool_not_implemented, "description": "[v2 stub] not implemented in v2.0.0", "inputSchema": {"type":"object"}},
    "http_get": {"handler": tool_not_implemented, "description": "[v2 stub] not implemented in v2.0.0", "inputSchema": {"type":"object"}},
    "run_skill": {"handler": tool_not_implemented, "description": "[v2 stub] not implemented in v2.0.0", "inputSchema": {"type":"object"}},
    "list_skills": {"handler": tool_not_implemented, "description": "[v2 stub] not implemented in v2.0.0", "inputSchema": {"type":"object"}},
}

# Pool-level tools — no Session arg; routed outside acquire().
POOL_TOOLS: dict[str, dict[str, Any]] = {
    "release_session": {"handler": tool_release_session, "description": "Release every active platform session for this (org,agent).", "inputSchema": {"type":"object","properties":{"persist":{"type":"boolean","default":True}}}},
    "release_platform": {"handler": tool_release_platform, "description": "Release one platform's session.", "inputSchema": {"type":"object","properties":{"platform":{"type":"string"},"persist":{"type":"boolean","default":True}},"required":["platform"]}},
    "list_platforms": {"handler": tool_list_platforms, "description": "List active (platform, backend, age) pairs for this (org,agent).", "inputSchema": {"type":"object","properties":{}}},
    "switch_platform": {"handler": tool_switch_platform, "description": "Explicitly bind a platform; subsequent toolless-URL calls route there.", "inputSchema": {"type":"object","properties":{"platform":{"type":"string"}},"required":["platform"]}},
}


# ----- HTTP handlers ---------------------------------------------------------

def _check_auth(request: web.Request, expected_key: str) -> tuple[str, str, Optional[str], str]:
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
            body=json.dumps({"error": "unauthorized", "detail": "missing/invalid X-Aki-Org-Id"}),
            content_type="application/json",
        )
    if not UUID_RE.match(agent_id):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "missing/invalid X-Aki-Agent-Id"}),
            content_type="application/json",
        )
    platform = request.headers.get("X-Aki-Platform")
    if platform and not PLATFORM_RE.match(platform):
        raise web.HTTPUnauthorized(
            body=json.dumps({"error": "unauthorized", "detail": "invalid X-Aki-Platform"}),
            content_type="application/json",
        )
    req_id = request.headers.get("X-Aki-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
    return org_id, agent_id, platform, req_id


def _pick_route(
    pool: BrowserPoolV2, org_id: str, agent_id: str,
    explicit_platform: Optional[str], args: dict,
) -> Route:
    """Decide which (platform, backend) to bind for this call. See
    PROTOCOL_v2.md §3 for the precedence order."""
    if explicit_platform:
        return route_for_platform(explicit_platform)
    url = args.get("url") if isinstance(args, dict) else None
    if isinstance(url, str):
        return route_for_url(url)
    cur = pool.current_platform(org_id, agent_id)
    if cur:
        return route_for_platform(cur)
    return None  # signals "no_active_platform"


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def readyz(request: web.Request) -> web.Response:
    pool: BrowserPoolV2 = request.app["pool"]
    if pool._reaper_task is None or pool._reaper_task.done():
        return web.json_response({"status": "not_ready"}, status=503)
    return web.json_response({"status": "ok"})


async def debug_platforms(request: web.Request) -> web.Response:
    """Auth-gated dump of routing state. For the founder, not the agent."""
    expected_key: str = request.app["api_key"]
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer ") or not hmac.compare_digest(
        hdr.split(" ", 1)[1].strip(), expected_key
    ):
        raise web.HTTPUnauthorized()
    pool: BrowserPoolV2 = request.app["pool"]
    return web.json_response({
        "active_sessions": [
            {
                "org_id": s.org_id, "agent_id": s.agent_id,
                "platform": s.platform, "backend": s.backend,
                "vendor_session_id": s.vendor_session_id,
            }
            for s in pool._sessions.values() if not s.closed
        ],
        "current_platform": {
            f"{k[0]}:{k[1]}": v for k, v in pool._current_platform.items()
        },
    })


async def mcp_endpoint(request: web.Request) -> web.Response:
    expected_key: str = request.app["api_key"]
    org_id, agent_id, explicit_platform, request_id = _check_auth(request, expected_key)

    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        return web.json_response(_jrpc_err(None, -32700, f"parse error: {e}"), status=400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return web.json_response(
            _jrpc_err(body.get("id") if isinstance(body, dict) else None,
                      -32600, "invalid request"), status=400,
        )

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}
    pool: BrowserPoolV2 = request.app["pool"]
    start = time.monotonic()

    def _ms() -> int:
        return int((time.monotonic() - start) * 1000)

    try:
        if method == "initialize":
            return web.json_response(_jrpc_ok(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }))
        if method == "notifications/initialized":
            return web.Response(status=202)
        if method == "tools/list":
            tools = []
            for n, meta in {**SESSION_TOOLS, **POOL_TOOLS}.items():
                tools.append({
                    "name": n, "description": meta["description"],
                    "inputSchema": meta["inputSchema"],
                })
            return web.json_response(_jrpc_ok(req_id, {"tools": tools}))
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name in POOL_TOOLS:
                try:
                    value = await POOL_TOOLS[name]["handler"](pool, org_id, agent_id, args)
                except ToolError as te:
                    _struct_log(logging.WARNING, "tool_call",
                                org_id=org_id, agent_id=agent_id, tool=name,
                                duration_ms=_ms(), status="tool_error", code=te.code,
                                detail=te.detail, request_id=request_id)
                    return web.json_response(_jrpc_ok(req_id, _tool_err(
                        te.code, te.detail, request_id=request_id, duration_ms=_ms(), **te.extra,
                    )))
                _struct_log(logging.INFO, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            duration_ms=_ms(), status="ok", request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_ok(
                    value, request_id=request_id, duration_ms=_ms(),
                )))

            if name not in SESSION_TOOLS:
                return web.json_response(_jrpc_err(req_id, -32601, f"unknown tool {name!r}"))

            route = _pick_route(pool, org_id, agent_id, explicit_platform, args)
            if route is None:
                _struct_log(logging.WARNING, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            duration_ms=_ms(), status="tool_error",
                            code="no_active_platform", request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    "no_active_platform",
                    "no platform bound — call navigate(url=…) or switch_platform first",
                    request_id=request_id, duration_ms=_ms(),
                )))

            handler: Callable[[Session, dict], Awaitable[Any]] = SESSION_TOOLS[name]["handler"]
            try:
                async with pool.acquire(org_id, agent_id, route) as sess:
                    value = await handler(sess, args)
            except ToolError as te:
                _struct_log(logging.WARNING, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            platform=route.platform, backend=route.backend,
                            duration_ms=_ms(), status="tool_error", code=te.code,
                            detail=te.detail, url=args.get("url"), request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    te.code, te.detail, request_id=request_id, duration_ms=_ms(), **te.extra,
                )))
            except VendorError as ve:
                code = "vendor_quota_exhausted" if ve.status in (402, 429) else "vendor_unavailable"
                _struct_log(logging.ERROR, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            platform=route.platform, backend=route.backend,
                            duration_ms=_ms(), status="vendor_error",
                            code=code, detail=str(ve), request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    code, str(ve), vendor=ve.vendor,
                    request_id=request_id, duration_ms=_ms(),
                )))
            except CDPError as ce:
                _struct_log(logging.ERROR, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            platform=route.platform, backend=route.backend,
                            duration_ms=_ms(), status="cdp_error",
                            detail=str(ce), request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    "internal_error", f"CDP failure: {ce}",
                    request_id=request_id, duration_ms=_ms(),
                )))
            except asyncio.TimeoutError:
                _struct_log(logging.WARNING, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            duration_ms=_ms(), status="timeout", request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    "timeout", f"{name} exceeded internal timeout",
                    request_id=request_id, duration_ms=_ms(),
                )))
            except Exception as e:
                tb = traceback.format_exc(limit=4)
                _struct_log(logging.ERROR, "tool_call",
                            org_id=org_id, agent_id=agent_id, tool=name,
                            duration_ms=_ms(), status="internal_error", error=str(e),
                            traceback=tb.splitlines()[-3:], request_id=request_id)
                return web.json_response(_jrpc_ok(req_id, _tool_err(
                    "internal_error", str(e),
                    request_id=request_id, duration_ms=_ms(),
                )))

            _struct_log(logging.INFO, "tool_call",
                        org_id=org_id, agent_id=agent_id, tool=name,
                        platform=route.platform, backend=route.backend,
                        duration_ms=_ms(), status="ok", url=args.get("url"),
                        request_id=request_id)
            return web.json_response(_jrpc_ok(req_id, _tool_ok(
                value, request_id=request_id, duration_ms=_ms(), platform=route.platform,
            )))

        return web.json_response(_jrpc_err(req_id, -32601, f"unknown method {method!r}"))
    except web.HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc(limit=4)
        _struct_log(logging.ERROR, "mcp_error",
                    org_id=org_id, agent_id=agent_id, method=method,
                    error=str(e), traceback=tb.splitlines()[-3:], request_id=request_id)
        return web.json_response(_jrpc_err(req_id, -32603, "internal error", str(e)))


# ----- App factory -----------------------------------------------------------

async def _on_startup(app: web.Application) -> None:
    await app["pool"].start()


async def _on_cleanup(app: web.Application) -> None:
    await app["pool"].stop()


def make_app() -> web.Application:
    api_key = os.environ.get("BROWSER_HARNESS_API_KEY")
    if not api_key:
        raise SystemExit("BROWSER_HARNESS_API_KEY env var is required")
    store = ProfileStore.from_env()
    steel = SteelAdapter()
    bb = BrowserbaseAdapter()
    pool = BrowserPoolV2(store, steel, bb)
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app["pool"] = pool
    app["api_key"] = api_key
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", readyz)
    app.router.add_get("/debug/platforms", debug_platforms)
    app.router.add_post("/mcp", mcp_endpoint)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(message)s", stream=sys.stdout,
    )
    port = int(os.environ.get("PORT", "7901"))
    host = os.environ.get("HOST", "0.0.0.0")
    web.run_app(make_app(), host=host, port=port, access_log=None)


if __name__ == "__main__":
    main()
