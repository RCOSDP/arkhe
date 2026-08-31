"""トークン発行（`ARKHE_AUTH` に `oauth2` を含めたときだけ現れる）。

**arkhe が単体でトークンを配るための口。** Keycloak のような認可サーバを持たない
組織でも、OAuth2 の作法で API を叩けるようにする。

grant は **client_credentials だけ**。ARK の採番は組織のシステムからの M2M で、
認可コードフローが解く「利用者が第三者アプリに代理を許可する」構図が無い。
人のログインが要るなら `oidc` で外部に委譲する（`ARKHE_ADMIN_LOGIN` を見よ）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.openapi.models import OAuthFlowClientCredentials, OAuthFlows
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2

from arkhe.api import i18n
from arkhe.auth import oauth2
from arkhe.auth.deps import Config, Db
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.domain import authz

router = APIRouter(prefix="/oauth", tags=["oauth"])

#: **仕様書にも「ここで取る」と書く。** これを依存に置いた口には `securitySchemes`
#: の `oauth2` が載り、Swagger UI の Authorize からトークンを取れる。生成した
#: クライアントも取得手順を持てる——エンドポイントの URL は README にしか無かった。
#:
#: **値は使わない**（`bearer_scheme` と同じで、載せるためだけの依存）。検証は
#: `auth.deps` の 1 か所に集める。`auto_error=False` なのも同じ理由で、
#: 公開情報の読取をここで 403 にしない。
#:
#: scope の語彙は `authz.SCOPES`、その説明は管理画面と同じ語から起こす。
#: **3 か所目を作らない**——増えると、登録できるのに説明の無い scope が生まれる。
scheme = OAuth2(
    scheme_name="oauth2",
    description="arkhe が自分で発行するトークン（RFC 6749 §4.4 client_credentials）。",
    flows=OAuthFlows(
        clientCredentials=OAuthFlowClientCredentials(
            tokenUrl=f"{router.prefix}/token",
            scopes={s: i18n.EN[f"sc.{s}"] for s in authz.SCOPES},
        )
    ),
    auto_error=False,
)


@router.post("/token", summary="アクセストークンを発行する（client_credentials）")
def token(
    request: Request,
    session: Db,
    cfg: Config,
    response: Response,
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    client_secret: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "",
):
    """RFC 6749 §4.4 の client_credentials。

    資格情報は **本文でも Basic 認証でも**受ける（§2.3.1 は Basic を推奨し、
    本文も認めている。既存のクライアントライブラリはどちらも使う）。
    """
    if "oauth2" not in cfg.auth:
        return JSONResponse(
            {"error": "unsupported_grant_type",
             "error_description": "この構成は自前でトークンを発行しません（ARKHE_AUTH）"},
            status_code=404,
        )
    if grant_type != "client_credentials":
        # **他の grant は持たない。** 実装しないものを明示して返す。
        return JSONResponse(
            {"error": "unsupported_grant_type",
             "error_description": "client_credentials のみ対応しています"},
            status_code=400,
        )

    if not client_id:
        client_id, client_secret = _basic(request) or ("", "")

    try:
        body = oauth2.issue_token(
            session,
            client_id=client_id,
            client_secret=client_secret,
            requested_scope=scope,
            secret_key=cfg.token_secret,
            ttl=cfg.token_ttl,
            issuer=cfg.token_issuer,
        )
    except AuthError:
        session.commit()
        # RFC 6749 §5.2: 資格情報が違うなら invalid_client。
        # **理由は分けない**（存在するクライアント名を総当たりで探せてしまう）。
        return JSONResponse(
            {"error": "invalid_client"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="arkhe"'},
        )
    except Forbidden as exc:
        return JSONResponse(exc.detail, status_code=400)

    session.commit()
    # §5.1: トークンの応答はキャッシュさせない。
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return body


def _basic(request: Request) -> tuple[str, str] | None:
    import base64
    import binascii

    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(raw[6:].strip()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    cid, _, secret = decoded.partition(":")
    return cid, secret
