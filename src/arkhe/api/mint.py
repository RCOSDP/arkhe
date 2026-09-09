"""採番・更新の API。**shoulder は主体から引き、リクエストでは広げられない。**

到達範囲の判定は `domain.authz` が一手に引き受ける。ここは HTTP の形を整えるだけ。
"""

from __future__ import annotations

from fastapi import APIRouter, Response, Security
from sqlalchemy import select

from arkhe import errors
from arkhe.api.schemas import (
    ArkOut,
    BulkImportIn,
    BulkImportOut,
    BulkMintIn,
    BulkMintOut,
    BulkQueryIn,
    BulkQueryOut,
    BulkUpdateIn,
    BulkUpdateOut,
    HoldIn,
    HoldReleaseIn,
    ImportIn,
    MintIn,
    PatchIn,
    RegisterIn,
    TombstoneIn,
    UpdateIn,
)
from arkhe.api.token import scheme as oauth2_scheme
from arkhe.arkspec.naming import ArkParseError, parse_ark
from arkhe.arkspec.shoulder import split_shoulder
from arkhe.auth.deps import Config, CurrentPrincipal, Db
from arkhe.db.models import Ark, MintReceipt, Shoulder
from arkhe.domain import admin_ops, authz, minting
from arkhe.domain.queries import ark_key_from_input

router = APIRouter(prefix="/api", tags=["ark"])


def needs(scope: str) -> list:
    """**この口が要求する scope を宣言する。** 仕様書の security requirement に出る
    ——`{"oauth2": ["ark:mint"]}` のように、口ごとに何が要るかが機械可読になる。

    **弾くのは本体の `require_scope` のまま。** 宣言と検査が 2 か所に分かれるので、
    一致することを検査で固定してある（`test_宣言した scope と検査する scope が一致する`）。

    scope を載せるのは oauth2 の要求だけである。`bearer` は `type: http` で、
    **OpenAPI では oauth2 以外のスキームに scope を書けない**（空配列でなければ
    ならない）——ここで `Security` に包む対象を `oauth2_scheme` に限る理由。
    """
    return [Security(oauth2_scheme, scopes=[scope])]



# --------------------------------------------------------------- 仕様書の文面
#
# **公開する OpenAPI は英語**——読者はこの台帳の外にいて、日本語を読むとは限らない。
# docstring は日本語のまま残す。**あれは実装を読む人のためのもの**で、仕様書の
# 読者とは別。FastAPI は `description` を渡すと docstring より優先するので、
# 出す文面はここに置き、コードの説明は下の docstring に残る。

E_MINT = """\
**Mint one new ARK.** Requires `ark:mint`.

The shoulder defaults to the organisation's own. Naming one in the request only asks
whether it lies inside the caller's registered reach — it never widens it.

**Send a `request_id` and a resend will not mint again.** The same principal resending
the same `request_id` gets back the ARK minted the first time, so a lost response does
not leave a dead identifier behind. The status code says which happened:

    201  minted
    200  returned an earlier minting (a resend)

**An ARK is never reissued**, so minting cannot be undone.
"""

E_BULK_MINT = """\
**Mint in bulk.** Requires `ark:mint`. One request holds at most `ARKHE_BULK_LIMIT`
rows (1000 by default).

**One row out of reach and nothing is created.** Reach and shoulder are checked for
every row before any minting, so a half-minted batch cannot be left behind.

**The answer keeps the order of the input**, because resent rows (a `request_id`
already seen) and new ones are mixed and the caller has to line them up. `created` and
`replayed` carry the two counts; all resends answer 200, one new minting makes it 201.

Give each row a `request_id` and **an interrupted batch can be sent again as it is** —
rows already minted are skipped. **The same `request_id` twice inside one request still
mints once**: it is one request, so it gets one number.
"""

E_REGISTER = """\
**Register a row for a qualified ARK** — an existing base name plus a qualifier.

Suffix passthrough already covers a reference of any depth; this endpoint **overrides
that default at a single point**: "this subtree lives in another store", "this
derivative sits elsewhere".

**It requires `ark:mint`.** Nothing is minted, but a new resolvable identifier does
appear, so it must not be handed to a principal that holds update rights alone.
"""

