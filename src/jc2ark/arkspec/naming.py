"""ARK 文字列の解析・正規化・祖先生成。

**ARK 仕様の難所はこのモジュールに集約されている。** Django にも DB にも依存
しないので、単体で検証できる。

Derived in part from arklet (https://github.com/internetarchive/arklet),
MIT License, Copyright (c) Internet Archive. See LICENSE.

受け入れ条件:
  A1  `ARK:` を大小非依存で受ける。**NAAN は小文字化、名前の大小は保持**
  A2  ハイフンは無意味として無視する
  N2  **NAAN は文字列として保持・比較する**（`ark:/099999/…` と `ark:/99999/…` は別物）
  N3  betanumeric NAAN を受理する（2001 年以前の歴史的 NAAN）
  N4  構造文字の正規化。`.` は両側に非構造文字がある場合のみ構造文字
  F1  NAAN の長さ制限（変換の前に弾く）
  D5  祖先は最長一致
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from .betanumeric import BETANUMERIC

#: ARK は `/` を「包含（部分）」、`.` を「変種」の意味で予約している。どちらも
#: base name のあとに続く修飾子領域を開くので、suffix passthrough は両方を走査する。
QUALIFIER_SEPARATORS = "/."

#: F1: `int()` に渡す前に長さで弾く。IA 原典の `len(naan) > 10` を踏襲。
MAX_NAAN_LENGTH = 10

#: A1: ラベルは大小非依存。
_LABEL = re.compile(r"ark:", re.IGNORECASE)

#: N3: NAAN は betanumeric（数字＋子音）。2001 年以降は 5 桁数字だが、
#: それ以前の歴史的 NAAN は betanumeric でありうる。
_NAAN_CHARS = frozenset(BETANUMERIC)


class ParsedArk(NamedTuple):
    """`nma` は ARK の前に付いていたホスト部（あれば）。"""

    nma: str
    naan: str  # N2: **文字列**。整数化しない
    name: str  # A1: 大小を保持


class ArkParseError(ValueError):
    """ARK として解釈できない。"""


def parse_ark(ark: str) -> ParsedArk:
    """ARK 文字列を (nma, naan, name) に分解する。

    A1: `ark:` / `ARK:` / `Ark:` を受け、**NAAN は小文字化、name の大小は保持**する。
    N2: NAAN を**文字列のまま**返す。`099999` と `99999` は別の NAAN。
    N3: betanumeric NAAN を受理する。
    F1: 長さ制限を先に適用する。
    """
    if not isinstance(ark, str):
        raise ArkParseError("ARK must be a string")

    parts = _LABEL.split(ark)
    if len(parts) != 2:
        raise ArkParseError("Not a valid ARK: missing or repeated 'ark:' label")
    nma, rest = parts

    rest = rest.lstrip("/")
    naan, slash, name = rest.partition("/")
    if not slash or not name:
        raise ArkParseError("Not a valid ARK: missing name part")

    # F1: 変換や照合の前に長さで弾く。
    if not naan or len(naan) > MAX_NAAN_LENGTH:
        raise ArkParseError("Not a valid NAAN: bad length")

    naan = naan.lower()  # A1: NAAN だけ小文字化する
    if not set(naan) <= _NAAN_CHARS:  # N3
        raise ArkParseError("Not a valid NAAN: must be betanumeric")

    return ParsedArk(nma=nma, naan=naan, name=name)


def ark_key(naan: str, name: str) -> str:
    """保存・照合に使う正規化キー。

    N2 のため NAAN は文字列のまま連結する。**ハイフンは呼び出し側で落とす**
    （A2。`strip_hyphens` を通した name を渡す）。
    """
    return f"{naan}/{name}"


def strip_hyphens(text: str) -> str:
    """ハイフンを落とす。

    A2: ハイフンは可読性のために入るか、行折り返しで紛れ込むので、**字句比較では
    無視する**。

    Derived from arklet.
    """
    return text.replace("-", "")


def normalize_structural(text: str) -> str:
    """構造文字を正規化する。

    N4: 仕様の正規化 8 段階の最終段。**連続するスラッシュは 1 つに畳む。**

    連続するピリオドは畳まない——`.` は「両側に非構造文字がある場合のみ」構造文字
    として働くので（下記 `is_structural_at`）、`a..b` の `.` はそもそも成分を
    区切っていない。畳むと別の名前になってしまう。
    """
    return re.sub(r"/{2,}", "/", text)


def is_structural_at(text: str, index: int) -> bool:
    """`text[index]` が成分を区切る構造文字か。

    N4: 仕様は `.` について「成分を区切るには**両側に少なくとも 1 つの非構造
    文字**が必要」と定める。これを見ないと `abc..def` から `abc.` という
    **存在しえない祖先候補**が生成される。
    """
    char = text[index]
    if char == "/":
        return True
    if char != ".":
        return False
    if index == 0 or index == len(text) - 1:
        return False
    return (
        text[index - 1] not in QUALIFIER_SEPARATORS
        and text[index + 1] not in QUALIFIER_SEPARATORS
    )


def gen_prefixes(name: str) -> Iterator[str]:
    """name の祖先を**長いものから順に**返す。

    D5: 解決は「末尾から遡り、最初に登録済みの祖先で止まる」＝**最長一致**。
    呼び出し側が最初にヒットしたものを採ればよいように、長い順で返す。

    N4: 構造文字として成立する位置でだけ切る。

    Derived from arklet（`is_structural_at` の条件を追加）。
    """
    for i in range(len(name) - 1, 0, -1):
        if name[i] in QUALIFIER_SEPARATORS and is_structural_at(name, i):
            yield name[:i]


def split_after_normalized(text: str, length: int) -> tuple[str, str]:
    """ハイフンを除いて数えた `length` 文字目の直後で分割する。

    head は保存済み ARK と照合されるのでハイフンを除いて測る。tail は**このリゾルバが
    採番していない資源へのパス**なので、ハイフンも含めて渡されたまま返す。

    Derived from arklet.
    """
    seen = 0
    for i, char in enumerate(text):
        if char == "-":
            continue
        if seen == length:
            return text[:i], text[i:]
        seen += 1
    return text, ""
