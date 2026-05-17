"""Sign up for a Typeform account.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password
# optional: args.full_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# Typeform's signup is single-page: email + password + (optional) full name.
# Like most modern SaaS, the dashboard is gated on email verification.
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args.get("full_name", "Aki Agent")

navigate("https://admin.typeform.com/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

EMAIL_SEL = "input[type='email'], input[name='email'], input[data-qa='email-input']"
PASS_SEL = "input[type='password'], input[name='password'], input[data-qa='password-input']"

if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)
    if not wait_for_element(PASS_SEL, timeout=5):
        result = make_result("form_changed", email,
                             detail="password input never appeared next to email")
    else:
        fill(PASS_SEL, password)
        # Some variants have a separate name field — fill if present.
        NAME_SEL = "input[name='name'], input[name='fullName'], input[data-qa='name-input']"
        if wait_for_element(NAME_SEL, timeout=2):
            fill(NAME_SEL, full_name)

        # Terms-of-service checkbox — Typeform sometimes requires explicit consent.
        js("""
            (() => {
              for (const c of document.querySelectorAll("input[type='checkbox']")) {
                if (!c.checked) c.click();
              }
            })()
        """)

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
                if (/create (account|free account)|sign up|get started/.test(t)) {
                  b.click(); return true;
                }
              }
              return false;
            })()
        """)
        if not clicked:
            press_key("Enter")

        wait_for_network_idle(timeout=12, idle_ms=600)

        page = page_info()
        # On success Typeform redirects to /onboarding or shows a verify-email screen.
        on_verify = js("""
            !!Array.from(document.querySelectorAll('h1, h2, p'))
                  .find(e => /verify your email|check your inbox|sent you (an|a confirmation) email/i.test(e.innerText || ''))
        """)
        result = make_result(
            "verification_email_sent" if on_verify else "account_created", email,
            account_url=page.get("url"),
            verification_state="pending" if on_verify else "not_required",
            detail="Typeform signup form submitted",
        )