E_IMPORT = """\
**Record an ARK that was minted elsewhere.** Requires `ark:import`.

Minting does not let a caller choose the name; this does, and that single difference is
why it has its own scope and its own checks. It exists so that **a name minted inside a
closed network can later be published under the same identifier** — without it, opening
an embargoed object means issuing a different ARK, and every reference handed out while
it was closed dies.

Three things are checked, and none of them can be waived:

* the shoulder is **delegated** — importing into a namespace this ledger mints in could
  collide with its own minter, and a name minted elsewhere only exists because the
  namespace was delegated in the first place;
* the name falls **inside that shoulder**;
* the **check digit verifies** — for a name that arrives from outside, that is the only
  evidence there is that it was not mistyped.

A name already in the ledger is refused rather than overwritten, exactly as minting is.
"""

E_IMPORT_BULK = """\
**Import a whole delegated namespace at once.** Requires `ark:import`. One request holds
at most `ARKHE_BULK_LIMIT` rows.

This is the shape the closed-network case actually needs: a delegate hands over the
names it minted, and they arrive together. Each row goes through exactly the same checks
as a single import, and **one row that fails any of them means nothing is created** — a
half-imported namespace is worse than none, because the names that did land cannot be
taken back.

Rows may span several shoulders, as long as every one of them is delegated and within
the caller's reach.
"""

E_PATCH = """\
**Update the fields you send, and leave the rest alone.** Requires `ark:update`.

`PUT` replaces the record: every field you omit takes its default, so repointing an ARK
with `{"ark": …, "url": …}` alone **empties its title, its who and its when**. That is
correct for a replacement and wrong for what people actually do most of the time, which
is move an object.

Sending a field as `""` clears it; not sending it leaves it untouched. Both are needed,
which is why this is not simply "ignore empty strings".
"""

E_UPDATE = """\
Update an existing ARK. **The manager of the target's shoulder is checked.**
"""

E_BULK_UPDATE = """\
Update in bulk. Rows are matched by key, and **nothing is applied unless every row
is found and in reach** — there is no partial application.
"""

E_TOMBSTONE = """\
**Declare that the object is gone.** The ARK is not deleted.

Under NR (no re-assignment) an identifier cannot be removed; only reachability can be.
**The identifier and its metadata stay**, and the resolver answers with the description.

**Its scope is separate from `ark:update`.** A tombstone says "this is gone", not "this
is elsewhere" — a different meaning with different consequences. It is hard to walk back
and it is public, so it does not belong to routine writers such as an ingest batch.
"""

E_HOLD = """\
**Stop redirecting, temporarily.** Resolution is not stopped — the description keeps
being returned.

For when a delegate is down, a wrong target went out, or an object is moving: you have
to stop quickly without killing the identifier. `404` would be a lie (the identifier
exists) and `503` makes a permanent identifier look broken, so a hold answers **200 with
the description**, the same path a tombstone takes.

**Its scope is separate from `ark:update`**, because stopping is a different decision
from repointing and the reason is published. It is separate from a tombstone too: that
is a permanent declaration, while this is **dated, and keeps the previous target**.
"""

E_HOLD_RELEASE = """\
Lift a hold before its expiry. **An expired hold lifts itself by the clock**, so this
is only for lifting one early.
"""

E_BULK_QUERY = """\
Look up ARKs in bulk. **Reads are confined to the caller's reach**, exactly as writes
are.
"""

def _key(raw: str) -> str:
    """`ark:99999/x9tn1qkq2g7` でも、旧形式の `ark:/99999/x9tn1qkq2g7` でも、
    `99999/x9tn1qkq2g7` でも受ける。

    **正規化は `domain.queries` の 1 か所**（画面・CLI・API が同じ式を通る）。
    ここで独自に書くと、API では触れる ARK が CLI では 404 になる。
    """
    try:
        return ark_key_from_input(raw)
    except ValueError as exc:
        raise authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc)) from exc



