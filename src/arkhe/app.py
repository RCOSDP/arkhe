"""アプリの組み立て。**役割で口を分ける。**

  resolver … 解決だけ。採番も管理もできない。読み取り専用ロールに向けられる
  minter   … 採番・更新 API
  admin    … 管理画面（`ARKHE_ADMIN=on` のときだけ）

分けているのは、resolver を別々にスケールさせるためと、**採番の口を持たない
プロセスを作れる**ようにするため。解決は止められないが採番は止めてよい、という
運用ができる。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from arkhe import __version__
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.domain.authz import Invalid, NotFound, ShoulderDelegated, Throttled
from arkhe.settings import Settings, get_settings

#: Swagger UI の冒頭に出る説明。**仕様上の要点を、試す前に読めるところに置く。**
API_DESCRIPTION = """\
ARK 識別子の採番と解決。

**ARK は再割当てしない（NR）。** この一点が API の形をほぼ決めている。

* **採番した ARK は取り消せない。** 削除の口は無く、対象が失われたときは
  `tombstone`（記述は残り、到達性だけが落ちる）。
* **再送で番号を増やさない。** `request_id` を付けて送れば、同じ値の再送には
  前回と同じ ARK が返る。万オーダーの投入は途中で切れる方が普通なので、
  切れた塊はそのまま再送してよい。
* **shoulder はリクエストで指定しても広がらない。** 到達範囲は資格情報の
  登録属性で決まる。省略すれば組織の既定が使われる。
* **子リソースは採番しない。** `ark:/99999/x9abc/page/3` のような深い参照は
  suffix passthrough が賄うので、1 レコード 1 採番で足りる。

### 認証

`Authorize` から Bearer トークンを入れる。受け付ける資格情報は起動時の
`ARKHE_AUTH` で決まり、API キー・arkhe が発行したトークン・外部の認可サーバが
発行した JWT のいずれか（併用可）。

**公開情報の読取に認証は要らない。** リポジトリは公開レコードを誰にでも見せる
ものだから。
"""

TAGS = [
    {
        "name": "ark",
        "description": "採番と更新。**書き込みは到達範囲の内側にしか届かない。**",
    },
    {
        "name": "resolve",
        "description": (
            "解決。`?`（簡潔な記述）・`??`（永続性宣言）・`?info`（人間向け）・"
            "`?json`（機械可読）の inflection を持つ。"
            "**対象に到達できなくても記述は答えられる**（FAIR A2）。"
            "`ARKHE_RESOLVER=1` で起動したときだけ現れる。"
        ),
    },
]


def _install_handlers(app: FastAPI) -> None:
    """ドメインの例外を HTTP に写す。**ドメイン側は HTTP を知らないままにする。**"""

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError):  # noqa: ARG001
        return JSONResponse(
            {"detail": exc.detail}, status_code=401, headers={"WWW-Authenticate": exc.challenge}
        )

    @app.exception_handler(ShoulderDelegated)
    async def _delegated(request: Request, exc: ShoulderDelegated):  # noqa: ARG001
        # **プロキシせず 307 で行き先を案内する。** 代理で呼ぶと、応答が失われた
        # ときに「向こうでは採番されたがこちらは知らない ARK」が生まれる。
        if exc.minter:
            return JSONResponse(exc.detail, status_code=307, headers={"Location": exc.minter})
        return JSONResponse(exc.detail, status_code=403)

    from arkhe.api.admin import NeedsLogin

    @app.exception_handler(NeedsLogin)
    async def _needs_login(request: Request, exc: NeedsLogin):  # noqa: ARG001
        # **401 を返さない。** ブラウザに Authorization ヘッダは付けられないので、
        # 401 を見せても人には何もできない。ログイン画面へ送る。
        from urllib.parse import quote

        return RedirectResponse(f"/admin/login?next={quote(exc.next_url)}", status_code=302)

    for exc_type, code in ((Forbidden, 403), (NotFound, 404), (Invalid, 400), (Throttled, 429)):

        @app.exception_handler(exc_type)
        async def _h(request: Request, exc, _code=code):  # noqa: ARG001
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
            return JSONResponse(detail, status_code=_code)


#: 画面に付ける保護。**CSP が本体**で、ほかは補助。
#:
#: 転送先のスキームは書き込み時にも読み取り時にも絞っているが、`?info` は
#: 認証を要さない公開ページで、そこに載る文字列を決めるのは採番した側である。
#: **一段目が破れても実行させない**ためにインラインスクリプトを禁じる。
#:
#: `style-src` に `unsafe-inline` が要るのは、この画面が CSS を HTML に
#: 埋め込んでいるため（配信物を増やさないための選択）。**スクリプトは
#: 一切埋め込んでいない**ので、`script-src 'none'` にできる。
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'none'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # HTTPS で出すかは前段が決めるので、ここでは HSTS を付けない
    # （http で配っている構成に付けると、そのホストが開けなくなる）。
}


#: API ドキュメントだけは別扱い。**Swagger UI は CDN から script を読む**ので、
#: `script-src 'none'` を当てると真っ白になる。読み込み先を限る形に緩める。
DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
DOCS_PATHS = ("/api/docs", "/api/redoc")


def _install_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path in DOCS_PATHS:
            response.headers["Content-Security-Policy"] = DOCS_CSP
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    s.check()

    app = FastAPI(
        title="arkhe",
        summary="ARK identifier infrastructure — minter and resolver as separate services",
        description=API_DESCRIPTION,
        version=__version__,
        license_info={"name": "MIT", "identifier": "MIT"},
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    _install_handlers(app)
    _install_security_headers(app)

    # **どのモードでも生存確認の口は要る。** 以前は resolve ルータにしか無く、
    # minter と admin は probe に 404 を返し続けて kubelet に殺されていた。
    # 認証も DB も通さない——落ちているのがアプリ自身かどうかだけを見る。
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    if s.resolver:
        from arkhe.api import resolve

        app.include_router(resolve.router)
        return app  # **minter に解決の口が無いのと同様、resolver に採番の口は無い**

    from arkhe.api import admin, mint

    app.include_router(mint.router)
    app.include_router(admin.router)
    if "oauth2" in s.auth:
        # **自前でトークンを配るときだけ口を開ける。** 使わない構成に
        # 認可サーバの入口を生やさない。
        from arkhe.api import token

        app.include_router(token.router)
    return app
