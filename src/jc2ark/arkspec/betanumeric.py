"""betanumeric 文字集合と NOID チェックディジット。

ARK の名前は「母音と `l` を除く数字＋子音」＝ betanumeric で構成する。これは
**転記されることを前提にした規約**である（`ark_domain_pid_design.md` §7）:

- ラベルから打ち込むとき `l`/`1`・`O`/`0` を誤らない
- 偶然の単語ができない
- NCDA チェックディジットが単一文字誤りと隣接転置を検出する

Derived from arklet (https://github.com/internetarchive/arklet), MIT License,
Copyright (c) Internet Archive. See LICENSE.

受け入れ条件: N6（betanumeric 限定）・N7（チェックディジットの計算範囲・適合を維持）
"""

from __future__ import annotations

import secrets

#: 数字 10 ＋ 子音 19（母音 aeiou と `l` を除く）＝ 29 文字。
BETANUMERIC = "0123456789bcdfghjkmnpqrstvwxz"

#: shoulder に使える子音のみ（first-digit 規約の前半部分）。
CONSONANTS = "bcdfghjkmnpqrstvwxz"

_MODULUS = len(BETANUMERIC)  # 29


def noid_check_digit(name: str) -> str:
    """base compact name に対する NCDA チェックディジットを返す。

    N7: 仕様は「チェックディジットは blade の末尾に置き、**label を除いた
    base compact name** に対して計算する」「**修飾子は含めない**」と定めている。
    呼び出し側は `f"{naan}{shoulder}{noid}"` を渡すこと。

    betanumeric 以外の文字はスコアに算入しない（NOID 原典の挙動）。

    Derived from arklet.
    """
    total = 0
    for position, char in enumerate(name, start=1):
        score = BETANUMERIC.find(char)
        if score > 0:
            total += position * score
    return BETANUMERIC[total % _MODULUS]


def verify_check_digit(base_with_digit: str) -> bool:
    """末尾 1 文字をチェックディジットとみなして検証する。

    ⚠️ **渡すのは base compact name 全体**——すなわち `naan + shoulder + noid + cd`。
    blade だけを渡すと必ず False になる。N7 のとおり検査桁は label を除いた
    base compact name に対して計算されるので、NAAN を含めないと合わない。
    通常は `verify_ark_check_digit(naan, name)` を使うこと。
    """
    if len(base_with_digit) < 2:
        return False
    body, digit = base_with_digit[:-1], base_with_digit[-1]
    return noid_check_digit(body) == digit


def verify_ark_check_digit(naan: str, name: str) -> bool:
    """`ark:/<naan>/<name>` の検査桁を検証する。**呼び出し側はこちらを使う。**

    D1: 未登録 ARK に対してこれを検証し、不一致なら**転記ミスを明示した 404**
    を返す。検証せずに転送すると、NCDA が保証している「単一文字誤り・隣接転置の
    検出」を捨てることになる。

    修飾子（`/` や `.` 以降）は検査桁の対象外（N7）なので、**base name だけを
    渡すこと**。祖先探索で切り出した base を渡す想定。
    """
    return verify_check_digit(f"{naan}{name}")


def generate_noid(length: int) -> str:
    """betanumeric の乱数列を返す。

    Derived from arklet.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    return "".join(secrets.choice(BETANUMERIC) for _ in range(length))
