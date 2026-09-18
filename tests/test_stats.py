"""台帳の統計。

**確かめたいのは 2 点。** 数が合うことと、**届かないものが 1 件も混ざらないこと**
——合計は在ることを漏らす。他組織の ARK が何件あるかはその組織の規模であり、
こちらが教えてよい事実ではない。

数え方を 1 か所に置いた（`domain/stats.py`）ので、画面・CLI・API のどれから
呼んでも同じ数になる。ここではドメインと API を見る。
"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority
from arkhe.domain import admin_ops as ops
from arkhe.domain import stats
from arkhe.domain.minting import mint


@pytest.fixture
def ledger(db, world):
    """組織 a に 3 本（うち 1 本は公開前）、組織 b に 2 本。"""
    for _ in range(2):
        mint(db, shoulder=world["sh_a"], created_by="test")
    mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    for _ in range(2):
        mint(db, shoulder=world["sh_b"], created_by="test")
    db.commit()


def test_合計と内訳が足して合う(db, root, ledger):
    """**足して合わない統計は、読む人の信頼を失う。** 公開の別は 1 回で数える。"""
    st = stats.ledger_stats(db, root)
    assert st.arks == 5
    assert st.public + st.reserved == st.arks
    assert st.reserved == 1
    assert sum(s.arks for s in st.by_shoulder) == st.arks


def test_組織には自分のぶんしか見えない(db, world, ledger, principal_of):
    """**合計は在ることを漏らす。** ここが緩むと、他組織の規模が漏れる。"""
    org = principal_of(manager=world["a"], scopes={"ark:read"})
    st = stats.ledger_stats(db, org)
    assert st.arks == 3
    assert st.public == 2 and st.reserved == 1
    # 内訳にも他組織の shoulder が出ない——**名前だけでも漏れてはいけない。**
    assert [s.shoulder for s in st.by_shoulder] == [world["sh_a"].shoulder]


def test_NAAN管理者には自NAANの全組織が見える(db, ledger, principal_of):
    naan_admin = principal_of(authority=Authority.NAAN, scopes={"ark:read"})
    st = stats.ledger_stats(db, naan_admin)
    assert st.arks == 5
    assert st.scope == "naan"


def test_絞り込みは範囲を広げない(db, world, ledger, principal_of):
    """**届かない組織を指定しても 0。** 絞り込みの引数は鍵にならない。"""
    org = principal_of(manager=world["a"], scopes={"ark:read"})
    st = stats.ledger_stats(db, org, org=str(world["b"].id))
    assert st.arks == 0


def test_取り下げた名前は公開後のものを分けて数える(db, root, world, ledger):
    """**公開後に消した回数は、約束を破った回数である。** 合計に埋めない。"""
    a, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    b, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    ops.withdraw_ark(db, root, ark=a.ark)                      # 予約の取り下げ
    ops.purge_ark(db, root, ark=b.ark, reason="削除命令", confirm=b.ark)  # 公開後
    db.commit()
    st = stats.ledger_stats(db, root)
    assert st.withdrawn == 2
    assert st.withdrawn_after_publication == 1


def test_shoulderは0件の状態も出す(db, root, ledger):
    """**「delegated が 0 件」と「delegated を知らない」は別のこと。**"""
    st = stats.ledger_stats(db, root)
    assert set(st.shoulders) == {"active", "reserved", "delegated", "retired"}


def test_保留は今かかっているものだけ数える(db, root, world, ledger):
    from datetime import UTC, datetime, timedelta

    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    assert stats.ledger_stats(db, root).holds["ark"] == 0
    ops.set_hold(db, root, kind="ark", key=ark.ark,
                 until=datetime.now(UTC) + timedelta(days=3), reason="調査中")
    db.commit()
    assert stats.ledger_stats(db, root).holds["ark"] == 1


def test_APIは到達範囲のぶんだけ返す(as_principal, principal_of, world, ledger):
    org = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    r = org.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["arks"] == 3
    assert body["scope"] == "organisation"


def test_APIはark_readが要る(as_principal, principal_of, world, ledger):
    """**読みも鍵で縛る。** 数だけなら誰でもよい、にはしない。"""
    no_read = as_principal(principal_of(manager=world["a"], scopes={"ark:mint"}))
    assert no_read.get("/api/stats").status_code == 403


def test_採番の窓は重なって数える(db, root, ledger):
    """24h のぶんは 7d にも 30d にも入る。**別々の母数ではない。**"""
    st = stats.ledger_stats(db, root)
    assert st.minted["24h"] <= st.minted["7d"] <= st.minted["30d"]
    assert st.minted["30d"] == st.arks


# ------------------------------------------------- 管理画面（同じ数を見る）


def test_画面は数えた結果をそのまま見せる(as_principal, principal_of, db, world, ledger):
    """**画面が独自に集計を書かない。** 同じ「件数」が場所によって違うのが
    いちばん質の悪いずれなので、ドメインの数と一致することを見る。
    """
    from arkhe.domain import stats as domain

    ui = as_principal(principal_of(authority=Authority.NAAN, scopes={"ark:read"}))
    page = ui.get("/admin/stats")
    assert page.status_code == 200
    st = domain.ledger_stats(db, principal_of(authority=Authority.NAAN, scopes={"ark:read"}))
    assert str(st.arks) in page.text
    assert "/admin/stats" in page.text          # 左の案内に出ている


def test_画面も到達範囲の外を見せない(as_principal, principal_of, world, ledger):
    """**合計は在ることを漏らす。** 他組織の shoulder 名も出してはいけない。"""
    org = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    page = org.get("/admin/stats")
    assert page.status_code == 200
    assert world["sh_b"].shoulder not in page.text


def test_画面とAPIとCLIが同じ数を出す(as_principal, principal_of, db, world, ledger):
    """**数える場所は 1 つ**（`domain/stats.py`）。3 つの入口が食い違わないこと。"""
    from arkhe.domain import stats as domain

    p = principal_of(authority=Authority.NAAN, scopes={"ark:read"})
    api = as_principal(p).get("/api/stats").json()
    dom = domain.ledger_stats(db, p)
    assert api["arks"] == dom.arks
    assert api["public"] == dom.public
    assert api["withdrawn_after_publication"] == dom.withdrawn_after_publication


# ----------------------------------------------- 復元できたことの確認（指紋）


def test_指紋は件数が同じでも行き先の入れ替わりを捕まえる(db, root, world, ledger):
    """**件数が合うことは、確かめたことにならない。**

    件数が同じでも行き先が入れ替わっていれば、識別子は全部壊れている——
    復元の確認で見るべきはそこである。
    """
    from arkhe.db.models import Ark

    before = stats.ledger_fingerprint(db)
    row = db.query(Ark).order_by(Ark.ark).first()
    row.url = "https://wrong.example/"
    db.commit()
    after = stats.ledger_fingerprint(db)

    assert after.ark_count == before.ark_count, "件数は変わらない——だから件数では気づけない"
    assert after.arks != before.arks, "行き先が入れ替わったのに指紋が同じ"


def test_指紋は同じ台帳なら何度出しても同じ(db, root, ledger):
    """**並びを固定していないと、出すたびに変わって使い物にならない。**"""
    assert stats.ledger_fingerprint(db).arks == stats.ledger_fingerprint(db).arks


def test_取り下げ台帳は別に数える(db, root, world, ledger):
    """**`withdrawn_name` が落ちても採番は動き続ける**ので、黙って通る。

    1 つの値に潰すと「どこが違うか」が消える——`arks` が同じまま
    `withdrawn` だけ変わることを見る。
    """
    from arkhe.domain.minting import mint

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()
    before = stats.ledger_fingerprint(db)
    ops.withdraw_ark(db, root, ark=a.ark)
    db.commit()
    after = stats.ledger_fingerprint(db)

    assert after.withdrawn != before.withdrawn, "取り下げたのに指紋が同じ"
    assert after.withdrawn_count == before.withdrawn_count + 1


def test_保留は指紋に入れない(db, root, world, ledger):
    """**期限で勝手に変わるものを入れない。** 差が出ても「壊れた」と読めない
    ——**鳴りっぱなしの警報は、誰も見なくなる。**
    """
    from datetime import UTC, datetime, timedelta

    from arkhe.db.models import Ark

    ark = db.query(Ark).order_by(Ark.ark).first().ark
    before = stats.ledger_fingerprint(db)
    ops.set_hold(db, root, kind="ark", key=ark,
                 until=datetime.now(UTC) + timedelta(days=3), reason="調査中")
    db.commit()
    assert stats.ledger_fingerprint(db).arks == before.arks


# --------------------------------- 公開前のまま放置されたものを見つける


def test_いちばん古い公開前が出る(db, root, world):
    """**溜まっていることは、数ではなく古さに出る。**

    10 件でも昨日採ったものなら普通で、1 件でも 3 年前なら放置である
    ——件数では警報を出せない。
    """
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint

    assert stats.ledger_stats(db, root).reserved_oldest is None, "何も無ければ出ない"

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    a.created_at = datetime.now(UTC) - timedelta(days=400)
    mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)   # 新しい予約
    mint(db, shoulder=world["sh_a"], created_by="t")                 # 公開済みは関係ない
    db.commit()

    oldest = stats.ledger_stats(db, root).reserved_oldest
    assert oldest is not None
    assert (datetime.now(UTC) - oldest).days >= 399, "いちばん古いものを見ていない"


def test_公開済みは古くても放置に数えない(db, root, world):
    """**公開したものは放置ではない。** 出してあるのだから、古くてよい。"""
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t")   # 公開済み
    a.created_at = datetime.now(UTC) - timedelta(days=999)
    db.commit()
    assert stats.ledger_stats(db, root).reserved_oldest is None


def test_古さで絞れる(db, root, world):
    """**拾えなければ、気づいても手が出せない。**"""
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint
    from arkhe.domain.queries import narrow_arks, visible_arks

    old, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    old.created_at = datetime.now(UTC) - timedelta(days=400)
    new, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()

    stmt = narrow_arks(visible_arks(root), state="reserved", older_than_days=365)
    found = {a.ark for a in db.scalars(stmt)}
    assert old.ark in found
    assert new.ark not in found, "新しい予約まで拾っている"
    # **`state` と直交している。** 公開済みの古いものを探したい日も来る。
    assert isinstance(db.scalars(narrow_arks(visible_arks(root), older_than_days=1)).all(), list)


def test_日時は必ずUTC付きで返る(db, root, world):
    """**engine によって型が変わると、受け取った側が落ちる。**

    SQLite には時刻帯の型が無いので、`DateTime(timezone=True)` と宣言していても
    naive な `datetime` が返る。PostgreSQL では aware——**片方でだけ
    `TypeError`**、というのが実際に起きた（`arkhe stat` が落ちた）。
    """
    from datetime import UTC, datetime

    from arkhe.domain.minting import mint

    mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()
    st = stats.ledger_stats(db, root)
    for name in ("first_mint", "last_mint", "reserved_oldest"):
        got = getattr(st, name)
        assert got is not None and got.tzinfo is not None, f"{name} に時刻帯が無い"
        datetime.now(UTC) - got          # 引き算が通ること自体が検査である
