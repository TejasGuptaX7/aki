"""Shared defensive helpers for autonomous signup skills.

NOT a standalone skill — has no top-level imperative code and assigns no
`result`. The 8 signup skills source it via `exec(open(...).read(), globals())`
at their top so they share the cookie-banner / captcha / verification
patterns without copy-paste.

Why a shared file instead of an MCP tool: skills are meant to be agent-edited
on the fly per the upstream model (see SKILL.md in the upstream repo). Pulling
the boring scaffolding out keeps each skill's diff readable when an agent
edits a selector that's rotted.
"""

# Cookie / privacy banner buttons that show up on roughly half the modern
# SaaS landing pages. Listed roughly in priority order — the first one that
# matches gets clicked. The selectors are CSS so we can chain via querySelector
# without playwright-style "role" matching.
#
# Each entry is (selector, label-regex). The JS below clicks any matching
# button whose visible text matches the regex (case-insensitive). This is
# stricter than selector-only because some sites use the same selector for
# Accept and Reject — we always want Accept (less friction, account creation
# usually still works with rejected cookies but flow is bumpier).
COOKIE_ACCEPT_PATTERNS = [
    ("#onetrust-accept-btn-handler", r"accept"),
    ("[data-testid='uc-accept-all-button']", r"accept"),
    ("#truste-consent-button", r"agree|accept"),
    ("[aria-label='Accept all']", r"accept"),
    ("[aria-label='Accept All']", r"accept"),
    ("button.cky-btn-accept", r"accept"),
    ("button#hs-eu-confirmation-button", r"accept|confirm"),
    # Generic last-resort patterns
    ("button", r"^accept(\sall)?(\scookies)?$"),
    ("button", r"^i\sagree$"),
    ("button", r"^got it$"),
]


def dismiss_cookie_banner(_timeout=3.0):
    """Best-effort: click an Accept button if one appears within `_timeout` s.
    Returns True if a banner was dismissed, False otherwise. Never raises.

    The 8 skills call this after `navigate` + `wait_for_load`. Skipping is
    fine — most sites still let you proceed with the banner open."""
    import time
    deadline = time.time() + _timeout
    while time.time() < deadline:
        for selector, label_re in COOKIE_ACCEPT_PATTERNS:
            clicked = js(f"""
                (() => {{
                  const re = new RegExp({_js_string(label_re)}, 'i');
                  for (const el of document.querySelectorAll({_js_string(selector)})) {{
                    const txt = (el.innerText || el.textContent || '').trim();
                    if (re.test(txt) && el.offsetParent !== null) {{
                      el.click();
                      return true;
                    }}
                  }}
                  return false;
                }})()
            """)
            if clicked:
                wait_for_network_idle(timeout=3, idle_ms=400)
                return True
        time.sleep(0.5)
    return False


def detect_captcha_or_raise():
    """Probe for visible captcha widgets and raise the structured signal.

    The server.py captcha detector runs on text/title; this is the in-skill
    check that catches widget-based captchas (iframes from hcaptcha/turnstile/
    google recaptcha) that don't always include the text triggers. Skills
    call this right before clicking the submit button.
    """
    hit = js("""
        (() => {
          const sel = [
            "iframe[src*='hcaptcha.com']",
            "iframe[src*='cloudflare.com/cdn-cgi/challenge-platform']",
            "iframe[src*='challenges.cloudflare.com']",
            "iframe[src*='google.com/recaptcha']",
            "iframe[src*='recaptcha.net']",
            "div.g-recaptcha",
            ".h-captcha",
            "div.cf-turnstile",
          ];
          for (const s of sel) {
            const el = document.querySelector(s);
            if (el && el.offsetParent !== null) return s;
          }
          return null;
        })()
    """)
    if hit:
        # Surface as a captcha_required signal via the harness's structured
        # error path. The run_skill tool turns Python exceptions into
        # {code: "skill_error", ...} — but we want code:"captcha_required",
        # so we use a sentinel string the dispatcher recognises. (See
        # README's "Captcha" section.)
        raise RuntimeError(f"captcha_required: visible widget {hit}")


def is_captcha_required_error(exc):
    """True if exc is the sentinel raised by detect_captcha_or_raise."""
    return isinstance(exc, RuntimeError) and str(exc).startswith("captcha_required:")


def fill_email_password(email_selector, password_selector, email, password,
                        wait_timeout=10):
    """Wait for both fields, fill them, return True on success.

    Most signup forms render the email + password inputs together; if the
    selector for either doesn't resolve within `wait_timeout` seconds, the
    form layout has rotted — return False and let the caller decide whether
    to escalate or try an alternate selector."""
    if not wait_for_element(email_selector, timeout=wait_timeout):
        return False
    if not wait_for_element(password_selector, timeout=2):
        return False
    fill(email_selector, email)
    fill(password_selector, password)
    return True


def make_result(status, email, **extra):
    """Standard return shape across all 8 signup skills.

    status ∈ {
      "verification_email_sent",  # form submitted, waiting on email click
      "account_created",          # account is fully live, no email step
      "captcha_required",         # blocked at signup, agent must escalate
      "form_changed",             # selectors didn't match — needs re-verify
    }

    extra fields:
      account_url        — the dashboard URL if available
      verification_state — "pending" / "complete" / "not_required"
      credentials_path   — where the (email, password) tuple is stored
                            (the integrator's secrets store; skill doesn't
                            persist itself)
      detail             — human-readable note for the agent / operator
    """
    return {"status": status, "email": email, **extra}


def _js_string(s):
    """Embed a Python string as a JS string literal. JSON-encodes which
    handles every escape we care about (quotes, backslash, newline)."""
    import json
    return json.dumps(s)