def _qualifier_error(exc: Exception) -> authz.Invalid:
    """`register_qualified` が投げた理由を符号に写す。

    **符号はドメインの側で決めない。** あちらは HTTP も API の語彙も知らない層
    なので、例外の型を見てここで符号を選ぶ。
    """
    if isinstance(exc, minting.AlreadyRegistered):
        return authz.Invalid(errors.ALREADY_REGISTERED, ark=str(exc))
    if isinstance(exc, minting.QualifierForm):
        return authz.Invalid(errors.QUALIFIER_FORM)
    if isinstance(exc, minting.QualifierOutsideBase):
        return authz.Invalid(errors.QUALIFIER_OUTSIDE_BASE, qualifier=exc.qualifier)
    if isinstance(exc, minting.NameTooLong):
        return authz.Invalid(errors.NAME_TOO_LONG, length=exc.length, limit=exc.limit)
    return authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc))




def _parse(raw: str):
    try:
        return parse_ark(raw)
    except ArkParseError as exc:
        raise authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc)) from exc


def _check_importable(shoulder, name: str, raw: str) -> None:
    """**書かずに済む検査を、書く前に済ませる。**

    委譲されているか・名前がその内側か・検査桁が合うか。ここを通らない行が
    1 つでもあれば、一括は 1 件も入れない。
    """
    try:
        minting.check_importable(shoulder, name)
    except minting.NotDelegated as exc:
        raise authz.Forbidden(
            errors.IMPORT_SHOULDER_NOT_DELEGATED, shoulder=exc.shoulder, status=exc.status
        ) from exc
    except minting.BadCheckDigit as exc:
        # **呼び出し側が送った文字列を返す。** 正規化後の名前を見せても、
        # 打ち間違いを探している人の手元とは一致しない。
        raise authz.Invalid(errors.IMPORT_CHECK_DIGIT, ark=raw) from exc
    except minting.OutsideShoulder as exc:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=exc.name, naan=exc.naan
        ) from exc
    except minting.NameTooLong as exc:
        raise authz.Invalid(errors.NAME_TOO_LONG, length=exc.length, limit=exc.limit) from exc


def _insert_import(session, principal, shoulder, row) -> Ark:
    """検査を通した 1 件を入れる。衝突だけはここでしか分からない（E1）。"""
    authz.assert_within_quota(session, principal)
    try:
        return minting.import_minted(
            session,
            shoulder=shoulder,
            name=_parse(row.ark).name,
            created_by=principal.client_id,
            **row.writable(),
        )
    except minting.AlreadyRegistered as exc:
        raise authz.Invalid(errors.ALREADY_REGISTERED, ark=str(exc)) from exc


def _import_one(session, principal, row) -> Ark:
    """取り込み 1 件。**単体でも一括でも、通る検査は同じ。**

    ドメイン側の例外を符号に写すのはここ。`domain/` は HTTP も API の語彙も
    知らない層なので、対応表を上に置く。
    """
    parsed = _parse(row.ark)
    shoulder = _shoulder_holding(session, principal, parsed)
    _check_importable(shoulder, parsed.name, row.ark)
    return _insert_import(session, principal, shoulder, row)


def _shoulder_holding(session, principal, parsed):
    """取り込む名前が属する shoulder を、**主体の到達範囲の内側から**選ぶ。

    first-digit 規約で名前から shoulder を切り出し、その 1 つだけを見る
    ——**総当たりで「入る shoulder」を探さない**。探すと、委譲していない
    名前空間に名前を滑り込ませる余地ができる。
    """
    prefix = split_shoulder(parsed.name)[0]
    if not prefix:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=parsed.name, naan=parsed.naan
        )
    shoulder = session.scalar(
        select(Shoulder).where(
            Shoulder.naan == parsed.naan, Shoulder.shoulder == f"/{prefix}"
        )
    )
    if shoulder is None:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=parsed.name, naan=parsed.naan
        )
    # **2 つ別のことを確かめる。**
    #   1. この台帳がその NAAN の権威を持つか（取り次いでいるだけの名前空間に
    #      名前を引き受けてはいけない）
    #   2. この主体がその shoulder に届くか（**上位の権威は下位を覆う**)
    authz.assert_naan_is_ours(session, parsed.naan)
    authz.assert_reaches_shoulder(session, principal, shoulder)
    return shoulder


