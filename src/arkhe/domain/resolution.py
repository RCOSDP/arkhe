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
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlsplit

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
#: **ブラウザに解釈させると危ないスキーム。** 登録を拒む唯一の理由。
#:
#: `?info` は認証を要さない公開ページなので、そこに載る文字列を採番した側が
#: 自由に決められると、リゾルバのオリジンで動くスクリプトを他人に踏ませられる。
#:
#: 黒名簿で足りるのは、**綴りの揺れを `urlsplit` が吸収する**から——大小混在も、
#: 前置きの空白も、途中のタブ・改行・NUL も、同じ scheme に正規化される
#: （ブラウザの扱いと同じ）。文字列のまま比べるなら白名簿が要るが、
#: 解析してから比べるなら数え上げられる。
DANGEROUS_SCHEMES = frozenset({"javascript", "data", "vbscript", "blob", "filesystem"})

#: **ブラウザに「そこへ行け」と言ってよいスキーム。**
#: これ以外は、リンクにもせず転送もしない——ただし**登録は妨げない**。
FOLLOWABLE_SCHEMES = frozenset({"http", "https"})


def _scheme(url: str) -> str:
    try:
        return urlsplit(url.strip()).scheme.lower()
    except ValueError:
        return "?"


def is_registrable(url: str) -> bool:
    """行き先として台帳に入れてよいか。

    **ARK は物理オブジェクトにも、他の識別子にも付けられる。** `where` は URI で
    あって HTTP URL とは限らないので、`urn:` `doi:` `ark:` `mailto:` などを
    拒んではいけない。空も正当——**行き先が無い対象**は中心的な用途である。

    拒むのは、ブラウザに解釈させると危ないものだけ。
    """
    return not url or _scheme(url) not in DANGEROUS_SCHEMES


def is_followable(url: str) -> bool:
    """ブラウザを転送してよいか／リンクにしてよいか。

    `urn:isbn:…` は正当な行き先だが、**転送先にはならない**（ブラウザは開けない）。
    そういう ARK は記述を返す——これは制限ではなく、`?info` が最初から
    担っている役目である。
    """
    return bool(url) and _scheme(url) in FOLLOWABLE_SCHEMES


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
    HELD = "held"  # 転送を一時停止している。**識別子は生きている**


@dataclass(frozen=True)
class Hold:
    """効いている保留。**転送だけを止める**（解決は止めない）。

    `scope` は誰が止めているか——`ark` / `shoulder` / `naan`。止めた層が分かると、
    「この 1 件が悪いのか、名前空間ごと止まっているのか」を外から見分けられる。
    """

    scope: str
    reason: str = ""
    until: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "reason": self.reason,
            "until": self.until.isoformat() if self.until else "",
        }


def _aware(value):
    """素の datetime を UTC とみなす。

    **SQLite は tz を落として返す。** 素と aware を比べると `TypeError` になり、
    保留の判定だけが例外で落ちる——**止めたつもりが転送され続ける**ほうが、
    ここでは何倍も悪い。
    """
    if value is None or not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hold_of(obj, scope: str, now: datetime) -> Hold | None:
    """その行が今まさに保留中なら `Hold` を返す。

    **期限切れをバッチで戻さない。** 解決のたびにここで時計を見るので、
    戻し忘れが起きない——止め忘れは残るが、**戻し忘れは残らない**。
    """
    until = _aware(getattr(obj, "hold_until", None))
    if until is None or until <= now:
        return None
    return Hold(scope=scope, reason=getattr(obj, "hold_reason", "") or "", until=until)


def effective_hold(now: datetime, *pairs) -> Hold | None:
    """`(行, scope)` を狭い順に見て、最初に効いているものを返す。

    狭い順に見るのは、**その 1 件を止めた理由のほうが具体的**だから。
    """
    for obj, scope in pairs:
        if obj is None:
            continue
        found = hold_of(obj, scope, now)
        if found is not None:
            return found
    return None


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
    #: 効いている保留。**転送を止めた理由**を応答に載せるために運ぶ。
    hold: Hold | None = None


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
    now: datetime | None = None,
) -> Resolution:
    """ARK を解決する。

    `now` は保留（hold）の判定にだけ使う。**引数にしてあるのはテストのため**で、
    渡さなければ現在時刻を見る。
    """
    now = now or datetime.now(UTC)
    name = normalize_structural(name)  # N4
    normalized = strip_hyphens(name)  # A2
    requested = ark_key(naan, name)

    # --- 完全一致 -----------------------------------------------------------
    # 保存済みの表記を先に当てる（ハイフンを含む旧レコードを生かすため）。
    for key in dict.fromkeys([ark_key(naan, name), ark_key(naan, normalized)]):
        ark = repo.get_ark(key)
        if ark is not None:
            return _deliver(ark, requested=requested, inflection=inflection, now=now)

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
                now=now,
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
                # **委譲先を止められるのはここだけ。** この名前は我々の台帳に無い
                # ので、止める判断は shoulder か NAAN の側にしか置けない。
                held = effective_hold(now, (shoulder, "shoulder"), (naan_obj, "naan"))
                if held is not None:
                    return _held(requested, inflection, held)
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

    # 他所の NAAN は登録された委譲先へ。**その NAAN ごと止めることもできる。**
    held = effective_hold(now, (naan_obj, "naan"))
    if held is not None:
        return _held(requested, inflection, held)
    return Resolution(
        Outcome.FORWARD,
        status=302,
        location=f"{naan_obj.redirect.rstrip('/')}/ark:/{requested}",
        requested=requested,
        reason="delegated by NAAN registration",
    )


def _held(requested: str, inflection: Inflection, held: Hold) -> Resolution:
    """台帳に行が無いまま止まっているとき（shoulder / NAAN 単位）の応答。

    **`404` にはしない。** その名前空間は存在していて、我々が今は転送しないだけ。
    """
    return Resolution(
        Outcome.HELD,
        status=200,
        requested=requested,
        inflection=inflection,
        reason="redirection is on hold",
        hold=held,
    )


def _deliver(
    ark,
    *,
    requested: str,
    inflection: Inflection,
    suffix: str = "",
    inherited_from: str = "",
    now: datetime | None = None,
) -> Resolution:
    """見つかった ARK（本人または祖先）をどう返すか決める。"""
    now = now or datetime.now(UTC)
    # ARK → その shoulder → その NAAN の順に見る（狭いほうの理由が具体的）。
    # **関係は辿るだけで引かない。** repository が同じ 1 本の問い合わせで載せてくる。
    shoulder = getattr(ark, "shoulder", None)
    held = effective_hold(
        now,
        (ark, "ark"),
        (shoulder, "shoulder"),
        (getattr(shoulder, "naan_obj", None), "naan"),
    )
    if held is not None:
        # **転送だけを止める。** 記述は返し続ける——識別子は生きている。
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
            inflection=inflection,
            reason="redirection is on hold",
            hold=held,
        )
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
