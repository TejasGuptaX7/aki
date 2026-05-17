"""Sign up for a ClickUp workspace (free forever plan).

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password
# optional: args.full_name, args.workspace_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# ClickUp's signup is a single page: email + password + (optional) name.
# After submit, a verification email is sent and the dashboard lets you in
# but with a banner that gates a few features until verification.
# We return verification_email_sent so the agent's email-poller closes the
# loop.
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args.get("full_name", "Aki Agent")
workspace_name = args.get("workspace_name", "Aki Workspace")

navigate("https://app.clickup.com/signup", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

EMAIL_SEL = "input[type='email'], input[name='email'], input[autocomplete='email']"
PASS_SEL = "input[type='password'], input[name='password']"
NAME_SEL = "input[name='name'], input[name='fullName'], input[placeholder*='name' i]"

if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
else:
    fill(EMAIL_SEL, email)
    if wait_for_element(NAME_SEL, timeout=3):
        fill(NAME_SEL, full_name)
    if not wait_for_element(PASS_SEL, timeout=5):
        result = make_result("form_changed", email,
                             detail="password input never appeared next to email")
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
                if (/(play with clickup|sign up|create account|get started|continue with email)/.test(t)) {
                  b.click(); return true;
                }
              }
              return false;
            })()
        """)
        if not clicked:
            press_key("Enter")
        wait_for_network_idle(timeout=12, idle_ms=600)

        # ClickUp usually drops you straight into the onboarding wizard
        # (workspace name → use case → invite team → done). We fill the
        # workspace name if the input is there and stop — the rest is
        # cosmetic.
        WORKSPACE_SEL = "input[placeholder*='workspace' i], input[name*='workspace' i]"
        if wait_for_element(WORKSPACE_SEL, timeout=5):
            fill(WORKSPACE_SEL, workspace_name)

        page = page_info()
        verify_banner = js("""
            !!Array.from(document.querySelectorAll('div, span, p'))
                  .find(e => /verify your email|check your inbox|confirm your email/i.test(e.innerText || ''))
        """)
        result = make_result(
            "verification_email_sent" if verify_banner else "account_created", email,
            account_url=page.get("url"),
            verification_state="pending" if verify_banner else "not_required",
            workspace_name=workspace_name,
            detail="ClickUp signup submitted; verification email expected for full feature access",
        )
