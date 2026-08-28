"""解決の決定ロジック。**HTTP から切り離してある**ので単体で検証できる。

一本の流れとして書く（`arklet_ark_conformance.md` §7-1）:

    正規化（A1・N4）
      → 完全一致
      → 祖先 passthrough（D5・D6・B3）
      → チェックディジット検証（D1。**自分が権威を持つ NAAN のときだけ**）
      → shoulder の redirect
      → 自 NAAN なら 404（D3）／他所なら Naan.redirect／未知 NAAN なら n2t（D2）

受け入れ条件: D1・D2・D3・D5・D6・B3・C5・N4・A2・SC1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from arkhe.arkspec.betanumeric import verify_ark_check_digit
from arkhe.arkspec.naming import (
    QUALIFIER_SEPARATORS,
    ark_key,
    gen_prefixes,
    is_structural_at,
    normalize_structural,
    split_after_normalized,
    strip_hyphens,
)
from arkhe.arkspec.shoulder import split_shoulder

#: D2: 未知 NAAN の取次先。設定可能にする。
DEFAULT_GLOBAL_RESOLVER = "https://n2t.net"


class Inflection(Enum):
    """`?` で始まる問い合わせ。**仕様上の必須は `?info` だけ**（C1 の訂正）。"""

    NONE = "none"
    BRIEF = "brief"  # `?`     — ERC/ANVL の簡潔な記述
    INFO = "info"  # `?info` — 人間可読の記述（MUST）
    JSON = "json"  # `?json` — 機械可読（arklet 由来の拡張）
    POLICY = "policy"  # `??`    — 永続性宣言を返す（C4）

    @property
    def wants_metadata(self) -> bool:
        return self is not Inflection.NONE


class Outcome(Enum):
    REDIRECT = "redirect"  # 302/303 で転送する
    DESCRIBE = "describe"  # リゾルバ自身が記述を返す
    NOT_FOUND = "not_found"
    FORWARD = "forward"  # 他所の NAAN / 未知 NAAN へ取り次ぐ


@dataclass
class Resolution:
    outcome: Outcome
    status: int = 302
    location: str = ""
    #: 記述を返すときの元になった Ark（祖先かもしれない）。
    ark: object | None = None
    #: 要求された ARK（`naan/name`）。祖先から継承したときに名乗る名前。
    requested: str = ""
    #: 祖先から切り出した修飾子部分。
    suffix: str = ""
    #: 祖先継承のとき、どの ARK から継承したか（C5）。
    inherited_from: str = ""
    inflection: Inflection = Inflection.NONE
    reason: str = ""
    detail: dict = field(default_factory=dict)


def base_name(name: str) -> str:
    """修飾子より前の base name を返す。

    N7: 検査桁は base compact name に対して計算され、**修飾子は含めない**。
    """
    for i, char in enumerate(name):
        if char in QUALIFIER_SEPARATORS and is_structural_at(name, i):
            return name[:i]
    return name


_TEMPLATE = re.compile(r"\$\{blade\}|\$id")
_STATUS_PREFIX = re.compile(r"^(30[1237])\s+")


def expand_redirect(template: str, naan: str, name: str) -> tuple[int, str]:
    """N2T 互換のテンプレートを展開する。

    | 記法 | 置換 |
    | --- | --- |
    | `$id` | `<naan>/<name>`（修飾子を含む） |
    | `${blade}` | shoulder より後ろ |
    | 先頭の `303 ` 等 | ステータスコード指定 |

    `${nlid}` は採らない（N2T 内部の正規化 ID で、対応する概念が無い）。
    """
    status = 302
    m = _STATUS_PREFIX.match(template)
    if m:
        status = int(m.group(1))
        template = template[m.end() :]
    blade = split_shoulder(name)[1]
    expanded = _TEMPLATE.sub(
        lambda mo: blade if mo.group(0) == "${blade}" else f"{naan}/{name}", template
    )
    return status, expanded


class ArkRepository:
    """解決に必要な問い合わせだけを切り出した窓口。

    テストでは差し替えられるようにし、**決定ロジックを Django から独立**させる。
    """

    def get_ark(self, key: str):  # pragma: no cover - 実装は django_repo
        raise NotImplementedError

    def get_arks(self, keys: list[str]) -> dict:  # pragma: no cover
        raise NotImplementedError

    def get_naan(self, naan: str):  # pragma: no cover
        raise NotImplementedError

    def get_shoulder(self, naan: str, shoulder: str):  # pragma: no cover
        raise NotImplementedError


def resolve(
    repo: ArkRepository,
    naan: str,
    name: str,
    inflection: Inflection = Inflection.NONE,
    *,
    global_resolver: str = DEFAULT_GLOBAL_RESOLVER,
) -> Resolution:
    """ARK を解決する。"""
    name = normalize_structural(name)  # N4
    normalized = strip_hyphens(name)  # A2
    requested = ark_key(naan, name)

    # --- 完全一致 -----------------------------------------------------------
    # 保存済みの表記を先に当てる（ハイフンを含む旧レコードを生かすため）。
    for key in dict.fromkeys([ark_key(naan, name), ark_key(naan, normalized)]):
        ark = repo.get_ark(key)
        if ark is not None:
            return _deliver(ark, requested=requested, inflection=inflection)

    # --- 祖先 passthrough（D5: 最長一致） -----------------------------------
    candidates = list(gen_prefixes(normalized))  # 長い順
    if candidates:
        # SC1: **DB で関数ソートしない。** 候補は高々 name 長ぶんなので 1 回の
        # IN で引き、`gen_prefixes` が返す長い順にアプリ側で最初の一致を採る。
        found = repo.get_arks([ark_key(naan, c) for c in candidates])
        for cand in candidates:
            ancestor = found.get(ark_key(naan, cand))
            if ancestor is None:
                continue
            _, suffix = split_after_normalized(name, len(cand))
            return _deliver(
                ancestor,
                requested=requested,
                inflection=inflection,
                suffix=suffix,
                inherited_from=ark_key(naan, cand),
            )

    # --- ここから未登録 -----------------------------------------------------
    naan_obj = repo.get_naan(naan)

    if naan_obj is None:
        # D2: 未知 NAAN はグローバルリゾルバへ取り次ぐ（SHOULD）。
        if inflection.wants_metadata:
            return Resolution(
                Outcome.NOT_FOUND,
                status=404,
                requested=requested,
                inflection=inflection,
                reason="metadata for an unknown NAAN is not held by this resolver",
            )
        return Resolution(
            Outcome.FORWARD,
            status=302,
            location=f"{global_resolver.rstrip('/')}/ark:/{requested}",
            requested=requested,
            reason="unknown NAAN forwarded to the global resolver",
        )

    if naan_obj.is_authoritative:
        # D1: **我々が権威を持つ NAAN のときだけ**検査桁を見る。他所の NAAN は
        # チェックディジットを使っているとは限らないので判定しない。
        stem = base_name(normalized)
        if not verify_ark_check_digit(naan, stem):
            return Resolution(
                Outcome.NOT_FOUND,
                status=404,
                requested=requested,
                inflection=inflection,
                reason="check digit mismatch: the identifier looks mistranscribed",
                detail={"base": stem},
            )

        # shoulder 単位の解決委譲（N2T のデータモデル）。
        shoulder_part = split_shoulder(stem)[0]
        if shoulder_part:
            shoulder = repo.get_shoulder(naan, f"/{shoulder_part}")
            if shoulder is not None and shoulder.redirect:
                status, location = expand_redirect(shoulder.redirect, naan, name)
                return Resolution(
                    Outcome.REDIRECT,
                    status=status,
                    location=location,
                    requested=requested,
                    reason="delegated by shoulder",
                )

        # D3: **自分が権威を持つ NAAN の未知の名前は 404。**「無い」と言える。
        return Resolution(
            Outcome.NOT_FOUND,
            status=404,
            requested=requested,
            inflection=inflection,
            reason="this resolver is authoritative for the NAAN and has no such ark",
        )

    # 他所の NAAN は登録された委譲先へ。
    return Resolution(
        Outcome.FORWARD,
        status=302,
        location=f"{naan_obj.redirect.rstrip('/')}/ark:/{requested}",
        requested=requested,
        reason="delegated by NAAN registration",
    )


def _deliver(
    ark, *, requested: str, inflection: Inflection, suffix: str = "", inherited_from: str = ""
) -> Resolution:
    """見つかった ARK（本人または祖先）をどう返すか決める。"""
    if inflection.wants_metadata:
        # C5: **inflection は suffix passthrough でも失われない。** 最も近い
        # 登録済み祖先のメタデータを、要求された ARK の名前で返す（FAIR A2）。
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
            inflection=inflection,
        )
    if not ark.url:
        # D6: 転送先が無いなら**裸の suffix にリダイレクトせず**、記述を返す。
        # 物理オブジェクトではこれが主たる応答になる。
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
        )
    return Resolution(
        Outcome.REDIRECT,
        status=302,
        location=f"{ark.url}{suffix}",
        ark=ark,
        requested=requested,
        suffix=suffix,
        inherited_from=inherited_from,
    )
