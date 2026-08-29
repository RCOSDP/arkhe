"""一覧の絞り込み。**画面も CLI も、ここを呼ぶ。**

`admin_ops` が「何をするか」を持つのに対し、ここは「何が見えるか」を持つ。

到達範囲の判定を 2 か所に書くと、片方だけ直したときに**画面には出ないものが
CLI には出る**——そして気づくのは、見えてはいけないものが見えた後になる。
検索条件も同じで、画面が 3 つの項目を見て CLI が 1 つしか見なければ、
同じ言葉で引いたのに結果が違う、が起きる。
"""

from __future__ import annotations

from sqlalchemy import Select, select

from arkhe.auth.principal import Principal
from arkhe.db.models import Ark, Manager, Shoulder


def visible_arks(p: Principal) -> Select:
    """**到達範囲でそのまま絞る。**

    システム管理者は全件、NAAN 単位はその NAAN、組織単位は自組織の shoulder に
    限る——一覧の絞り込みと認可を別々に書かない。
    """
    stmt = select(Ark)
    if not p.is_system:
        stmt = stmt.where(Ark.naan == p.naan)
    if not p.is_naan_wide:
        # 主体が shoulder に固定されていればそれだけ（採番できる範囲と同じ絞り方）。
        if p.shoulder_id is not None:
            stmt = stmt.where(Ark.shoulder_id == p.shoulder_id)
        else:
            stmt = stmt.where(
                Ark.shoulder_id.in_(
                    select(Shoulder.id).where(Shoulder.manager_id == p.manager_id)
                )
            )
    return stmt


def narrow_arks(stmt: Select, *, naan: str = "", org: str = "", q: str = "") -> Select:
    """絞り込みを重ねる。**到達範囲を広げる手段ではない。**

    `visible_arks` で先に絞ったものに重ねるので、届かない NAAN や組織を指定しても
    何も出ない——**絞り込みの引数は、見える範囲の外に出る鍵にはならない。**

    `naan` は今のところ CLI からしか渡らない（画面は組織で絞る）。片方にしか
    無いのは入口の違いで、**どちらも同じ式を通る**。
    """
    if naan.strip():
        stmt = stmt.where(Ark.naan == naan.strip())
    if str(org).strip().isdigit():
        stmt = stmt.where(
            Ark.shoulder_id.in_(
                select(Shoulder.id).where(Shoulder.manager_id == int(str(org).strip()))
            )
        )
    term = q.strip()
    if term:
        # **ARK そのものと、行き先と、題名で引く。** 運用で手元にあるのはどれか
        # 分からないので、3 つとも見る。
        like = f"%{term}%"
        stmt = stmt.where(Ark.ark.ilike(like) | Ark.url.ilike(like) | Ark.title.ilike(like))
    return stmt


def selectable_orgs(p: Principal) -> Select:
    """絞り込みに出す組織。**届く範囲のものだけ。**"""
    stmt = select(Manager).order_by(Manager.naan, Manager.name)
    if not p.is_system:
        stmt = stmt.where(Manager.naan == p.naan)
    return stmt