def _replay(session, principal, request_id: str) -> Ark | None:
    """F4: 同じ `request_id` の採番が既にあれば、その ARK を返す。"""
    if not request_id:
        return None
    key = session.scalar(
        select(MintReceipt.ark).where(
            MintReceipt.client_id == principal.client_id,
            MintReceipt.request_id == request_id,
        )
    )
    return session.get(Ark, key) if key else None


def _keep_receipt(session, principal, request_id: str, ark: Ark) -> None:
    """F4: 控えを残す。**採番と同じトランザクションで**——別にすると、控えを書く前に
    落ちたときに「採番したが再送で二重に採番される」が起きる。"""
    if request_id:
        session.add(
            MintReceipt(client_id=principal.client_id, request_id=request_id, ark=ark.ark)
        )


def _apply(ark: Ark, data: dict, principal) -> Ark:
    for field, value in data.items():
        if field == "ark":
            continue
        setattr(ark, "metadata_" if field == "metadata" else field, value)
    ark.updated_by = principal.client_id
    return ark


# ------------------------------------------------------------------- 採番


@router.post(
    "/mint",
    dependencies=needs("ark:mint"),
    response_model=ArkOut,
    status_code=201,
    description=E_MINT,
    # **再送は 201 では返らない。** 宣言しないと、生成クライアントが 200 を
    # 「知らない応答」として扱う。
    responses={200: {"model": ArkOut, "description": "returned an earlier minting (a resend)"}},
)
def mint(body: MintIn, principal: CurrentPrincipal, session: Db, response: Response):
    """**新しい ARK を 1 つ発行する。** `ark:mint` が要る。

    採番先の shoulder は、省略すれば組織の既定。指定した場合は**その主体の到達範囲に
    含まれるかを検証するだけ**で、範囲を広げる手段にはならない。

    **`request_id` を付けると再送で番号が増えない**（F4）。同じ主体が同じ
    `request_id` で送り直すと、最初に採番した ARK をそのまま返す——応答だけが失われた
    ときに死んだ番号が増えるのを防ぐ。区別は状態符号に出る:

      201  採番した
      200  以前の採番を返した（再送）

    ARK は**振り直せない**。採番は取り消せない操作である。
    """
    authz.require_scope(principal, "ark:mint")
    # F4: **再送なら採番しない。** 応答が失われただけのときに番号を増やさない。
    if (existing := _replay(session, principal, body.request_id)) is not None:
        response.status_code = 200
        return ArkOut.of(existing)
    shoulder = authz.shoulder_for(session, principal, body.shoulder or None)
    authz.assert_shoulder_mintable(shoulder)
    authz.assert_within_quota(session, principal)
    ark, _ = minting.mint(
        session, shoulder=shoulder, created_by=principal.client_id, **body.writable()
    )
    _keep_receipt(session, principal, body.request_id, ark)
    authz.audit(session, principal, "mint", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/mint/bulk",
    dependencies=needs("ark:mint"),
    response_model=BulkMintOut,
    status_code=201,
    description=E_BULK_MINT,
    responses={200: {"model": BulkMintOut, "description": "every row was a resend"}},
)
def bulk_mint(
    body: BulkMintIn, principal: CurrentPrincipal, session: Db, cfg: Config, response: Response
):
    """**まとめて採番する。** `ark:mint` が要る。1 リクエストの上限は
    `ARKHE_BULK_LIMIT`（既定 1000）。

    **1 件でも範囲外なら、何も作らない。** 到達範囲と shoulder の検証を全件先に済ませて
    から採番するので、途中まで採番された状態は残らない。

    **応答は入力の順序で返す。** 再送ぶん（`request_id` が既知の行）と新規ぶんが混ざる
    ので、並びを保って呼び出し側が突き合わせられるようにしてある。`created` と
    `replayed` にそれぞれの件数が出る。全件が再送なら 200、1 件でも採番していれば 201。

    行ごとに `request_id` を付けておけば、**切れた塊をそのまま送り直せる**——
    採番済みの行は飛ばされる。**同じ `request_id` が 1 回の要求に複数あるときも
    1 件にまとめる**（同じ依頼を 2 度書いたのだから、番号も 1 つ）。
    """
    authz.require_scope(principal, "ark:mint")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)

    # F4: **既に採番済みの行は飛ばす。** 切れた塊をそのまま再送できるようにする。
    wanted = {r.request_id for r in rows if r.request_id}
    replayed: dict[str, Ark] = {}
    if wanted:
        for rid, key in session.execute(
            select(MintReceipt.request_id, MintReceipt.ark).where(
                MintReceipt.client_id == principal.client_id,
                MintReceipt.request_id.in_(wanted),
            )
        ).all():
            replayed[rid] = session.get(Ark, key)

    # **同じ塊のなかの重複も、再送と同じ扱いにする。** 控えは (client, request_id) で
    # 一意なので、同じ `request_id` の行を 2 つ採番すると控えを 2 度書くことになり、
    # commit で IntegrityError——500 で落ち、1 件も採番されない。同じ `request_id` は
    # 「同じ 1 つの依頼」という意味なのだから、**1 件だけ採番して両方に同じ ARK を返す。**
    fresh, seen = [], set()
    for r in rows:
        if r.request_id in replayed or r.request_id in seen:
            continue
        if r.request_id:
            seen.add(r.request_id)
        fresh.append(r)
    # 到達範囲の検証を**先に全件済ませる**（1 件でも範囲外なら何も作らない）。
    shoulders = [authz.shoulder_for(session, principal, r.shoulder or None) for r in fresh]
    for sh in shoulders:
        authz.assert_shoulder_mintable(sh)
    authz.assert_within_quota(session, principal, len(fresh))

    minted: dict[int, Ark] = {}
    for sh, row in zip(shoulders, fresh, strict=True):
        ark, _ = minting.mint(
            session, shoulder=sh, created_by=principal.client_id, **row.writable()
        )
        _keep_receipt(session, principal, row.request_id, ark)
        minted[id(row)] = ark
    authz.audit(session, principal, "bulk_mint", count=len(minted))
    session.commit()

    # **入力の順序で返す。** 再送ぶんと新規ぶんが混ざるので、呼び出し側が
    # 突き合わせられるように並びを保つ。
    by_request = {r.request_id: minted[id(r)] for r in fresh if r.request_id}
    made = [
        replayed.get(r.request_id) or by_request.get(r.request_id) or minted[id(r)]
        for r in rows
    ]
    if not minted:
        response.status_code = 200
    return BulkMintOut(
        minted=[ArkOut.of(a) for a in made], created=len(minted), replayed=len(made) - len(minted)
    )


