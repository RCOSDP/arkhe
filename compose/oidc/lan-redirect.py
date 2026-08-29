"""LAN のアドレス向けの redirect_uri を `arkhe-admin` に足す。

**realm JSON には書かない。** 公開されるクイックスタートに特定の LAN アドレスを
焼き込むことになるので、`lan.yml` で立ち上げたときにだけここで足す。

realm も client も**作り直さない**——作り直すと発行済みのセッションが飛び、
`sub` が変われば台帳に突き合わせている身元も切れる。既にある値に足すだけにする。
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
    sys.exit("ARKHE_DEMO_HOST が未設定です")

KC = f"http://{HOST}:8080"
REALM = "arkhe"
WANT = f"http://{HOST}:8057/admin/callback"


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
    sys.exit(f"Keycloak ({KC}) に届きません: {exc}")

found = call(
    "GET", f"/admin/realms/{REALM}/clients?clientId=arkhe-admin", token=token
)
if not found:
    sys.exit(f"realm {REALM} に arkhe-admin がありません")

client = found[0]
if WANT in client["redirectUris"]:
    print(f"redirect_uri は登録済み: {WANT}")
else:
    client["redirectUris"] = sorted({*client["redirectUris"], WANT})
    call("PUT", f"/admin/realms/{REALM}/clients/{client['id']}", body=client, token=token)
    print(f"redirect_uri を足しました: {WANT}")

print(f"→ http://{HOST}:8057/admin/  を開いてください")
