"""Sign up for a Linear workspace.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.workspace_name
# optional: args.full_name (used on the workspace setup panel)
# returns:  {status, email, account_url?, verification_state, detail?}
#
# Flow:
#   1. /signup with email
#   2. Linear sends a magic link — no password is ever required.
#      So this skill's "success" is always status=verification_email_sent.
#   3. The follow-up (clicking the magic link, naming the workspace) happens
#      after the email-poller calls back into the agent with the verified URL.
#
# Known fragility:
#   - Linear uses Cloudflare Turnstile on signup; the iframe-detector in
#     _signup_helpers.py catches it and we raise captcha_required.
"""

load_helpers("_signup_helpers")

email = args["email"]
workspace_name = args.get("workspace_name", "Aki Workspace")

navigate("https://linear.app/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

EMAIL_SEL = "input[type='email'], input[name='email'], input[autocomplete='email']"
if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)

    try:
        detect_captcha_or_raise()
    except RuntimeError as e:
        if is_captcha_required_error(e):
            raise
        raise

    clicked = js("""
        (() => {
          for (const b of document.querySelectorAll("button[type='submit'], button")) {
            const t = (b.innerText || '').trim().toLowerCase();
            if (/^(continue|sign up( with email)?)$/.test(t)) {
              b.click(); return true;
            }
          }
          return false;
        })()
    """)
    if not clicked:
        press_key("Enter")

    wait_for_network_idle(timeout=10, idle_ms=500)

    # Linear renders a "Check your inbox" panel on success.
    sent = js("""
        !!Array.from(document.querySelectorAll('h1, h2, p, div'))
              .find(e => /check your (inbox|email)|sent you a (magic )?link/i.test(e.innerText || ''))
    """)
    if not sent:
        result = make_result("form_changed", email,
                             detail="no 'check your inbox' confirmation after submit",
                             workspace_name=workspace_name)
    else:
        page = page_info()
        result = make_result(
            "verification_email_sent", email,
            account_url=page.get("url"),
            verification_state="pending",
            workspace_name=workspace_name,
            detail="Linear sent a magic link; agent completes signup after click-through",
        )
