"""Sign up for a Mailchimp account (free tier).

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password, args.username
# optional: args.full_name, args.business_name
# returns:  {status, email, account_url?, verification_state, detail?}
#
# Mailchimp's free signup is:
#   /signup → email + username + password → "Activate Account" email link →
#   /signup/account-setup → business info (we skip the optional bits)
#
# The username has to be globally unique (it's the dashboard URL component);
# the caller is expected to pass something it knows is free, e.g. an org
# slug + a random suffix.
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
username = args["username"]

navigate("https://login.mailchimp.com/signup/", wait_for_load=True, timeout=20)
dismiss_cookie_banner()

EMAIL_SEL = "input[type='email'], input[name='email']"
USER_SEL = "input[name='new_username'], input[name='username'], input#new_username"
PASS_SEL = "input[type='password'], input[name='new_password'], input#new_password"

if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on /signup")
elif not wait_for_element(USER_SEL, timeout=5):
    result = make_result("form_changed", email,
                         detail="username input not on signup form")
elif not wait_for_element(PASS_SEL, timeout=5):
    result = make_result("form_changed", email,
                         detail="password input not on signup form")
else:
    fill(EMAIL_SEL, email)
    fill(USER_SEL, username)
    fill(PASS_SEL, password)

    # Mailchimp's password rules are strict (length, mixed case, numbers,
    # special char). If the caller's password fails them, the form won't
    # submit. The agent should re-attempt with a compliant password.
    try:
        detect_captcha_or_raise()
    except RuntimeError as e:
        if is_captcha_required_error(e):
            raise
        raise

    clicked = js("""
        (() => {
          for (const b of document.querySelectorAll("button[type='submit'], input[type='submit'], button")) {
            const t = (b.innerText || b.value || '').trim().toLowerCase();
            if (/(sign up|create account|get started)/.test(t)) {
              b.click(); return true;
            }
          }
          return false;
        })()
    """)
    if not clicked:
        press_key("Enter")
    wait_for_network_idle(timeout=12, idle_ms=600)

    # Mailchimp always sends an "Activate Your Account" email after step 1;
    # business info is collected after the link is clicked.
    sent = js("""
        !!Array.from(document.querySelectorAll('h1, h2, p, div'))
              .find(e => /activate your account|check your email|we sent (you )?an (activation|confirmation) email/i.test(e.innerText || ''))
    """)
    page = page_info()
    if sent:
        result = make_result(
            "verification_email_sent", email,
            account_url=page.get("url"),
            verification_state="pending",
            username=username,
            detail="Mailchimp sent activation email; business-info step happens post-click",
        )
    else:
        # Check for the specific Mailchimp password-rule error so the agent
        # knows what to retry with.
        pw_err = js("""
            (() => {
              const e = document.querySelector('.password-error, [data-error*=\"password\"]');
              return e ? (e.innerText || '').trim() : null;
            })()
        """)
        result = make_result(
            "form_changed", email,
            account_url=page.get("url"),
            password_error=pw_err,
            detail="no activation-email confirmation after submit; check password rules",
        )