@router.post(
    "/register",
    dependencies=needs("ark:mint"),
    response_model=ArkOut,
    status_code=201,
    description=E_REGISTER,
)
def register(body: RegisterIn, principal: CurrentPrincipal, session: Db):
    """B4: **既存 ARK に修飾子を付けた行を登録する。**

    既定では suffix passthrough が任意の深さを賄う。この口は**その既定を 1 点だけ
    上書きする**ためにある——「このサブツリーだけ別ストレージ」「この変換版だけ別の所在」。

    **`ark:mint` を要求する。** 採番ではないが、**新しく解決可能な識別子が増える**
    ので、更新権限しか持たない主体に渡してはいけない。
    """
    authz.require_scope(principal, "ark:mint")
    base = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, base)
    authz.assert_shoulder_mintable(base.shoulder)
    authz.assert_within_quota(session, principal)
    try:
        ark = minting.register_qualified(
            session,
            base=base,
            qualifier=body.qualifier,
            created_by=principal.client_id,
            **body.writable(),
        )
    except (minting.AlreadyRegistered, ValueError) as exc:
        raise _qualifier_error(exc) from exc
    authz.audit(session, principal, "register_qualified", ark.ark)
    session.commit()
    return ArkOut.of(ark)


# ------------------------------------------------------------------- 更新


