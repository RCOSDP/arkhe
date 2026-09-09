"""解決。**resolver プロセスの唯一の口。** 採番も管理もここには無い。

決定は `domain.resolution.resolve()` が行い、ここは HTTP の形に写すだけ。
"""

from __future__ import annotations

import os
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from arkhe import errors
from arkhe.api import i18n
from arkhe.arkspec.naming import ArkParseError, compact_ark, parse_ark
from arkhe.auth.deps import Config, Db
from arkhe.db.models import Manager, Naan, Shoulder, utcnow
from arkhe.db.repository import SqlArkRepository
from arkhe.domain.resolution import Inflection, Outcome, is_followable, resolve

router = APIRouter(tags=["resolve"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: ERC が定める「値が無いときの符号」。**空欄で済ませてはいけない。**
#: draft-kunze-erc-01: 値を得られなかったときは、その理由を示す標準値を置くこと。
#: 空にすると「まだ入れていない」と「そもそも無い」が区別できなくなる。我々は
#: どちらか判別できないので一律 `(:unav)` を使う——`(:unas)`（未割当）や
#: `(:none)`（元から無い）を騙るより正直。
UNAVAILABLE = "(:unav)"

DC_FIELDS = ("type", "identifier", "format", "relation", "source")

#: 生の URI を渡すヘッダ名（`?` の判定に使う）。前段で立てているときだけ設定する。
RAW_URI_HEADER = os.environ.get("ARKHE_RAW_URI_HEADER", "")

#: 永続性の水準の表示名は `api/i18n` の `ci.*` から採る。**画面の言語で出す**
#: ——`?info` は公開の口で、ARK は世界中から引かれる。



# --------------------------------------------------------------- 仕様書の文面
#
# **公開する OpenAPI は英語**——読者はこの台帳の外にいる。docstring は日本語の
# まま残す（実装を読む人のためのもの）。FastAPI は `description` を優先する。

E_WELL_KNOWN = """\
**Tells a client that this host has an ARK resolver** (draft-kunze-ark-42 §5.6).

§5.6 registers `ark` in the Well-Known URIs registry (RFC 8615) and defines the answer
as **plain text holding the resolver's root path, ending in `/`** — append a compact ARK
to it and you have a resolution request. **A client that sends no `Accept`, or `*/*`,
gets that**; answering such a client with JSON would make the host look, to anyone
reading the specification, as though it had no ARK resolver at all.

`Accept: application/json` returns arkhe's own inventory instead: **where to go when a
NAAN's minting happens elsewhere** (`Naan.minter` / `Shoulder.minter`), and any
namespace whose redirection is on hold.

Both representations carry `Vary: Accept`.
"""

E_RESOLVE = """\
**Resolve an ARK. No authentication.** Both `ark:99999/x9tn1qkq2g7` and the older
`ark:/99999/x9tn1qkq2g7` are accepted, in any letter case.

There is more than one way to answer, and **keeping the identifier alive comes first on
every path**:

    302  redirect to the target (the usual case; a shoulder's delegation template may
         name 301, 303 or 307 instead)
    200  return a description — for `?info` and `??`, for a target a browser cannot
         open (`urn:isbn:…`), for an empty target, for a tombstone, and while a hold
         is on
    404  not in this ledger and nowhere to forward to. **`?info` on an unknown name is
         still a 404** — there is nothing to say about a name we do not know
    400  not readable as an ARK

**A hold is not a 404.** The identifier exists; we are only declining to hand out its
address for now, so the reason and the expiry come back with a 200. **The same holds for
a tombstone** — saying "it was lost" is not the same as saying "it never was".

An ARK that is only a NAAN (`ark:12345`) answers with what can be said about that NAAN.
An unknown NAAN is forwarded to the global resolver (`ARKHE_GLOBAL_RESOLVER`, n2t.net by
default).

Every answer this resolver gives about an identifier carries the THUMP headers of §5.2
(`THUMP-Status` and `Link: <…>; rel="describes"`); redirects carry neither.
"""


def _inflection(request: Request) -> Inflection:
    """inflection を判定する。

    | 記法 | クエリ文字列 | 返すもの |
    | --- | --- | --- |
    | `?` | `""`（**生の URI で見分ける**） | ERC/ANVL の簡潔な記述 |
    | `??` | `"?"` | 永続性宣言（C4） |
    | `?info` | `"info"` | 人間可読の記述（**仕様上の必須**） |
    | `?json` | `"json"` | 機械可読 |

    **裸の `?` はクエリ文字列だけでは見分けられない。** `…/name?` も `…/name` も
    `query_string` は空になる。これは ASGI でも同じで、生の URI を渡すサーバ
    （gunicorn の `RAW_URI` 相当）が無い限り復元できない。**仕様上 `?` は
    optional** なので、見分けられない環境では inflection 無しとして扱う——
    そこで壊れるものは無い（`??` は `query_string` が `"?"` になるので効く）。

    生 URI を渡すサーバの下では `ARKHE_RAW_URI_HEADER` にヘッダ名を設定すると
    `?` も拾える（例: nginx で `X-Raw-URI` を立てる）。
    """
    # **先頭の要素だけを見る。** `?info` はクエリ文字列そのものが inflection なので、
    # 言語の切り替えは `?info&lang=en` と書くしかない——`&` の手前で切って読む。
    qs = request.url.query.split("&", 1)[0]
    if qs == "?":
        return Inflection.POLICY
    if qs == "info":
        return Inflection.INFO
    if qs == "json":
        return Inflection.JSON
    if not qs:
        raw = request.headers.get(RAW_URI_HEADER, "") if RAW_URI_HEADER else ""
        if raw.endswith("?"):
            return Inflection.BRIEF
    return Inflection.NONE


def _raw_ark_path(request: Request) -> str:
    """**%-エンコードを保ったままの経路**を返す。

    A4。`request.url.path`（＝ ASGI の `scope["path"]`）は**サーバが先に復号して
    いる**ので、`%2F` が `/` に、`%7D` が `}` になって届く。これを鵜呑みにすると:

    - `x54%2Fc2`（区切りではない `/` を隠した 1 つの名前）が `x54/c2`
      （`x54` に含まれる `c2`）に化ける——**別の識別子**になり、祖先 passthrough が
      別レコードの行き先を継ぐ
    - `}` は §3.1 の文字集合に無い。`%7D` は `}` を運ぶ唯一の合法な形なので、
      復号した文字列は**そもそも ARK として成立しない**
    - 他所へ取り次ぐときは、**書き換わった ARK を転送先に渡す**ことになる

    仕様（draft-kunze-ark-42 §3.2）は "no %-encoded character should ever appear in
    an ARK in its decoded form" と、これを名指しで禁じている。

    ASGI は生の経路を `scope["raw_path"]` に残しているので、そちらを優先する。
    **前段が潰す構成では戻せない**——nginx なら `proxy_pass` にパスを書かない
    （書くと再エンコードされる）、Apache なら `AllowEncodedSlashes NoDecode` が要る。
    """
    raw = request.scope.get("raw_path")
    if not raw:
        return request.url.path
    # サーバによっては query も入る。`?` は名前の中では `%3F` なので、素の `?` で切れる。
    raw = raw.split(b"?", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # 生バイトが UTF-8 でない。**捏造せず**、復号済みの経路に落とす。
        return request.url.path


def _anvl(pairs) -> str:
    """ERC/ANVL 形式。**ARK が伝統的に `?` / `??` で返してきた形。**

    実測: `n2t.net/ark:/13030/m5s75pdz??` は `text/plain` で `erc.who:` /
    `erc.what:` / `erc.when:` を返す。JSON ではない。

    **空文字を渡した要素は `(:unav)` で必ず出し、`None` を渡した要素は行ごと省く。**
    符号を義務づけられているのは **kernel の 4 要素（who / what / when / where）だけ**
    で、任意ラベルまで `(:unav)` で埋めると、別のところで分かっている事実を
    「不明」と偽ることになる。
    """
    lines = ["erc:"]
    for key, value in pairs:
        if value is None:
            continue
        text = str(value).strip() or UNAVAILABLE
        lines.append(f"{key}: " + text.replace("\n", "\n    "))
    return "\n".join(lines) + "\n"


#: C7: THUMP の版。仕様（draft-kunze-ark-42 §5.2）の応答例が `THUMP-Status: 0.6
#: 200 OK` を示しており、[THUMP] は draft-kunze-thump-03 を指している。
THUMP_VERSION = "0.6"


def _thump(status: int, requested: str = "") -> dict[str, str]:
    """THUMP の応答ヘッダ（§5.2）。

    C7。仕様の応答例:

        S: THUMP-Status: 0.6 200 OK
        S: Link: </ark:67531/metadc107835> rel="describes";

    `Link` の役目は仕様に書いてある——**inflection を知らない受信者に対して、
    この応答が「修飾の付いていない ARK」を記述したものだと示す**。これが無いと、
    `?info` の応答は「その URL 自体の表現」と読まれる。

    **`rel` の書き方は仕様の例に従わない。** 例は `<…> rel="describes";` だが、
    RFC 8288 のリンク値は `<URI>; rel="…"` で、区切りのセミコロンが前に要る
    ——例のほうが誤りで、そのまま出すと標準の Link パーサが読めない。
    **通じないものを出すより、通じる形で同じことを言う。**
    """
    headers = {"THUMP-Status": f"{THUMP_VERSION} {status} {HTTPStatus(status).phrase}"}
    if requested:
        # 相対参照。解決の経路そのものなので、ホストを書かずに済む（NMA は
        # identity inert。§2.1）。
        headers["Link"] = f'</{compact_ark(requested)}>; rel="describes"'
    return headers


def _negotiate(accept: str, offers: tuple[str, ...]) -> str:
    """`Accept` から出す媒体を 1 つ選ぶ。**同点なら `offers` の先頭**。

    q 値と限定の強さ（`text/plain` > `text/*` > `*/*`）を見る。ヘッダが無い、
    空、`*/*` のいずれでも先頭の申し出に落ちる——**仕様が定める表現を既定に
    したいので、呼ぶ側はそれを先頭に置くこと**。
    """
    best = dict.fromkeys(offers, 0.0)
    for part in accept.split(","):
        media, _, params = part.strip().partition(";")
        media = media.strip().lower()
        if not media:
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        for offer in offers:
            kind = offer.split("/")[0]
            if media in (offer, f"{kind}/*", "*/*"):
                best[offer] = max(best[offer], q)
    # `max` は同点なら先に見たものを残すので、`offers` の順がそのまま優先順になる。
    chosen = max(offers, key=lambda o: best[o])
    return chosen if best[chosen] > 0 else offers[0]


#: `/.well-known/ark` で出せる表現。**text/plain が先頭**——仕様が定めるのは
#: そちらで、`Accept` を送らない相手（curl、発見クライアント）はこれを受け取る。
WELL_KNOWN_OFFERS = ("text/plain", "application/json")

#: `?info` で出せる表現。**html が先頭**——`?info` は人に見せる口で、`Accept` を
#: 送らない相手（ブラウザ、curl）はこれを受け取る。
#:
#: 仕様（draft-kunze-ark-42 §5.2）: "THUMP is designed so that the response
#: (**indicated by the returned HTTP content type**) is normally displayed, whether the
#: output is structured for machine processing (text/plain) or formatted for human
#: consumption (text/html)." ——**媒体で出し分けるのは仕様の想定どおり**である。
#:
#: 中身はどれも同じ「記述＋永続性宣言」（§5「`?info` は記述と permanence を 1 回で
#: 返す」）。`?json` はこの json を名指しする別名として残す。
INFO_OFFERS = ("text/html", "application/json", "text/plain")


def _resolver_path(request: Request) -> str:
    """このホスト上での ARK リゾルバのルートパス。**必ず `/` で終える。**

    ARK ルートは app の直下（`/ark:…`）に生やしてあるので、前段でパスを
    切っていなければ `/`。プレフィクス付きでマウントするなら ASGI の
    `root_path`（uvicorn なら `--root-path`）を設定すること——**その値を
    そのまま答える**ので、設定し忘れると案内先が実際の口とずれる。
    """
    root = "/" + (request.scope.get("root_path") or "").strip("/")
    return root if root.endswith("/") else root + "/"


def _erc(session, res, t) -> dict:
    ark = res.ark
    manager = None
    if ark.shoulder is not None and ark.shoulder.manager_id:
        manager = session.get(Manager, ark.shoulder.manager_id)
    naan = session.get(Naan, ark.naan)
    return {
        "ark": compact_ark(res.requested),
        "who": ark.who,
        "what": ark.title,
        "when": ark.when,
        # C6: **`where` は ARK であって、転送先ではない。**
        #
        # 仕様（draft-kunze-ark-42 §5.1.2）: "A description must at a minimum answer
        # the who, what, when, and where questions (**"where" being the long-term
        # identifier as opposed to a transient redirect target**)".
        #
        # 以前はここに転送先の URL を入れ、ARK は URL が空のときの代替にしていた
        # ——**逆である**。記述は「この識別子は何を指すか」を答えるものなので、
        # 行き先が変わっても変わらない値が入っていなければ、記述として引用できない。
        #
        # ホスト付きの mapping ARK にはしない。前段の書き換え次第で**内部ホスト名を
        # 公開の記述に焼き付ける**ことになるし、compact ARK だけで長期識別子として
        # 完結している（NMA は identity inert。§2.1）。
        "where": compact_ark(res.requested),
        # 転送先は捨てずに別の要素で出す。**kernel の外**に置くのは、これが
        # 「今どこにあるか」であって「何であるか」ではないため。
        "redirect": ark.url + res.suffix if ark.url else "",
        # **リンクにしてよいかは、値と一緒に運ぶ。** テンプレートで判定させると、
        # 別の画面を足したときに付け忘れる。
        # リンクにしてよいか。**登録は妨げないが、開かせるかは別。**
        "redirect_safe": is_followable(ark.url),
        **{f: getattr(ark, f) for f in DC_FIELDS},
        "commitment_level": manager.commitment_level if manager else "",
        # `permanent-dynamic` だけ見せられても意味が伝わらないので、人が読む名も渡す。
        # **画面の言語で出す**（`ci.*`）。未知の値なら翻訳器がそのまま返す。
        "commitment_label": t(f"ci.{manager.commitment_level}") if manager else "",
        "na_policy": naan.na_policy if naan else "",  # NAA ポリシー（NAAN 単位）
        "inherited_from": compact_ark(res.inherited_from) if res.inherited_from else "",
        "suffix": res.suffix,
        "created_at": ark.created_at.isoformat() if ark.created_at else "",
        "updated_at": ark.updated_at.isoformat() if ark.updated_at else "",
    }


_WELL_KNOWN_RESPONSES = {
    200: {
        "description": (
            "`text/plain` by default: the resolver's root path, one line "
            "(draft-kunze-ark-42 §5.6). `Accept: application/json` returns the "
            "namespaces this ledger holds."
        ),
        "content": {
            "text/plain": {"schema": {"type": "string"}},
            "application/json": {"schema": {"type": "object"}},
        },
    },
}


@router.get("/.well-known/ark", responses=_WELL_KNOWN_RESPONSES, description=E_WELL_KNOWN)
def well_known_ark(request: Request, session: Db, cfg: Config):
    """**このホストに ARK リゾルバがあることを知らせる口**（draft-kunze-ark-42 §5.6）。

    42 は `ark` を Well-Known URIs レジストリ（RFC 8615）に登録し、このパスの
    応答を「**リゾルバのルートパスを含む plain text**、末尾は `/`」と定めた。
    **`Accept` を送らない相手にはそれを返す**——`*/*` で JSON を返すと、
    仕様どおりに読む発見クライアントからは「ARK リゾルバではない」に見える。

    `Accept: application/json` のときだけ、arkhe 独自の在庫を返す:
    **採番を外に委ねている NAAN があるとき、クライアントがどこへ行けばよいか**
    （`Naan.minter` / `Shoulder.minter`）と、止まっている名前空間。

    同じ URL が 2 つの表現を持つので、どちらにも `Vary: Accept` を付ける。
    """
    vary = {"Vary": "Accept"}
    if _negotiate(request.headers.get("accept", ""), WELL_KNOWN_OFFERS) == "text/plain":
        # **末尾に改行を置く。** 仕様の言う "plain text file" であり、応答例も
        # 1 行として書かれている。読む側は前後の空白を落として使うこと。
        return PlainTextResponse(
            _resolver_path(request) + "\n",
            media_type="text/plain; charset=utf-8",
            headers=vary,
        )

    naans = session.scalars(select(Naan).order_by(Naan.naan)).all()
    return JSONResponse(
        headers=vary,
        content={
            # 仕様が定める値も JSON に入れておく。**片方だけ見て済ませられる。**
            "resolver_path": _resolver_path(request),
            "resolver": "arkhe",
            "global_resolver": cfg.global_resolver,
            "naans": [
                {
                    "naan": n.naan,
                    "authoritative": n.is_authoritative,
                    "redirect": n.redirect or None,
                    "minter": n.minter or None,
                    "na_policy": n.na_policy or None,
                }
                for n in naans
            ],
            # **`minter` は「叩ける口」だけ。** 人向けの案内は `about` に分ける
            # ——同じ鍵に混ぜると、読む側が API とページを見分けられない。
            "delegated_shoulders": [
                {
                    "shoulder": f"{s.naan}{s.shoulder}",
                    "minter": s.minter or None,
                    "about": s.about or None,
                }
                for s in session.scalars(
                    select(Shoulder).where(Shoulder.status == "delegated")
                ).all()
            ],
            # **転送を止めている名前空間を公開する。** 分散構成では、上位が止めた
            # ことを下位が（その逆も）機械的に確かめられる必要がある。
            "held": [
                {
                    "scope": scope,
                    "target": target(row),
                    "until": row.hold_until.isoformat(),
                    "reason": row.hold_reason,
                }
                for scope, model, target in (
                    ("naan", Naan, lambda r: r.naan),
                    ("shoulder", Shoulder, lambda r: f"{r.naan}{r.shoulder}"),
                )
                for row in session.scalars(
                    select(model).where(model.hold_until > utcnow())
                ).all()
            ],
        }
    )


_TEXT = {"text/plain": {"schema": {"type": "string"}}}

#: **転送だけの口ではない。** 宣言しておかないと、生成クライアントは 200 の JSON だけを
#: 想定して組まれ、転送も記述も 404 も異常として扱う。
#:
#: **媒体も 1 つではない。** 同じ 200 でも、`?json` と NAAN だけの ARK は JSON、
#: `?` と `??` と保留は ANVL（text/plain）、`?info` は人が読む HTML を返す。
#: 3xx が 4 通りあるのは、shoulder の委譲テンプレートが先頭に符号を書けるため
#: （`_STATUS_PREFIX`。N2T に合わせて 301 / 302 / 303 / 307 だけ受ける）。
_RESOLVE_RESPONSES = {
    200: {
        "description": (
            "a description (`?info` / `?` / `??` / `?json`, a target that cannot be "
            "opened, a tombstone, a hold, an ARK that is only a NAAN)"
        ),
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string"}},   # ANVL
            "text/html": {"schema": {"type": "string"}},
        },
    },
    301: {"description": "redirect to the target (a delegation template named `301 `)"},
    302: {"description": "redirect to the target (the default)"},
    303: {"description": "redirect to the target (a delegation template named `303 `)"},
    307: {"description": "redirect to the target (a delegation template named `307 `)"},
    400: {"description": "not readable as an ARK", "content": _TEXT},
    404: {"description": "not in this ledger, and nowhere to forward to", "content": _TEXT},
}


@router.get("/ark:/{rest:path}", responses=_RESOLVE_RESPONSES, description=E_RESOLVE)
@router.get("/ark:{rest:path}", responses=_RESOLVE_RESPONSES, description=E_RESOLVE)
def resolve_ark(rest: str, request: Request, session: Db, cfg: Config):
    """**ARK を解決する。認証は要らない。** `ark:/99999/x9tn1qkq2g7` と `ark:99999/x9tn1qkq2g7` の
    どちらの表記でも受ける。

    返し方は 1 つではない——**識別子を殺さないことを、どの経路でも優先する**:

      302  行き先へ転送する（通常。shoulder の委譲テンプレートが先頭に符号を
           書いていれば **301 / 303 / 307** にもなる）
      200  記述を返す。`?info` / `??` を付けたとき、行き先がブラウザで開けない
           とき（`urn:isbn:…` など）、行き先が空のとき、墓碑のとき、保留中のとき
      404  この台帳に無く、取次先も無いとき。**`?info` でも 404 は 404**
           ——知らない名前について述べられることは無い
      400  ARK として読めない文字列

    **保留（hold）でも 404 にしない。** その識別子は存在していて、我々が今は転送
    しないだけなので、理由と期限を添えて 200 で返す。**墓碑（tombstone）も同じ**
    ——「失われた」と述べることと、「無かった」と言うことは違う。

    NAAN だけの ARK（`ark:12345`）には、その NAAN について答えられることを返す。
    知らない NAAN は上位のリゾルバ（`ARKHE_GLOBAL_RESOLVER`、既定 n2t.net）へ取り次ぐ。
    """
    # A4: **復号済みの経路を使わない。** `%2F` が `/` に化けると別の識別子になる。
    raw = _raw_ark_path(request)
    try:
        parsed = parse_ark(raw.lstrip("/"), allow_naan_only=True)  # D4
    except ArkParseError as exc:
        # **符号を先頭に置く。** 解決の口は text/plain を返す（人も読む）ので、
        # 機械に判定させるなら行頭が読みやすい。
        return PlainTextResponse(
            f"{errors.ARK_UNREADABLE.number} {errors.ARK_UNREADABLE.say(reason=exc)}\n",
            status_code=400,
            headers=_thump(400),
        )

    if not parsed.name:
        # D4: NAAN だけの ARK。**その NAAN について答えられることを返す。**
        naan = session.get(Naan, parsed.naan)
        if naan is None:
            return RedirectResponse(
                f"{cfg.global_resolver.rstrip('/')}/{compact_ark(parsed.naan)}", status_code=302
            )
        return JSONResponse(
            {"naan": naan.naan, "name": naan.name, "na_policy": naan.na_policy,
             "authoritative": naan.is_authoritative, "minter": naan.minter}
        )

    res = resolve(
        SqlArkRepository(session),
        parsed.naan,
        parsed.name,
        _inflection(request),
        global_resolver=cfg.global_resolver,
    )

    # **ブラウザを転送してよい先だけ転送する。** `urn:isbn:…` のような正当な
    # 行き先は開けないので、転送せず記述を返す——これは制限ではなく、`?info` が
    # 最初から担っている役目。`FORWARD`（他所のリゾルバへの取次）は常に http。
    if res.outcome is Outcome.REDIRECT and not is_followable(res.location):
        res = replace(res, outcome=Outcome.DESCRIBE, status=200)

    if res.outcome in (Outcome.REDIRECT, Outcome.FORWARD):
        # C2: **`??` を転送先 URL に付けて渡さない。** 転送はあくまで対象への
        # 誘導で、inflection はこのリゾルバへの問い合わせだから。
        return RedirectResponse(res.location, status_code=res.status)

    if res.outcome is Outcome.HELD:
        # **404 にしない。** その名前空間は存在していて、我々が今は転送しないだけ。
        # 行が無いので記述は出せないが、**理由と期限は出す**——黙って止まるより良い。
        return PlainTextResponse(
            _anvl(
                [
                    ("where", compact_ark(res.requested)),
                    ("hold", res.hold.reason if res.hold else ""),
                    ("hold-until", res.hold.until.isoformat() if res.hold else ""),
                    ("hold-scope", res.hold.scope if res.hold else ""),
                ]
            ),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    if res.outcome is Outcome.NOT_FOUND:
        code = res.code or errors.ARK_UNKNOWN_NAME
        return PlainTextResponse(
            f"{code.number} {compact_ark(res.requested)} — {res.reason}\n",
            status_code=404,
            headers=_thump(404, res.requested),
        )

    # 記述に添える語は**画面の言語**で。`?info` は公開の口なので、`Accept-Language`
    # と `?info&lang=` を見る（管理画面と同じ順序）。
    lang = i18n.pick(request)
    erc = _erc(session, res, i18n.translator(lang))
    kernel = [
        ("who", erc["who"]),
        ("what", erc["what"]),
        ("when", erc["when"]),
        ("where", erc["where"]),
    ]

    if res.inflection is Inflection.BRIEF:
        # `?` — ERC の 4 要素だけを簡潔に返す。**対象に到達できなくても、これは
        # 答えられる**（FAIR A2）。転送先は kernel の外に、あるときだけ添える。
        return PlainTextResponse(
            _anvl([*kernel, ("redirect", erc["redirect"] or None)]),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    def _as_json():
        return JSONResponse(
            headers={**_thump(200, res.requested), "Vary": "Accept, Accept-Language"},
            content={
                **erc,
                "commitment": res.ark.commitment,
                # **止まっていることは隠さない。** 機械にも分かる形で出す。
                "hold": res.hold.as_dict() if res.hold else None,
            },
        )

    def _as_anvl():
        # `??` の中身。**`?info` の text/plain もこれ**——どちらも「記述＋永続性宣言」
        # で、違うのは媒体だけである（§5）。
        return PlainTextResponse(
            _anvl(
                [
                    *kernel,
                    ("redirect", erc["redirect"] or None),
                    ("about", erc["ark"]),
                    # NAA ポリシー（NAAN 単位・名前空間に対して負う約束）
                    ("policy", erc["na_policy"]),
                    # NMA コミットメント（対象単位・この対象をどう保つか）。
                    # **空なら行ごと省く。** `(:unav)` を置くと「我々の約束が不明」に
                    # 読めるが、約束は下の commitment-level で分かっている。
                    ("commitment", res.ark.commitment or None),
                    ("commitment-level", erc["commitment_level"]),
                    # 保留は**約束の一部として**出す。`??` は「この識別子をどう
                    # 保つか」を答える口なので、今転送していない事実はここに要る。
                    ("hold", res.hold.reason if res.hold else None),
                    ("hold-until", res.hold.until.isoformat() if res.hold else None),
                    ("inherited-from", erc["inherited_from"] or None),
                ]
            ),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    def _as_html():
        return templates.TemplateResponse(
            request,
            "info.html",
            {
                "erc": erc, "res": res,
                "hold": res.hold.as_dict() if res.hold else None,
                "t": i18n.translator(lang), "lang": lang, "langs": i18n.LANGS,
            },
            headers={**_thump(200, res.requested), "Vary": "Accept, Accept-Language"},
        )

    if res.inflection is Inflection.JSON:
        # `?json` は `?info` の JSON を**名指しする別名**。仕様の語彙ではないので
        # 消しはしないが、`?info` に `Accept: application/json` を送っても同じものが返る。
        return _as_json()

    if res.inflection is Inflection.POLICY:
        # `??` は **`?` の内容 ＋ 永続性宣言**（C4）。
        #   draft-kunze-ark-42        … "'?' (brief metadata) and '??' (more metadata)"
        #   arks.org/about/ark-features … "a maintenance commitment from the current server"
        # **「more」の中身が commitment**、と読めば両立する。形式も ANVL に揃える。
        return _as_anvl()

    # `?info` と、inflection の無い記述（墓碑・保留・行き先なし）。**媒体で出し分ける**
    # ——仕様が「応答の形は content type が示す」と書いているとおりで、中身はどれも
    # 同じ「記述＋永続性宣言」である。`Accept` を送らない相手には人が読む html。
    chosen = _negotiate(request.headers.get("accept", ""), INFO_OFFERS)
    if chosen == "application/json":
        return _as_json()
    if chosen == "text/plain":
        return _as_anvl()
    return _as_html()

