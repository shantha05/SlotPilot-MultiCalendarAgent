"""Quick diagnostic: prints the MSAL client ID in use and attempts device-code
flow as a fallback to confirm whether the app registration is public-client-
capable at all.

Run with:  python diagnose_auth.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("MSAL_CLIENT_ID", "")
tenant_id = os.getenv("MSAL_TENANT_ID", "common")

print(f"MSAL_CLIENT_ID  : {client_id!r}")
print(f"MSAL_TENANT_ID  : {tenant_id!r}")

if not client_id:
    print("\nERROR: MSAL_CLIENT_ID is not set in .env — that is the root cause.")
    sys.exit(1)

import msal

authority = f"https://login.microsoftonline.com/{tenant_id}"
app = msal.PublicClientApplication(client_id=client_id, authority=authority)

print(f"\nAuthority       : {authority}")
print("\nAttempting device-code flow (does NOT require a browser redirect)…")
print("This will ONLY succeed if 'Allow public client flows' is ON in the portal.\n")

flow = app.initiate_device_flow(scopes=["User.Read"])
if "user_code" in flow:
    print(f"SUCCESS — the app IS public-client-capable.")
    print(f"(You would visit {flow['verification_uri']} and enter code {flow['user_code']})")
    print("\nSince device-code works, the issue with interactive login is likely that")
    print("the redirect URI platform in the portal is set to 'Web' instead of")
    print("'Mobile and desktop applications'. Fix: delete the http://localhost")
    print("entry from the Web platform and re-add it under Mobile and desktop apps.")
else:
    print(f"FAILED — error: {flow.get('error')}")
    print(f"Details: {flow.get('error_description')}")
    print("\nThis confirms 'Allow public client flows' is still OFF (or the wrong app")
    print("registration is being edited). In Azure Portal:")
    print("  1. Go to App registrations → find the app with client ID above")
    print("  2. Authentication → Advanced settings")
    print("  3. Set 'Allow public client flows' to Yes → Save")
