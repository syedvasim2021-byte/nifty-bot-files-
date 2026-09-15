"""
Kite Connect session handling.

Zerodha's access_token expires daily, and Kite Connect deliberately has no
API-only login (this is by design, for security). The supported flow is:

  1. Open the login URL in a browser and log in manually (with your 2FA/TOTP).
  2. Zerodha redirects to your app's redirect URL with a `request_token` in
     the query string.
  3. Exchange that request_token + your api_secret for an access_token.
  4. The access_token is valid until ~6 AM IST the next day (or logout).

This script automates steps 3 onward but deliberately does NOT try to script
the login page itself (no stored password / auto-TOTP submission). That kind
of full auto-login is technically possible and some traders do build it, but
it means keeping your account password and TOTP secret in a config file,
which is a meaningfully bigger security exposure than a 15-second manual
login once a day. Do your own risk assessment before adding that.
"""
from kiteconnect import KiteConnect

import config
from logger_setup import get_logger

log = get_logger()


def get_kite_session() -> KiteConnect:
    kite = KiteConnect(api_key=config.KITE_API_KEY)

    if config.KITE_ACCESS_TOKEN:
        kite.set_access_token(config.KITE_ACCESS_TOKEN)
        try:
            kite.profile()  # cheap call to verify the token is still valid
            log.info("Reusing existing access token from .env")
            return kite
        except Exception:
            log.warning("Stored access token is invalid/expired, need fresh login.")

    login_url = kite.login_url()
    print("\n1. Open this URL in your browser and log in:")
    print(f"   {login_url}")
    print("2. After login you'll be redirected to your app's redirect URL.")
    print("   Copy the 'request_token' value from that URL's query string.\n")
    request_token = input("Paste request_token here: ").strip()

    data = kite.generate_session(request_token, api_secret=config.KITE_API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)

    log.info("New access token generated. Add this to your .env to reuse it today:")
    log.info(f"KITE_ACCESS_TOKEN={access_token}")

    return kite
