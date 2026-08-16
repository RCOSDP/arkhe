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
    """生のクエリ文字列から inflection を判定する。

    `??` はクエリ文字列が `"?"` になる。`?info` / `?json` はそのまま。

    ⚠️ **裸の `?`（brief）は WSGI では検出できない**——`…/name?` のクエリ文字列は
    空で、inflection 無しと区別がつかない。仕様上 `?` は optional なので採らない
    （C1 の訂正）。必須の `?info` は検出できる。
    """
    raw = request.META.get("QUERY_STRING", "")
    if raw == "?":
        return Inflection.POLICY
    if raw == "info":
        return Inflection.INFO
    if raw == "json":
        return Inflection.JSON
    return Inflection.NONE


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
    from .models import Naan

    naans = list(Naan.objects.filter(is_authoritative=True).values("naan", "na_policy"))
    return JsonResponse(
        {
            "ark_resolver": True,
            "naans": [n["naan"] for n in naans],
            "na_policy": {n["naan"]: n["na_policy"] for n in naans if n["na_policy"]},
            "inflections": ["?info", "?json", "??"],
            "suffix_passthrough": True,
        },
        json_dumps_params={"ensure_ascii": False},
    )
