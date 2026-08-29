"""設定。**認証機構は排他ではなく、個別に有効化できる。**

`ARKHE_AUTH` に列挙したものを順に試す。移行期に「API キーと OIDC の両方を受ける」
が普通に要るので、単一の「モード」にはしない。

  apikey  … arklet 方式の API キー。**arkhe 単体で完結する**（外部依存なし）
  oauth2  … arkhe 自身が client_credentials でトークンを発行する。単体で完結する
  oidc    … 外部の認可サーバ（Keycloak 等）が発行した JWT を検証する。委譲

`oauth2` を client_credentials だけに絞っているのは、ARK の採番が組織システムから
の M2M だからで、認可コードフロー（＝利用者がブラウザで第三者アプリに許可を与える
手順）が要る場面が無いため。人間のログインが要るなら `oidc` で外部に委譲する。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Mechanism = Literal["apikey", "oauth2", "oidc"]
AdminLogin = Literal["bearer", "password", "oidc", "proxy"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARKHE_", env_file=".env", extra="ignore")

    # ---------------------------------------------------------------- 役割
    #: resolver として起動する。**minter に解決の口は無く、resolver に採番の口は無い。**
    #: 別々にスケールさせ、resolver を読み取り専用ロールとレプリカに向けるため。
    resolver: bool = False

    debug: bool = False
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # ---------------------------------------------------------------- DB
    database_url: str = "postgresql+psycopg://arkhe@localhost/arkhe"
    #: resolver 用の読み取り専用接続。未設定なら `database_url` を使う。
    read_database_url: str = ""

    # ---------------------------------------------------------------- 認証
    #: `NoDecode` を付けるのは、pydantic-settings が環境変数の list を JSON として
    #: 解釈しようとするため。`ARKHE_AUTH=apikey,oidc` と書けるようにする。
    auth: Annotated[list[Mechanism], NoDecode] = Field(
        default_factory=lambda: ["apikey", "oidc"]
    )

    #: `oauth2`（自前発行）用。トークンの署名鍵と寿命。
    token_secret: str = ""
    token_ttl: int = 3600
    token_issuer: str = ""

    #: `oidc`（委譲）用。発行者と、**API のアクセストークン**に求める audience。
    #:
    #: 管理画面のログインで検証する ID トークンの `aud` は必ず `admin_client_id`
    #: なので、ここの値は使わない（混ぜると片方が必ず落ちる）。
    oidc_issuer: str = ""
    oidc_audience: str = ""
    #: JWKS の取得先。未設定なら issuer の discovery から引く。
    oidc_jwks_url: str = ""

    # ------------------------------------------------------- 管理画面への入口
    #: **ブラウザは Authorization ヘッダを付けられない。** API は Bearer で足りるが、
    #: 人が管理画面に入る経路は別に要る。
    #:
    #:   bearer    既定。ログイン画面を持たない（自動化・curl 専用）
    #:   password  arkhe が ID とパスワードを預かる。**外部 IdP が無くても単体で建つ**
    #:   oidc      arkhe が OIDC のクライアントとして認可コードフローを回す
    #:   proxy     前段の認証プロキシが済ませた前提で、そのヘッダを信じる
    #:
    #: **oidc / proxy が使えるならそちらがよい。** 身元の管理が 1 か所に集まり、
    #: 退職や異動が組織側の操作だけで効く。password は、それが無い組織のためのもの。
    admin_login: AdminLogin = "bearer"

    #: セッション Cookie の署名鍵と寿命。**既定値は持たない。**
    session_secret: str = ""
    session_ttl: int = 28800  # 8 時間。断続的に 1 日使う想定
    #: Cookie に Secure を付けるか。HTTPS で出すなら true のままにする。
    session_secure: bool = True

    #: `admin_login=oidc` のときの、arkhe 自身のクライアント登録。
    admin_client_id: str = ""
    admin_client_secret: str = ""
    admin_scope: str = "openid profile email"

    #: `admin_login=proxy` のときに身元を読むヘッダ。
    proxy_user_header: str = "X-Forwarded-User"

    # ---------------------------------------------------------------- 解決
    #: D2: 未知 NAAN の取次先。
    #: **前段（ロードバランサやプロキシ）を何段信じるか。**
    #:
    #: `X-Forwarded-For` は誰でも付けられるヘッダなので、既定では見ない（`0`）。
    #: 見ずに直接の接続元を記録するほうが、詐称された値を記録するよりましである
    #: ——監査ログに攻撃者の書いた文字列が並ぶのがいちばん困る。
    #:
    #: 前段が n 段あるなら `n` を入れる。**右から n 番目**を採る（右端は自分の
    #: 直前の前段が書いた値で、これは信じられる）。左端を採ってはいけない
    #: ——そこは client が書いた値だから。
    trusted_proxies: int = 0

    global_resolver: str = "https://n2t.net"

    # ---------------------------------------------------------------- 採番
    bulk_limit: int = 1000

    @field_validator("auth", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    def check(self) -> None:
        """**設定し忘れをその場で止める。** 既定の秘密値は持たない。

        resolver は例外。解決に認証は要らず、管理画面も載らないので、
        **認証まわりの設定は一切要求しない**——要求すると、使いもしない
        セッション鍵を解決系の全ノードに配ることになる。
        """
        if self.resolver:
            return
        if not self.auth:
            raise ValueError("ARKHE_AUTH が空です。apikey / oauth2 / oidc から選んでください")
        if "oauth2" in self.auth:
            if not self.token_secret:
                raise ValueError(
                    "ARKHE_AUTH に oauth2 を含めるなら ARKHE_TOKEN_SECRET が要ります"
                    "（自前でトークンを発行するための署名鍵。既定値は持ちません）"
                )
            # RFC 7518 §3.2: HS256 の鍵はハッシュ長（32 バイト）以上であること。
            # 短い鍵でも PyJWT は警告を出すだけで動いてしまうので、ここで止める。
            if len(self.token_secret.encode()) < 32:
                raise ValueError(
                    "ARKHE_TOKEN_SECRET が短すぎます（32 バイト以上。RFC 7518 §3.2）。"
                    "例: python -c \"import secrets;print(secrets.token_urlsafe(48))\""
                )
        if self.admin_login != "bearer" and not self.session_secret:
            raise ValueError(
                f"ARKHE_ADMIN_LOGIN={self.admin_login} には ARKHE_SESSION_SECRET が要ります"
                "（セッション Cookie の署名鍵。既定値は持ちません）"
            )
        if self.admin_login != "bearer" and len(self.session_secret.encode()) < 32:
            raise ValueError("ARKHE_SESSION_SECRET が短すぎます（32 バイト以上）")
        if self.admin_login == "oidc":
            if not self.oidc_issuer:
                raise ValueError("ARKHE_ADMIN_LOGIN=oidc には ARKHE_OIDC_ISSUER が要ります")
            if not self.admin_client_id:
                raise ValueError(
                    "ARKHE_ADMIN_LOGIN=oidc には ARKHE_ADMIN_CLIENT_ID が要ります"
                    "（認可サーバに登録した arkhe 自身のクライアント）"
                )
        if "oidc" in self.auth and not self.oidc_issuer:
            raise ValueError(
                "ARKHE_AUTH に oidc を含めるなら ARKHE_OIDC_ISSUER が要ります"
                "（委譲先の認可サーバ。例 https://keycloak.example.org/realms/arkhe）"
            )

    @property
    def read_url(self) -> str:
        return self.read_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
