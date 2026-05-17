"""Sign up for a new Notion account with email + password.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password
# optional: args.full_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# Flow:
#   1. Navigate to https://www.notion.so/signup
#   2. Dismiss cookie banner if visible
#   3. Fill email → click Continue → fill password → click Create account
#   4. If captcha widget appears: status=captcha_required (caller escalates)
#   5. On success, Notion sends a verification email — we return
#      status=verification_email_sent. The integrator's email-poller
#      service picks up the magic link and completes verification out-of-band.
#
# Known fragility:
#   - Notion A/B-tests the signup flow. There's a "Continue with email"
#     button on some variants; we click it via the role/label fallback in
#     `_click_label_button`.
#   - The "Use my password" tab may need an explicit click if Notion
#     defaults to magic-link auth that day.
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args.get("full_name", "Aki Agent")

navigate("https://www.notion.so/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

# Email field — Notion's id has rotated, so use the best-effort union.
EMAIL_SEL = "input[type='email'], input[id='notion-email-input-1'], input[name='email']"
if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)
    # "Continue with email" button — text-match because the data-test id
    # has rotated. Falls back to pressing Enter on the email field if no
    # button matches.
    clicked = js("""
        (() => {
          for (const b of document.querySelectorAll("button, div[role='button']")) {
            const t = (b.innerText || '').trim().toLowerCase();
            if (t === 'continue' || t === 'continue with email' || t === 'sign up with email') {
              b.click();
              return true;
            }
          }
          return false;
        })()
    """)
    if not clicked:
        press_key("Enter")
    wait_for_network_idle(timeout=8, idle_ms=500)

    # Notion may now show the password screen OR a "we sent you a code" screen
    # depending on the A/B variant. Prefer the password path; if we see the
    # code prompt, it's verification_email_sent already.
    code_screen = js("""
        !!Array.from(document.querySelectorAll('h1, h2, div'))
              .find(e => /enter the (sign[- ]?up|login) code|check your email/i.test(e.innerText || ''))
    """)
    if code_screen:
        result = make_result(
            "verification_email_sent", email,
            verification_state="pending",
            detail="Notion sent a magic-link/code; agent's email-poller completes signup",
        )
    else:
        PASS_SEL = "input[type='password']"
        if not wait_for_element(PASS_SEL, timeout=10):
            result = make_result("form_changed", email,
                                 detail="password input never appeared after Continue")
        else:
            fill(PASS_SEL, password)
            # Best-effort name field; Notion sometimes adds it on the same panel
            NAME_SEL = "input[name='name'], input[placeholder*='name' i]"
            if wait_for_element(NAME_SEL, timeout=2):
                fill(NAME_SEL, full_name)
            try:
                detect_captcha_or_raise()
            except RuntimeError as e:
                if is_captcha_required_error(e):
                    raise   # propagates to harness as code:captcha_required
                raise

            create_clicked = js("""
                (() => {
                  for (const b of document.querySelectorAll("button, div[role='button']")) {
                    const t = (b.innerText || '').trim().toLowerCase();
                    if (t === 'create account' || t === 'continue' || t === 'sign up') {
                      b.click(); return true;
                    }
                  }
                  return false;
                })()
            """)
            if not create_clicked:
                press_key("Enter")
            wait_for_network_idle(timeout=12, idle_ms=600)

            # Verification email is Notion's default — the dashboard is gated
            # behind clicking the link in the email.
            page = page_info()
            result = make_result(
                "verification_email_sent", email,
                account_url=page.get("url"),
                verification_state="pending",
                detail="filled signup form; email confirmation pending",
            )
