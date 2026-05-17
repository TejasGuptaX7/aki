"""Sign up for a HubSpot free CRM trial.

# verified: 2026-05-16 (static review only — selectors not yet live-validated)
# requires: args.email, args.password, args.full_name, args.company
# optional: args.industry (one of HubSpot's dropdown options), args.size
# returns:  {status, email, account_url?, verification_state, detail?}
#
# HubSpot's signup is multi-step:
#   Step 1: email
#   Step 2: full name + password
#   Step 3: company name + URL  (we leave URL blank — HubSpot infers it)
#   Step 4: industry + employee count   (we skip — defaults work)
#   Step 5: verify email via link
#
# We complete steps 1-3 then return verification_email_sent (HubSpot gates
# the portal behind email click-through on free trials).
"""

load_helpers("_signup_helpers")

email = args["email"]
password = args["password"]
full_name = args["full_name"]
company = args["company"]
industry = args.get("industry")

navigate("https://app.hubspot.com/signup/crm/step/user-info",
         wait_for_load=True, timeout=20)
dismiss_cookie_banner()

# --- Step 1: email -----------------------------------------------------------
EMAIL_SEL = "input[name='email'], input[type='email']"
if not wait_for_element(EMAIL_SEL, timeout=15):
    result = make_result("form_changed", email,
                         detail="email input never appeared on signup")
else:
    fill(EMAIL_SEL, email)
    clicked = js("""
        (() => {
          for (const b of document.querySelectorAll("button[type='submit'], button[data-test-id*='submit'], button")) {
            const t = (b.innerText || '').trim().toLowerCase();
            if (/next|continue|sign up/.test(t)) { b.click(); return true; }
          }
          return false;
        })()
    """)
    if not clicked:
        press_key("Enter")
    wait_for_network_idle(timeout=8, idle_ms=500)

    # --- Step 2: name + password --------------------------------------------
    NAME_SEL = "input[name='firstName'], input[name='fullName'], input[name='name']"
    PASS_SEL = "input[name='password'], input[type='password']"
    if not wait_for_element(NAME_SEL, timeout=10) or not wait_for_element(PASS_SEL, timeout=2):
        result = make_result("form_changed", email,
                             detail="name/password panel didn't render after step 1")
    else:
        first, _, last = full_name.partition(" ")
        # If the form uses firstName/lastName instead of fullName, fill both
        last_present = bool(js(f"!!document.querySelector('input[name=\"lastName\"]')"))
        if js("!!document.querySelector('input[name=\"firstName\"]')"):
            fill("input[name='firstName']", first)
            if last_present and last:
                fill("input[name='lastName']", last)
        else:
            fill(NAME_SEL, full_name)
        fill(PASS_SEL, password)

        try:
            detect_captcha_or_raise()
        except RuntimeError as e:
            if is_captcha_required_error(e):
                raise
            raise

        click_next = js("""
            (() => {
              for (const b of document.querySelectorAll("button[type='submit'], button")) {
                const t = (b.innerText || '').trim().toLowerCase();
                if (/next|continue|create account|sign up/.test(t)) { b.click(); return true; }
              }
              return false;
            })()
        """)
        if not click_next:
            press_key("Enter")
        wait_for_network_idle(timeout=10, idle_ms=500)

        # --- Step 3: company --------------------------------------------------
        COMPANY_SEL = "input[name='companyName'], input[name='company'], input[placeholder*='company' i]"
        if wait_for_element(COMPANY_SEL, timeout=10):
            fill(COMPANY_SEL, company)
            if industry:
                # HubSpot uses a custom listbox for industry — best-effort.
                js(f"""
                    (() => {{
                      const trigger = document.querySelector('button[id*=\"industry\" i], [data-test-id*=\"industry\"]');
                      if (trigger) trigger.click();
                    }})()
                """)
                wait_for_element(f"li[data-value='{industry}'], li[data-test-id*='option']", timeout=3)
                js(f"""
                    (() => {{
                      for (const li of document.querySelectorAll('li')) {{
                        if ((li.innerText || '').trim().toLowerCase() === {repr(industry.lower())}) {{
                          li.click(); return true;
                        }}
                      }}
                      return false;
                    }})()
                """)
            click_final = js("""
                (() => {
                  for (const b of document.querySelectorAll("button[type='submit'], button")) {
                    const t = (b.innerText || '').trim().toLowerCase();
                    if (/next|continue|sign up|create/.test(t)) { b.click(); return true; }
                  }
                  return false;
                })()
            """)
            if not click_final:
                press_key("Enter")
            wait_for_network_idle(timeout=12, idle_ms=600)

        page = page_info()
        result = make_result(
            "verification_email_sent", email,
            account_url=page.get("url"),
            verification_state="pending",
            company=company,
            detail="HubSpot signup form filled; verify-email step gates the portal",
        )
