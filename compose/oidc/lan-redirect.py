"""Add a redirect_uri for this machine's address on the network to arkhe-admin.

It is not written into the realm JSON, which would burn one particular address into a
published quickstart. It is added here, and only when lan.yml is used.

Neither the realm nor the client is recreated: recreating them would drop the sessions
already issued, and a changed sub would break the identities matched against the ledger.
This only adds to what is there.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("ARKHE_DEMO_HOST", "")
if not HOST:
    sys.exit("ARKHE_DEMO_HOST is not set")

KC = f"http://{HOST}:8080"
REALM = "arkhe"
WANT = f"http://{HOST}:8057/admin/callback"
#: Where to return to after signing out. It has to be registered separately from
#: redirectUris; the + form means the same as redirectUris, which does not include
#: /admin/.
WANT_LOGOUT = f"http://{HOST}:8057/admin/"


def call(method: str, path: str, body=None, form=None, token: str = ""):
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(KC + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


try:
    token = call(
        "POST", "/realms/master/protocol/openid-connect/token",
        form={"grant_type": "password", "client_id": "admin-cli",
              "username": "admin", "password": "admin"},
    )["access_token"]
except urllib.error.URLError as exc:
    sys.exit(f"cannot reach Keycloak at {KC}: {exc}")

found = call(
    "GET", f"/admin/realms/{REALM}/clients?clientId=arkhe-admin", token=token
)
if not found:
    sys.exit(f"realm {REALM} has no arkhe-admin client")

client = found[0]
attrs = client.setdefault("attributes", {})
logouts = [u for u in attrs.get("post.logout.redirect.uris", "").split("##") if u]

changed = False
if WANT not in client["redirectUris"]:
    client["redirectUris"] = sorted({*client["redirectUris"], WANT})
    changed = True
if WANT_LOGOUT not in logouts:
    attrs["post.logout.redirect.uris"] = "##".join(sorted({*logouts, WANT_LOGOUT}))
    changed = True

if changed:
    call("PUT", f"/admin/realms/{REALM}/clients/{client['id']}", body=client, token=token)
    print(f"registered: {WANT} and {WANT_LOGOUT}")
else:
    print("already registered")

print(f"open http://{HOST}:8057/admin/")