@router.post(
    "/import",
    dependencies=needs("ark:import"),
    response_model=ArkOut,
    status_code=201,
    description=E_IMPORT,
)
def import_ark(body: ImportIn, principal: CurrentPrincipal, session: Db):
    """**外で採番された ARK を、この台帳に取り込む。**

    `federation.md` の C-2（閉じた側で採番）から C-1（公開側が名前と記述を持つ）
    へ移るための口。**これが無いと、閉じた期間に配った名前をそのまま公開できない。**

    scope を `ark:mint` と分けてあるのは、**名前を呼び出し側が選ぶ**から。採番は
    「番号をもらう」操作で、取り込みは「この番号だと言い張る」操作である。
    """
    authz.require_scope(principal, "ark:import")
    ark = _import_one(session, principal, body)
    # **採番とは別の語で記録する。** あとから「どれが外から来たか」を追えるように。
    authz.audit(session, principal, "import", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/import/bulk",
    dependencies=needs("ark:import"),
    response_model=BulkImportOut,
    status_code=201,
    description=E_IMPORT_BULK,
)
def bulk_import(body: BulkImportIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """**shoulder ごと引き取る。** 閉じた側が採った名前を、まとめて渡してもらう形。

    **1 件でも通らなければ何も作らない**（M5 と同じ）。中途半端に入った名前は
    引っ込められないので、部分適用は採番より重い事故になる。
    """
    authz.require_scope(principal, "ark:import")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)

    # **全件の検査を先に済ませてから入れる**（採番の一括と同じ順序）。途中で
    # 落ちるとロールバックには任せられる形でも、**入れてから気づく**のは避ける
    # ——取り込みは名前を増やす操作で、増えた名前は引っ込められない。
    checked = [(_shoulder_holding(session, principal, _parse(row.ark)), row) for row in rows]
    for shoulder, row in checked:
        _check_importable(shoulder, _parse(row.ark).name, row.ark)

    out: list[Ark] = [_insert_import(session, principal, sh, row) for sh, row in checked]
    authz.audit(session, principal, "bulk_import", count=len(out))
    session.commit()
    return BulkImportOut(imported=[ArkOut.of(a) for a in out], count=len(out))


