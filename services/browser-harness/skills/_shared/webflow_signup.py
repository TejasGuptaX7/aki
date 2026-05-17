"""Sign up for a Webflow account.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password
# optional: args.full_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# WARNING — Webflow has aggressive bot mitigation (Cloudflare Turnstile is
# almost always shown on the signup form). The `detect_captcha_or_raise`
# call below will fire on most attempts; this is expected — the agent
# should escalate to its captcha-handling path (per-customer solver, a
# human in the loop, or a "we don't sign up to Webflow autonomously"
# policy decision).
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args.get("full_name", "Aki Agent")

navigate("https://webflow.com/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

# Webflow gates the form behind a "Sign up with email" tab on some variants.
js("""
    (() => {
      for (const b of document.querySelectorAll("button, a")) {
        const t = (b.innerText || '').trim().toLowerCase();
        if (t === 'sign up with email' || t === 'email') { b.click(); return; }
      }
    })()
""")
wait_for_network_idle(timeout=3, idle_ms=300)

EMAIL_SEL = "input[type='email'], input[name='email']"
PASS_SEL = "input[type='password'], input[name='password']"
NAME_SEL = "input[name='name'], input[name='fullName'], input[placeholder*='name' i]"

if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)
    if wait_for_element(NAME_SEL, timeout=3):
        fill(NAME_SEL, full_name)
    if not wait_for_element(PASS_SEL, timeout=3):
        result = make_result("form_changed", email,
                             detail="password input never appeared next to email")
    else:
        fill(PASS_SEL, password)

        # Accept any visible checkbox (terms of service)
        js("""
            (() => {
              for (const c of document.querySelectorAll("input[type='checkbox']")) {
                if (!c.checked) c.click();
              }
            })()
        """)

        # Webflow almost always shows Turnstile — this raises immediately
        # in the expected case. Let it propagate.
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
                if (/(create account|sign up|get started)/.test(t)) {
                  b.click(); return true;
                }
              }
              return false;
            })()
        """)
        if not clicked:
            press_key("Enter")
        wait_for_network_idle(timeout=15, idle_ms=600)

        # If we made it here without a captcha raise, Webflow accepted us —
        # which is unusual, so log the state for the agent.
        page = page_info()
        result = make_result(
            "verification_email_sent", email,
            account_url=page.get("url"),
            verification_state="pending",
            detail="Webflow accepted signup without showing the usual Turnstile — re-verify selectors",
        )
