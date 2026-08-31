"""解決。**resolver プロセスの唯一の口。** 採番も管理もここには無い。

決定は `domain.resolution.resolve()` が行い、ここは HTTP の形に写すだけ。
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from arkhe.arkspec.naming import ArkParseError, parse_ark
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

COMMITMENT_LABEL_JA = {
    "not-guaranteed": "保証なし（検証・開発系）",
    "permanent-dynamic": "恒久・内容は更新されうる",
    "permanent-stable": "恒久・内容は実質不変",
    "permanent-unchanging": "恒久・内容は一切不変",
    "descriptive-only": "記述のみ（所在は変わりうる）",
}


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
    qs = request.url.query
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


def _erc(session, res) -> dict:
    ark = res.ark
    manager = None
    if ark.shoulder is not None and ark.shoulder.manager_id:
        manager = session.get(Manager, ark.shoulder.manager_id)
    naan = session.get(Naan, ark.naan)
    return {
        "ark": f"ark:/{res.requested}",
        "who": ark.who,
        "what": ark.title,
        "when": ark.when,
        "where": ark.url + res.suffix if ark.url else "",
        # **リンクにしてよいかは、値と一緒に運ぶ。** テンプレートで判定させると、
        # 別の画面を足したときに付け忘れる。
        # リンクにしてよいか。**登録は妨げないが、開かせるかは別。**
        "where_safe": is_followable(ark.url),
        **{f: getattr(ark, f) for f in DC_FIELDS},
        "commitment_level": manager.commitment_level if manager else "",
        # `permanent-dynamic` だけ見せられても意味が伝わらないので、人間向けの
        # 表示名も渡す（`?info` で使う）。
        "commitment_label": (
            COMMITMENT_LABEL_JA.get(manager.commitment_level, "") if manager else ""
        ),
        "na_policy": naan.na_policy if naan else "",  # NAA ポリシー（NAAN 単位）
        "inherited_from": f"ark:/{res.inherited_from}" if res.inherited_from else "",
        "suffix": res.suffix,
        "created_at": ark.created_at.isoformat() if ark.created_at else "",
        "updated_at": ark.updated_at.isoformat() if ark.updated_at else "",
    }


@router.get("/.well-known/ark")
def well_known_ark(session: Db, cfg: Config):
    """このリゾルバが何を預かっているかを機械可読で公開する。

    **採番を外に委ねている NAAN があるとき、クライアントがどこへ行けばよいか**を
    ここで分かるようにする（`Naan.minter` / `Shoulder.minter`）。
    """
    naans = session.scalars(select(Naan).order_by(Naan.naan)).all()
    return JSONResponse(
        {
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
            "delegated_shoulders": [
                {"shoulder": f"{s.naan}{s.shoulder}", "minter": s.minter}
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
        "description": "記述を返す（`?info` / `?` / `??` / `?json`、開けない行き先、"
                       "墓碑、保留、NAAN だけの ARK）",
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string"}},   # ANVL
            "text/html": {"schema": {"type": "string"}},
        },
    },
    301: {"description": "行き先へ転送する（委譲テンプレートが `301 ` を指定）"},
    302: {"description": "行き先へ転送する（既定）"},
    303: {"description": "行き先へ転送する（委譲テンプレートが `303 ` を指定）"},
    307: {"description": "行き先へ転送する（委譲テンプレートが `307 ` を指定）"},
    400: {"description": "ARK として読めない", "content": _TEXT},
    404: {"description": "この台帳に無く、取次先も無い", "content": _TEXT},
}


@router.get("/ark:/{rest:path}", responses=_RESOLVE_RESPONSES)
@router.get("/ark:{rest:path}", responses=_RESOLVE_RESPONSES)
def resolve_ark(rest: str, request: Request, session: Db, cfg: Config):
    """**ARK を解決する。認証は要らない。** `ark:/12345/xyz` と `ark:12345/xyz` の
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

    NAAN だけの ARK（`ark:/12345`）には、その NAAN について答えられることを返す。
    知らない NAAN は上位のリゾルバ（`ARKHE_GLOBAL_RESOLVER`、既定 n2t.net）へ取り次ぐ。
    """
    raw = str(request.url.path)
    try:
        parsed = parse_ark(raw.lstrip("/"), allow_naan_only=True)  # D4
    except ArkParseError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    if not parsed.name:
        # D4: NAAN だけの ARK。**その NAAN について答えられることを返す。**
        naan = session.get(Naan, parsed.naan)
        if naan is None:
            return RedirectResponse(
                f"{cfg.global_resolver.rstrip('/')}/ark:/{parsed.naan}", status_code=302
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
                    ("where", f"ark:/{res.requested}"),
                    ("hold", res.hold.reason if res.hold else ""),
                    ("hold-until", res.hold.until.isoformat() if res.hold else ""),
                    ("hold-scope", res.hold.scope if res.hold else ""),
                ]
            ),
            media_type="text/plain; charset=utf-8",
        )

    if res.outcome is Outcome.NOT_FOUND:
        return PlainTextResponse(f"ark:/{res.requested} — {res.reason}", status_code=404)

    erc = _erc(session, res)
    kernel = [
        ("who", erc["who"]),
        ("what", erc["what"]),
        ("when", erc["when"]),
        ("where", erc["where"] or erc["ark"]),
    ]

    if res.inflection is Inflection.BRIEF:
        # `?` — ERC の 4 要素だけを簡潔に返す。**対象に到達できなくても、これは
        # 答えられる**（FAIR A2）。
        return PlainTextResponse(_anvl(kernel), media_type="text/plain; charset=utf-8")

    if res.inflection is Inflection.JSON:
        return JSONResponse(
            {
                **erc,
                "commitment": res.ark.commitment,
                # **止まっていることは隠さない。** 機械にも分かる形で出す。
                "hold": res.hold.as_dict() if res.hold else None,
            }
        )

    if res.inflection is Inflection.POLICY:
        # `??` は **`?` の内容 ＋ 永続性宣言**（C4）。
        #   draft-kunze-ark-42        … "'?' (brief metadata) and '??' (more metadata)"
        #   arks.org/about/ark-features … "a maintenance commitment from the current server"
        # **「more」の中身が commitment**、と読めば両立する。形式も ANVL に揃える。
        return PlainTextResponse(
            _anvl(
                [
                    *kernel,
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
        )

    return templates.TemplateResponse(
        request,
        "info.html",
        {"erc": erc, "res": res, "hold": res.hold.as_dict() if res.hold else None},
    )

