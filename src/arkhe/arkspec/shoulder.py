"""shoulder の規約と割当。

shoulder は NAAN の下位名前空間で、**組織（Manager）への名前空間の委譲**を担う。

**全 NAAN で使う**（`design_ark_multitenant_authz.md` §2.1.1）。1 組織 1 NAAN の
岡崎3研究所でも default shoulder を必ず 1 つ持たせる。使わないと NAAN ごとに
モデルが分岐し、**first-digit 規約が NAAN によって成立したりしなかったりする**。

受け入れ条件:
  B2  shoulder は単一セグメント（多段を許さない）
  N5  **公衆が読める意味を持たせない。** 分野・装置は ARK の名前ではなく
      `format` / payload で表現する
"""

from __future__ import annotations

import re
import secrets

from .betanumeric import CONSONANTS

#: first-digit 規約: shoulder は NAAN の末尾から**最初の数字までを含む**範囲。
#: 区切り文字なしで shoulder と blade の境界を判定できるのはこの規約による。
#: 子音の並び＋末尾に数字 1 桁。母音と `l` を除くので偶然の単語にならない。
SHOULDER_PATTERN = re.compile(rf"^/[{CONSONANTS}]+[0-9]$")

#: 採用する長さ: 子音 2 ＋数字 1 の 3 文字。19*19*9 = 3,610 組織を収容できる
#: （800 組織で使用率 22.2%）。`ark_ra_model.md` §5.0。
DEFAULT_SHOULDER_LENGTH = 3


class InvalidShoulder(ValueError):
    pass


def validate_shoulder(shoulder: str) -> None:
    """first-digit 規約に照らして検証する。

    B2: shoulder のあとのスラッシュを明確に禁じる——それは「手前の部分が実在の
    対象を名指し、ARK 全体がその対象に含まれる」という**二重に誤った含意**を持つ。
    """
    if not shoulder.startswith("/"):
        raise InvalidShoulder("Shoulders must start with a forward slash")
    if not SHOULDER_PATTERN.match(shoulder):
        raise InvalidShoulder(
            "A shoulder must be a single segment of lowercase betanumeric "
            "consonants ending in one digit, e.g. '/x5'. It may not contain a "
            "further '/' or '.', which would falsely imply containment."
        )


def generate_shoulder(length: int = DEFAULT_SHOULDER_LENGTH) -> str:
    """規約に沿った不透明な shoulder を 1 つ返す。

    **連番割当は採らない。** `/bb1`, `/bb2`, `/bb3` と振ると **shoulder が加入順を
    漏らす**——これは opacity の趣旨（公衆に意味を読ませない）に反する。NOID と
    同じく乱数で引き、衝突は呼び出し側がリトライする。

    shoulder は秘密ではない（公開名前空間の目印）。ここでの不透明性は
    「推測困難」ではなく「**意味を持たない**」こと。
    """
    if length < 2:
        raise ValueError("shoulder length must be >= 2 (consonants + one digit)")
    body = "".join(secrets.choice(CONSONANTS) for _ in range(length - 1))
    # 末尾の数字は 0-9 すべて使う。betanumeric は**母音を除いてある**ので `o` が
    # 存在せず、`0` と紛れる相手がいない。除くと容量が 1 割減るだけで得がない。
    return "/" + body + secrets.choice("0123456789")


def shoulder_capacity(length: int = DEFAULT_SHOULDER_LENGTH) -> int:
    """その長さで収容できる shoulder 数。

    3 文字（子音 2 ＋数字 1）で 19² × 10 = **3,610**。JAIRO Cloud の 800 組織に
    対して使用率 22.2%・4.5 倍の余裕（`ark_ra_model.md` §5.0）。
    """
    return len(CONSONANTS) ** (length - 1) * 10


def split_shoulder(name: str) -> tuple[str, str]:
    """first-digit 規約で name を (shoulder, blade) に分ける。

    **区切り文字なしで境界を判定できる**ことがこの規約の目的。shoulder は
    先頭から最初の数字までを含む。数字が無ければ shoulder は空。
    """
    for i, char in enumerate(name):
        if char.isdigit():
            return name[: i + 1], name[i + 1 :]
    return "", name
