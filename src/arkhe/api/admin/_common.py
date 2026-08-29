"""管理画面が共有するもの——ルータ、テンプレート、主体の解決、出し分けの述語。

**画面ごとのモジュールはここだけを見る。** 判定を各画面に散らすと、
「ボタンは出ないが URL は通る」「押しても断られるだけのボタンが出る」の
どちらかが必ず起きる。

もとは 1 ファイル 1,100 行だった。認証・認可・画面・フォーム処理が同居して
いて、どこを直すと何に響くかが読み取れなかったので、既にコメントで区切って
あった境界のとおりに割った。**行を動かしただけで、中身は変えていない。**

画面が呼ぶのは `domain.admin_ops` と `domain.minting` で、DB を直接は触らない。
CLI と同じ関数を通るので、画面から不変条件を破る道が生まれない。

見せる範囲は `Principal` の 3 段（system / naan / manager）でそのまま絞る。
**画面の出し分けと実際の認可は同じ判定**を使う——別々にすると、ボタンは出ないが
URL を直接叩けば通る、という穴ができる。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.api import i18n
from arkhe.auth import login as login_flow
from arkhe.auth import session as sess
from arkhe.auth.deps import Config, Db, authenticate, bearer
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Client,
    CredentialKind,
    Manager,
    Naan,
    Shoulder,
    Subject,
)

# 管理画面は HTML であって API ではない。**OpenAPI には載せない。**
#: 1 ページの件数。**総件数は数えない**——ARK は増える一方で、毎回の
#: `count(*)` が効いてくる。「次があるか」は 1 件多く引いて判断する。
PAGE = 50


router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _issuable_kinds(cfg) -> list[str]:
    """この構成で**実際に使える**資格情報の種別。

    機構が有効でなければ、出した鍵はどこからも通らない（`auth.deps.authenticate`
    は `ARKHE_AUTH` に挙がった機構しか試さない）。**使えない鍵を出せる画面は、
    押しても何も起きないボタンと同じ。**

      apikey ∈ auth  → API キー（Bearer でそのまま送る）
      oauth2 ∈ auth  → client_secret（arkhe 自身の /oauth/token で換える）
      oidc   のみ    → **どちらも出さない。** 秘密は認可サーバが持っていて、
                       arkhe が持つのは client_id と到達範囲の対応だけ
    """
    kinds = []
    if "apikey" in cfg.auth:
        kinds.append(CredentialKind.API_KEY.value)
    if "oauth2" in cfg.auth:
        kinds.append(CredentialKind.CLIENT_SECRET.value)
    return kinds


def _entry_route(client: Client, cfg) -> str:
    """この主体が**どうやって入ってくるか**。

    `oidc` だけの構成では機械も鍵を持たない。にもかかわらず「資格情報 0 有効」と
    出していたので、**正しく設定できている主体が未設定に見えていた。**
    ここは「鍵を何本持っているか」ではなく「入れるかどうか」を出す。

    **機構は主体に結びついていない。** 有効な機構のうち、この `client_id` を
    示せるものならどれでも通る——だから「この主体の入り方」は、持っている鍵と
    構成の両方から決まる。台帳に別途持たせても認証には使われず、実態とずれる
    だけなので持たせていない。
    """
    if client.subject_type != Subject.MACHINE:
        return "person"                       # 外部ログイン / パスワード
    # **機構が無効な鍵は数えない。** 持っていても通らないので、あると言うと嘘になる
    # （`oidc` だけの構成に残っている古い API キーがまさにこれ）。
    usable = set(_issuable_kinds(cfg))
    if any(c.active and c.kind in usable for c in client.credentials):
        return "key"                          # arkhe が出した鍵
    if "oidc" in cfg.auth:
        return "idp"                          # 認可サーバのトークン
    return "none"                             # **本当に未設定**


def _can_add_client(p: Principal) -> bool:
    """届く範囲として利用者を作れるか。組織単位でも自組織なら作れる。"""
    return p.is_naan_wide or p.manager_id is not None


def _may_register(session: Session, p: Principal) -> bool:
    """実際に登録できるか。**配る側が自己登録を止めていればできない。**

    `_ctx` の既定は到達範囲だけを見るので、組織の設定はここで重ねる
    （`register_client` が拒む条件と同じものを、画面の出し分けにも使う）。
    """
    if not _can_add_client(p):
        return False
    if p.is_naan_wide:
        return True
    m = session.get(Manager, p.manager_id) if p.manager_id else None
    return m is None or m.may_self_register


def _ctx(request: Request, principal: Principal, page: str, **extra) -> dict:
    lang = i18n.pick(request)
    return {
        "request": request,
        "principal": principal,
        "page": page,
        "lang": lang,
        "langs": i18n.LANGS,
        "t": i18n.translator(lang),
        # **画面の出し分けと実際の認可は同じ判定を使う。**
        # 別々にすると「ボタンは出ないが URL を直接叩けば通る」穴ができる。
        # 逆に、**押しても断られるだけのボタンも出さない**——押せるものだけを
        # 見せるのが、到達範囲を画面で表すということ。
        "can_manage": principal.is_naan_wide,
        "can_audit": principal.is_naan_wide,
        "can_mint": principal.has("ark:mint"),
        "can_add_client": _can_add_client(principal),
        **extra,
    }


def _remember_lang(request: Request, response):
    """`?lang=` での明示の選択を記憶する。以降のページでも保たれる。"""
    q = request.query_params.get("lang")
    if q in i18n.CATALOGS:
        response.set_cookie(i18n.COOKIE, q, max_age=31536000, httponly=True, samesite="lax")
    return response


def _visible_naans(session: Session, p: Principal) -> list[Naan]:
    """その主体に見える NAAN。system は全部、それ以外は自分の 1 つ。"""
    stmt = select(Naan).order_by(Naan.naan)
    if not p.is_system:
        stmt = stmt.where(Naan.naan == p.naan)
    return list(session.scalars(stmt))


def _visible_shoulders(session: Session, p: Principal) -> list[Shoulder]:
    """採番に使える shoulder。**認可と同じ絞り方**にする。"""
    stmt = select(Shoulder).options(selectinload(Shoulder.manager)).order_by(
        Shoulder.naan, Shoulder.shoulder
    )
    if not p.is_system:
        stmt = stmt.where(Shoulder.naan == p.naan)
    if not p.is_naan_wide:
        if p.shoulder_id is not None:
            stmt = stmt.where(Shoulder.id == p.shoulder_id)
        else:
            stmt = stmt.where(Shoulder.manager_id == p.manager_id)
    return list(session.scalars(stmt))


class NeedsLogin(Exception):
    """ログインへ送る。**401 を返さない**——ブラウザにヘッダは付けられないので、
    401 を見せても人には何もできない。"""

    def __init__(self, next_url: str = "/admin/"):
        self.next_url = next_url


def _with_ip(request: Request, cfg: Config, p: Principal) -> Principal:
    """接続元を刻む。**API と同じ判定**（`deps.client_ip`）を使う。"""
    from dataclasses import replace

    from arkhe.auth.deps import client_ip

    return replace(p, ip=client_ip(request, cfg))


def admin_principal(request: Request, session: Db, cfg: Config) -> Principal:
    """管理画面の主体。**入口は設定で選ぶ**（`ARKHE_ADMIN_LOGIN`）。

    どの入口でも、行き着く先は API と同じ `Principal`。到達範囲の判定も同じ。
    違うのは「誰であるかをどう確かめたか」だけ。
    """
    # 1) セッション Cookie（oidc / proxy でログイン済み）
    if cfg.admin_login != "bearer":
        raw = request.cookies.get(sess.COOKIE, "")
        claims = sess.read(raw, secret=cfg.session_secret) if raw else None
        if claims:
            try:
                return _with_ip(request, cfg, login_flow.by_subject(
                    session, claims["sub"], mechanism=claims.get("via", "")
                ))
            except AuthError:
                pass  # 登録が消えた・無効化された。ログインし直させる

    # 2) 前段の認証プロキシ
    if cfg.admin_login == "proxy":
        try:
            return _with_ip(request, cfg, login_flow.from_proxy(session, cfg, request.headers))
        except AuthError as exc:
            raise NeedsLogin() from exc

    # 3) Bearer（自動化・curl。bearer モードではこれだけ）
    try:
        return _with_ip(request, cfg, authenticate(bearer(request), session, cfg))
    except AuthError:
        if cfg.admin_login in ("oidc", "password"):
            raise NeedsLogin(str(request.url.path)) from None
        raise


AdminPrincipal = Annotated[Principal, Depends(admin_principal)]


class _ShoulderChoice:
    """採番フォームの選択肢。テンプレートに ORM を直接渡さないための薄い型。"""

    def __init__(self, s: Shoulder):
        self.naan = s.naan
        self.shoulder = s.shoulder
        self.manager_name = s.manager.name if s.manager else ""


#: 採番フォームの種別の候補。**DataCite の `resourceTypeGeneral`** を採る
#: （この分野で通っている語彙で、自前定義しない）。**縛りではなく候補**——
#: ERC の `what` は語彙を定めないので、一覧に無いものは直接入力できる。
RESOURCE_TYPES = (
    "Audiovisual", "Award", "Book", "BookChapter", "Collection",
    "ComputationalNotebook", "ConferencePaper", "ConferenceProceeding", "DataPaper",
    "Dataset", "Dissertation", "Event", "Image", "Instrument", "InteractiveResource",
    "Journal", "JournalArticle", "Model", "OutputManagementPlan", "PeerReview",
    "PhysicalObject", "Preprint", "Project", "Report", "Service", "Software", "Sound",
    "Standard", "StudyRegistration", "Text", "Workflow", "Other",
)


def _mintable(session: Session, p: Principal) -> list[_ShoulderChoice]:
    return [_ShoulderChoice(s) for s in _visible_shoulders(session, p) if s.can_mint_here]


def _redirect(to: str) -> RedirectResponse:
    """POST の後は 303 で GET に戻す（再読み込みで二重に実行させない）。"""
    return RedirectResponse(to, status_code=303)


def _page(request: Request, principal: Principal, template: str, page: str, **extra):
    return _remember_lang(
        request,
        templates.TemplateResponse(request, template, _ctx(request, principal, page, **extra)),
    )
