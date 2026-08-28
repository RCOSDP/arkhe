"""設定。**認証機構は排他ではなく、個別に有効化できる。**

`ARKHE_AUTH` に列挙したものを順に試す。移行期に「API キーと OIDC の両方を受ける」
が普通に要るので、単一の「モード」にはしない。

  apikey  … arklet 方式の API キー。**arkhe 単体で完結する**（外部依存なし）
  oauth2  … arkhe 自身が client_credentials でトークンを発行する。単体で完結する
  oidc    … 外部の認可サーバ（Keycloak 等）が発行した JWT を検証する。委譲

`oauth2` を client_credentials だけに絞っているのは、ARK の採番が機関システムから
の M2M だからで、認可コードフロー（＝利用者がブラウザで第三者アプリに許可を与える
手順）が要る場面が無いため。人間のログインが要るなら `oidc` で外部に委譲する。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Mechanism = Literal["apikey", "oauth2", "oidc"]


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

    #: `oidc`（委譲）用。発行者と、受け入れる audience。
    oidc_issuer: str = ""
    oidc_audience: str = ""
    #: JWKS の取得先。未設定なら issuer の discovery から引く。
    oidc_jwks_url: str = ""

    # ---------------------------------------------------------------- 解決
    #: D2: 未知 NAAN の取次先。
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
        """**設定し忘れをその場で止める。** 既定の秘密値は持たない。"""
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
