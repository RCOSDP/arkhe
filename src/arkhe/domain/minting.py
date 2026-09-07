"""採番。**既存 ARK を黙って上書きしない**（E1）ことを構造で守る。

arklet で最重大の欠陥は「主キー衝突が UPDATE に化け、既存 ARK の向き先を黙って
書き換える」だった。Django 版は `create()`（内部で `force_insert`）で防いでいた。
SQLAlchemy では **`session.add()` は常に INSERT** なので同じ性質が得られるが、
`merge()` を使うと UPDATE に化ける。**この層以外で Ark を作らない**ことで守る。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arkhe.arkspec.betanumeric import check_digit_base, generate_noid, noid_check_digit
from arkhe.arkspec.naming import (
    MAX_NAME_LENGTH,
    ark_key,
    compact_ark,
    normalize_percent,
    normalize_structural,
    strip_hyphens,
)
from arkhe.db.models import Ark, Shoulder

MINT_COLLISION_RETRIES = 10
NOID_LENGTH = 8


class AlreadyRegistered(Exception):
    """B4: 修飾子付き ARK が既に在る。**上書きせず呼び出し側に返す。**"""


class QualifierForm(ValueError):
    """修飾子が `/` でも `.` でも始まっていない。"""


class QualifierOutsideBase(ValueError):
    """修飾子が base の内側を指していない。"""

    def __init__(self, qualifier: str):
        self.qualifier = qualifier
        super().__init__(f"qualifier does not point inside the base: {qualifier!r}")


class NameTooLong(ValueError):
    """名前が索引できる長さを超えた。**仕様の下限（255）まで**は受ける。"""

    def __init__(self, length: int, limit: int):
        self.length, self.limit = length, limit
        super().__init__(f"name is {length} octets, limit is {limit}")


def mint(
    session: Session, *, shoulder: Shoulder, created_by: str = "", **fields
) -> tuple[Ark, int]:
    """衝突をリトライしながら 1 本採番する。戻り値は (Ark, 衝突回数)。

    衝突は**握りつぶさず数えて採り直す**。回数を返すのは、名前空間の枯渇が
    静かに進むのを検知できるようにするため（衝突率が上がったら桁を増やす合図）。
    """
    collisions = 0
    for _ in range(MINT_COLLISION_RETRIES):
        noid = generate_noid(NOID_LENGTH)
        stem = f"{shoulder.shoulder.lstrip('/')}{noid}"
        digit = noid_check_digit(check_digit_base(shoulder.naan, stem))
        name = f"{stem}{digit}"
        ark = Ark(
            ark=ark_key(shoulder.naan, name),
            naan=shoulder.naan,
            shoulder_id=shoulder.id,
            assigned_name=name,
            created_by=created_by,
            updated_by=created_by,
            **fields,
        )
        try:
            with session.begin_nested():  # SAVEPOINT。衝突しても外側を巻き込まない
                session.add(ark)
                session.flush()
        except IntegrityError:
            collisions += 1
            continue
        return ark, collisions
    raise RuntimeError(f"gave up minting after {collisions} collision(s)")


def register_qualified(
    session: Session, *, base: Ark, qualifier: str, created_by: str = "", **fields
) -> Ark:
    """B4: **既存 ARK に修飾子を付けた行を登録する。**

    「NOID を省略した採番」ではない。**修飾子は新しい名前ではなく、既存の名前に
    対する部分参照**なので、チェックディジットも付け直さない（N7: 検査桁は base
    compact name に対して計算され、修飾子を含まない）。

    用途は **suffix passthrough の上書き**——既定では祖先の URL に修飾子を
    continuation として足すが、「このサブツリーだけ別ストレージ」「この変換版だけ
    別の所在」を表したいときに、その 1 点だけ明示的に登録する。

    `shoulder` は base から継ぐ。**別の shoulder に生やせてはいけない**——
    修飾子は base の名前空間の内側にあるものだから。
    """
    if not qualifier.startswith(("/", ".")):
        raise QualifierForm("a qualifier must begin with '/' or '.'")
    # A4: 修飾子にも %-エンコードは来る（`%2F` は「区切りではない `/`」）。
    # **解決側と同じ式を通す**——揃えないと、登録できたのに解決できない行ができる。
    name = strip_hyphens(normalize_structural(normalize_percent(base.assigned_name + qualifier)))
    if name == base.assigned_name or not name.startswith(base.assigned_name):
        raise QualifierOutsideBase(qualifier)
    if len(name) > MAX_NAME_LENGTH:
        # **DB のエラーで落とさない。** 仕様（§3.1）が受け取る側に義務づけるのは
        # 255 オクテットまでで、我々もそこまでを索引できる。長い名前を作る側は
        # 「受け取る実装が索引できないかもしれない」と仕様に警告されている。
        raise NameTooLong(len(name), MAX_NAME_LENGTH)
    ark = Ark(
        ark=ark_key(base.naan, name),
        naan=base.naan,
        shoulder_id=base.shoulder_id,
        assigned_name=name,
        created_by=created_by,
        updated_by=created_by,
        **fields,
    )
    try:
        with session.begin_nested():
            session.add(ark)
            session.flush()
    except IntegrityError as exc:
        # E1: 既に在るものを黙って上書きしない。更新は `update` の仕事。
        raise AlreadyRegistered(
            f"{compact_ark(ark_key(base.naan, name))} は既に登録済み"
        ) from exc
    return ark
