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
from fastapi.responses import JSONResponse

from arkhe.auth.errors import AuthError, Forbidden
from arkhe.domain.authz import Invalid, NotFound, ShoulderDelegated, Throttled
from arkhe.settings import Settings, get_settings


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

    for exc_type, code in ((Forbidden, 403), (NotFound, 404), (Invalid, 400), (Throttled, 429)):

        @app.exception_handler(exc_type)
        async def _h(request: Request, exc, _code=code):  # noqa: ARG001
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
            return JSONResponse(detail, status_code=_code)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    s.check()

    app = FastAPI(
        title="arkhe",
        summary="ARK identifier infrastructure — minter and resolver as separate services",
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    _install_handlers(app)

    if s.resolver:
        from arkhe.api import resolve

        app.include_router(resolve.router)
        return app  # **minter に解決の口が無いのと同様、resolver に採番の口は無い**

    from arkhe.api import admin, mint

    app.include_router(mint.router)
    app.include_router(admin.router)
    return app