@router.put(
    "/update",
    dependencies=needs("ark:update"),
    response_model=ArkOut,
    description=E_UPDATE,
)
def update(body: UpdateIn, principal: CurrentPrincipal, session: Db):
    """既存 ARK を更新する。**対象の shoulder の manager を照合する**（M3）。"""
    authz.require_scope(principal, "ark:update")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    _apply(ark, body.model_dump(), principal)
    # **行き先の履歴は誰が行っても残す**（監査は NAAN 単位以上しか残さない）。
    authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "update", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.patch(
    "/update",
    dependencies=needs("ark:update"),
    response_model=ArkOut,
    description=E_PATCH,
)
def patch(body: PatchIn, principal: CurrentPrincipal, session: Db):
    """**送られた項目だけを書き換える。** `PUT` と同じ権限・同じ検証を通る。

    `PUT` が要るのは「レコードをこの内容にする」と言い切れるときで、実際には
    **行き先だけを付け替えたい**ほうがずっと多い。そこで `PUT` を送ると、
    省いた記述が既定値で上書きされて消える——`?info` が答えるべき中身が、
    行き先の付け替えのついでに失われる。

    空文字を**送れば**消える。送らなければ触らない。この 2 つを区別できないと、
    値を消す手段が無くなる。
    """
    authz.require_scope(principal, "ark:update")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    _apply(ark, body.sent(), principal)
    authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "patch", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.put(
    "/update/bulk",
    dependencies=needs("ark:update"),
    response_model=BulkUpdateOut,
    description=E_BULK_UPDATE,
)
def bulk_update(body: BulkUpdateIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M5: **辞書で引き当て、部分適用しない。**"""
    authz.require_scope(principal, "ark:update")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)
    keys = [_key(r.ark) for r in rows]
    found = authz.fetch_for_update(session, principal, keys)  # 欠けが 1 件でもあれば 404
    for key, row in zip(keys, rows, strict=True):
        ark = found[key]
        authz.assert_may_touch(session, principal, ark)
        before = ark.url
        _apply(ark, row.model_dump(), principal)
        authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "bulk_update", count=len(rows))
    session.commit()
    return BulkUpdateOut(updated=len(rows))


@router.put(
    "/tombstone",
    dependencies=needs("ark:tombstone"),
    response_model=ArkOut,
    description=E_TOMBSTONE,
)
def tombstone(body: TombstoneIn, principal: CurrentPrincipal, session: Db):
    """**対象が失われたと宣言する。** ARK は削除しない。

    `NR`（No Re-assignment）を宣言している以上、識別子は消せない。消せるのは
    対象への到達性だけで、**識別子とメタデータは残る**。

    **scope を `ark:update` と分けてある。** 墓碑化は「どこにあるか」ではなく
    「もう無い」という宣言で、意味も影響も違う。取り消しにくく、公開されると
    信頼に関わるので、投入バッチのような日常の書き手には渡さない。
    """
    authz.require_scope(principal, "ark:tombstone")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    # url が空なら、リゾルバが記述そのものを返す（D6 と同じ経路）。
    ark.url = body.url
    if body.commitment:
        ark.commitment = body.commitment
    ark.updated_by = principal.client_id
    authz.record_change(session, principal, ark, action="tombstone", before_url=before)
    authz.audit(session, principal, "tombstone", ark.ark)
    session.commit()
    return ArkOut.of(ark)


# --------------------------------------------------------------- 転送の保留


@router.put(
    "/hold",
    dependencies=needs("ark:hold"),
    response_model=ArkOut,
    description=E_HOLD,
)
def hold(body: HoldIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """**転送を一時的に止める。** 解決は止めない——記述は返り続ける。

    委譲先が落ちた、間違った行き先を配ってしまった、対象が移動中——急いで
    止めたいが、識別子は殺したくない場面のためのもの。`404` は嘘（その識別子は
    存在する）で、`503` は識別子が壊れて見えるので、**`200` と記述**を返す
    経路（D6・tombstone と同じ）に乗せる。

    **scope を `ark:update` と分けてある。** 止めるのは「どこにあるか」を書き換える
    のとは別の判断で、公開の口に理由が出る。tombstone とも分ける——あちらは
    「もう無い」という恒久の宣言で、こちらは**期限つきで、元の行き先を残す**。
    """
    authz.require_scope(principal, "ark:hold")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    admin_ops.set_hold(
        session, principal, kind="ark", key=ark.ark,
        until=body.until, reason=body.reason, max_days=cfg.hold_max_days,
    )
    session.commit()
    return ArkOut.of(ark)


@router.put(
    "/hold/release",
    dependencies=needs("ark:hold"),
    response_model=ArkOut,
    description=E_HOLD_RELEASE,
)
def hold_release(body: HoldReleaseIn, principal: CurrentPrincipal, session: Db):
    """期限を待たずに保留を外す。**期限切れは時計が勝手に外す**ので、これは前倒し。"""
    authz.require_scope(principal, "ark:hold")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    admin_ops.release_hold(session, principal, kind="ark", key=ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/query",
    dependencies=needs("ark:read"),
    response_model=BulkQueryOut,
    description=E_BULK_QUERY,
)
def bulk_query(body: BulkQueryIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M4: **読み取りも到達範囲に絞る**（arklet は認可を一切していなかった）。"""
    authz.require_scope(principal, "ark:read")
    keys = [_key(a) for a in body.data[: cfg.bulk_limit]]
    arks = authz.visible_arks(session, principal, keys)
    return BulkQueryOut(data=[ArkOut.of(a) for a in arks])
