"""Sign up for an Airtable workspace.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password, args.full_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# Airtable's signup has been email + name + password on one page since the
# 2024 redesign, then a follow-up screen asks about role + team size which
# we skip (defaults work; the agent can revisit later via the dashboard).
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args["full_name"]

navigate("https://airtable.com/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

EMAIL_SEL = "input[type='email'], input[name='email']"
NAME_SEL = "input[name='name'], input[name='fullName'], input[placeholder*='name' i]"
PASS_SEL = "input[type='password'], input[name='password']"

if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)
    if wait_for_element(NAME_SEL, timeout=3):
        fill(NAME_SEL, full_name)
    if not wait_for_element(PASS_SEL, timeout=3):
        result = make_result("form_changed", email,
                             detail="password input not on same panel as email")
    else:
        fill(PASS_SEL, password)

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
                if (/(continue|sign up|create account|get started)/.test(t)) {
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
        verify = js("""
            !!Array.from(document.querySelectorAll('h1, h2, p'))
                  .find(e => /verify your email|confirm your email|check your inbox/i.test(e.innerText || ''))
        """)
        result = make_result(
            "verification_email_sent" if verify else "account_created", email,
            account_url=page.get("url"),
            verification_state="pending" if verify else "not_required",
            detail="Airtable signup submitted; onboarding survey skipped",
        )
