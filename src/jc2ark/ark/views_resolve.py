"""解決のビュー。**無認証**（ARK 仕様に認証の規定は無く、解決は公開が前提）。

DRF に載せない。302 を返すだけで OpenAPI の対象でもない。
"""

from __future__ import annotations

import json

from django.conf import settings
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render
from django.views.decorators.http import require_safe

from jc2ark.arkspec.naming import ArkParseError, parse_ark

from .repository import DjangoArkRepository
from .resolution import Inflection, Outcome, resolve

#: ERC / Dublin Core として `?info` に出す項目。
ERC_FIELDS = ("who", "what", "when", "where")
DC_FIELDS = ("title", "type", "identifier", "format", "relation", "source", "commitment")


def _inflection(request) -> Inflection:
    """inflection を判定する。

    | 記法 | `QUERY_STRING` | 返すもの |
    | --- | --- | --- |
    | `?` | `""`（**生の URI で見分ける**） | ERC/ANVL の簡潔な記述 |
    | `??` | `"?"` | 永続性宣言（C4） |
    | `?info` | `"info"` | 人間可読の記述（**仕様上の必須**） |
    | `?json` | `"json"` | 機械可読 |

    **裸の `?` は `QUERY_STRING` だけでは見分けられない**——`…/name?` も `…/name`
    もクエリ文字列は空になる。**gunicorn が `RAW_URI` に生のリクエスト URI を
    入れる**ので、そこで判定する（実測: アクセスログにも `GET …/name?` と残る）。
    `RAW_URI` が無い環境（Django の開発サーバやテストクライアント）では `?` を
    諦めて inflection 無しとして扱う——**仕様上 `?` は optional** なので、
    そこで壊れるものは無い。
    """
    qs = request.META.get("QUERY_STRING", "")
    if qs == "?":
        return Inflection.POLICY
    if qs == "info":
        return Inflection.INFO
    if qs == "json":
        return Inflection.JSON
    if not qs:
        raw = request.META.get("RAW_URI") or request.META.get("REQUEST_URI") or ""
        if raw.endswith("?"):
            return Inflection.BRIEF
    return Inflection.NONE


def _anvl(pairs) -> str:
    """ERC/ANVL 形式。**ARK が伝統的に `?` で返してきた形。**

    値の改行は継続行にする（ANVL の折り返し規約）。
    """
    lines = ["erc:"]
    for key, value in pairs:
        if value:
            lines.append(f"{key}: " + str(value).replace("\n", "\n    "))
    return "\n".join(lines) + "\n"


def _erc(res) -> dict:
    ark = res.ark
    return {
        "ark": f"ark:/{res.requested}",
        "who": ark.who,
        "what": ark.title,
        "when": ark.when,
        "where": ark.url + res.suffix if ark.url else "",
        **{f: getattr(ark, f) for f in DC_FIELDS},
        "commitment_level": ark.shoulder.manager.commitment_level if ark.shoulder.manager else "",
        "inherited_from": f"ark:/{res.inherited_from}" if res.inherited_from else "",
        "suffix": res.suffix,
        "created_at": ark.created_at.isoformat() if ark.created_at else "",
        "updated_at": ark.updated_at.isoformat() if ark.updated_at else "",
    }


@require_safe
def resolve_ark(request, ark: str):
    try:
        parsed = parse_ark(f"ark:{ark}" if not ark.lower().startswith("ark:") else ark)
    except ArkParseError as exc:
        return HttpResponseBadRequest(str(exc))

    res = resolve(
        DjangoArkRepository(),
        parsed.naan,
        parsed.name,
        _inflection(request),
        global_resolver=getattr(settings, "JC2ARK_GLOBAL_RESOLVER", "https://n2t.net"),
    )

    if res.outcome in (Outcome.REDIRECT, Outcome.FORWARD):
        # C2: **`??` を転送先 URL に付けて渡さない。** 転送はあくまで対象への
        # 誘導で、inflection はこのリゾルバへの問い合わせだから。
        return HttpResponseRedirect(res.location, status=res.status)

    if res.outcome == Outcome.NOT_FOUND:
        body = f"ark:/{res.requested} — {res.reason}"
        return HttpResponseNotFound(body, content_type="text/plain; charset=utf-8")

    # DESCRIBE
    erc = _erc(res)
    if res.inflection is Inflection.BRIEF:
        # `?` — ERC の 4 要素だけを簡潔に返す。`?info`（HTML）より軽く、
        # `?json` より素朴。**対象に到達できなくても、これは答えられる**（FAIR A2）。
        return HttpResponse(
            _anvl(
                [
                    ("who", erc["who"]),
                    ("what", erc["what"]),
                    ("when", erc["when"]),
                    ("where", erc["where"] or erc["ark"]),
                ]
            ),
            content_type="text/plain; charset=utf-8",
        )
    if res.inflection is Inflection.JSON:
        return JsonResponse(erc, json_dumps_params={"ensure_ascii": False})
    if res.inflection is Inflection.POLICY:
        # C4: `??` は**永続性宣言**を返す。
        naan = res.ark.naan
        return HttpResponse(
            json.dumps(
                {
                    "ark": erc["ark"],
                    "na_policy": naan.na_policy,  # NAA ポリシー（NAAN 単位）
                    "commitment": res.ark.commitment,  # NMA コミットメント（対象単位）
                    "commitment_level": erc["commitment_level"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            content_type="application/json; charset=utf-8",
        )
    return render(request, "ark/info.html", {"erc": erc, "res": res})


@require_safe
def well_known_ark(request):
    """N1: `/.well-known/ark`（RFC 8615）。

    外部（N2T・他機関のツール）から「このホストは ARK リゾルバか」を自動判定
    できるようにする。**機関ドメインでリゾルバを常設する以上、発見可能性は運用上の
    価値がある。**
    """
    from .models import Naan, Shoulder, ShoulderStatus

    naans = list(Naan.objects.filter(is_authoritative=True).values("naan", "na_policy", "minter"))
    # **採番が外に出ている名前空間は公開して案内する。** クライアントがどこへ行けば
    # よいか分かるようにするため（我々は mint を代理しない）。
    delegated = {
        f"{s.naan_id}{s.shoulder}": s.minter
        for s in Shoulder.objects.filter(status=ShoulderStatus.DELEGATED).select_related("naan")
    }
    return JsonResponse(
        {
            "ark_resolver": True,
            "naans": [n["naan"] for n in naans],
            "na_policy": {n["naan"]: n["na_policy"] for n in naans if n["na_policy"]},
            "minters": {
                **{n["naan"]: n["minter"] for n in naans if n["minter"]},
                **delegated,
            },
            "inflections": ["?info", "?json", "??"],
            "suffix_passthrough": True,
        },
        json_dumps_params={"ensure_ascii": False},
    )
