"""グローバルへの公開と、公開前の取り下げ。

**NR が縛るのは、外へ出した名前である。** ここで確かめたいのはその 1 点で、
残りはその系である——公開前は解決するか、公開したものが消せないか、消した
名前が二度と採られないか、届かない主体が消せないか。

前半は台帳とドメイン、後半は HTTP と画面と CLI。
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import select

from arkhe.auth.errors import Forbidden
from arkhe.db.models import (
    Ark,
    ArkChange,
    Authority,
    MintReceipt,
    NotDeletable,
    WithdrawnName,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting
from arkhe.domain.authz import Conflict, Invalid, NotFound
from arkhe.domain.minting import mint
from arkhe.domain.queries import narrow_arks, visible_arks


@pytest.fixture
def reserved(db, world):
    """公開前の ARK 1 本。"""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    db.commit()
    return ark


@pytest.fixture
def api(as_principal, root):
    return as_principal(root)


# ================================================================ 台帳の側


def test_既定の採番は公開済み(db, world):
    """**今までと同じ振る舞いを既定にする。** 公開の一手間を既存の呼び出し側に
    課すと、足し忘れた側で「採番できるのに解決しない」が静かに積もる。"""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    assert ark.published_at is not None
    assert ark.is_public


def test_予約した採番は公開前(reserved):
    assert reserved.published_at is None
    assert not reserved.is_public


def test_公開前のARKは削除できる(db, root, reserved):
    key = reserved.ark
    ops.withdraw_ark(db, root, ark=key, reason="申請が取り下げられた")
    db.commit()
    assert db.get(Ark, key) is None


def test_公開したARKは削除できない(db, root, world):
    """**外に出した名前は消さない。** 消せるのは公開前のものだけ。"""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(Conflict):
        ops.withdraw_ark(db, root, ark=ark.ark)


def test_公開したARKはORMの層でも消せない(db, world):
    """**規約を人に守らせない。** `admin_ops` を通らずに消そうとしても落ちる。"""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(NotDeletable):
        db.delete(ark)
        db.flush()


def test_取り下げた名前は二度と採られない(db, root, world, reserved):
    """**予約した文字列は既に人の手に渡っている。** 別の対象に振り直せば、
    外からは NR 違反と見分けがつかない。"""
    key = reserved.ark
    ops.withdraw_ark(db, root, ark=key, reason="不要になった")
    db.commit()
    gone = db.get(WithdrawnName, key)
    assert gone is not None
    assert gone.minted_by == "test" and gone.withdrawn_by == root.client_id
    # 取り込みも拒む（採番は当たっても採り直す——確率でしか確かめられない）
    sh = world["sh_a"]
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="delegated")
    db.flush()
    with pytest.raises(minting.Withdrawn):
        minting.check_importable(db, sh, gone.assigned_name)


def test_公開すると解決を始める(db, root, reserved):
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    assert reserved.published_at is not None


def test_公開は二度呼んでも落ちない(db, root, reserved):
    """**応答だけが失われることがある。** 再送に 409 を返すと、呼び出し側は
    別の口で確かめに行くことになる。"""
    first = ops.publish_ark(db, root, ark=reserved.ark).published_at
    again = ops.publish_ark(db, root, ark=reserved.ark).published_at
    assert first == again


def test_公開はARKの履歴に残る(db, root, reserved):
    """**いつ外に出たかは後から必ず要る。** 監査は NAAN 単位以上しか残さない。"""
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    actions = list(db.scalars(select(ArkChange.action).where(ArkChange.ark == reserved.ark)))
    assert "publish" in actions


def test_取り下げると採番の控えも消える(db, root, world, reserved):
    """控えは ARK を指している。**残せば、消えた行を指す控えだけが生き残る。**"""
    db.add(MintReceipt(client_id="x", request_id="r1", ark=reserved.ark))
    db.commit()
    ops.withdraw_ark(db, root, ark=reserved.ark)
    db.commit()
    assert db.scalars(select(MintReceipt)).all() == []


def test_修飾子がぶら下がっていると取り下げられない(db, root, reserved):
    """**先に下から取り下げる。** 親だけ消すと、継ぐ先の無い部分参照が残る。"""
    minting.register_qualified(db, base=reserved, qualifier="/c3", created_by="t")
    db.commit()
    with pytest.raises(Conflict):
        ops.withdraw_ark(db, root, ark=reserved.ark)


def test_修飾子は公開状態をbaseから継ぐ(db, reserved):
    """部分参照が base より先に世に出ることはない。"""
    part = minting.register_qualified(db, base=reserved, qualifier="/c3", created_by="t")
    assert part.published_at is None


def test_他組織のARKは取り下げられない(db, world, reserved, principal_of):
    """**負の場合。** 取り下げも「触る」操作なので、届かない相手には効かない。"""
    other = principal_of(manager=world["b"])
    with pytest.raises(Forbidden):
        ops.withdraw_ark(db, other, ark=reserved.ark)


def test_無い_ARKの取り下げは404(db, root):
    with pytest.raises(NotFound):
        ops.withdraw_ark(db, root, ark="99999/x9nosuchark")


# ============================================================ 解決の側


def test_公開前のARKは解決しない(api, db, reserved):
    """**まだ無い名前として扱う。** 予約しただけの番号で 200 を返すと、
    公開していない対象の存在と記述が外に出る。"""
    reserved.url = "https://example.ac.jp/draft"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 404


def test_公開前のARKは記述も返さない(api, db, reserved):
    reserved.title = "まだ公開していない観測データ"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}?info")
    assert r.status_code == 404
    assert "まだ公開していない観測データ" not in r.text


def test_公開すれば解決する(api, db, root, reserved):
    reserved.url = "https://example.ac.jp/thing"
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 302
    assert r.headers["location"] == "https://example.ac.jp/thing"


def test_公開前のARKは祖先としても使われない(api, db, reserved):
    """suffix passthrough で拾われては、**公開していない行き先が外に出る。**"""
    reserved.url = "https://example.ac.jp/draft"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}/c3")
    assert r.status_code == 404


# ======================================== 公開した ARK の破棄


@pytest.fixture
def published(db, world):
    """公開済みの ARK 1 本。**普通に採番すればこれになる。**"""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    return ark


def test_RAの運用者は公開したARKを破棄できる(db, root, published):
    """**逃げ道が無いと、必要に迫られた誰かが DB を直接叩く。**
    跡の残らない削除がいちばん悪い。"""
    key = published.ark
    gone = ops.purge_ark(
        db, root, ark=key, reason="裁判所の削除命令", confirm=key
    )
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == key)).all() == []
    assert gone.published_at is not None  # 取り下げと区別が付く
    assert gone.reason == "裁判所の削除命令"


def test_破棄した名前も二度と採られない(db, root, world, published):
    """**約束のうち守れるほうは守る。** 解決は止まるが、その名前が別のものを
    指すことは無い——残った参照は 404 になるだけ。"""
    key = published.ark
    name = published.assigned_name
    ops.purge_ark(db, root, ark=key, reason="誤って投入した", confirm=key)
    db.commit()
    assert db.get(WithdrawnName, key) is not None
    sh = world["sh_a"]
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="delegated")
    db.flush()
    with pytest.raises(minting.Withdrawn):
        minting.check_importable(db, sh, name)


def test_NAAN管理者は破棄できない(db, world, published, principal_of):
    """**負の場合。** 名前空間を預かることと、配った名前を消せることは別。"""
    naan_admin = principal_of(authority=Authority.NAAN, scopes={"ark:purge"})
    with pytest.raises(Forbidden):
        ops.purge_ark(db, naan_admin, ark=published.ark, reason="消したい",
                      confirm=published.ark)
    assert db.get(Ark, published.ark) is not None


def test_組織の管理者は破棄できない(db, world, published, principal_of):
    org = principal_of(manager=world["a"], scopes={"ark:purge"})
    with pytest.raises(Forbidden):
        ops.purge_ark(db, org, ark=published.ark, reason="消したい", confirm=published.ark)


def test_理由の無い破棄はできない(db, root, published):
    """**残らない破棄は、無かったことと同じ。**"""
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="   ", confirm=published.ark)
    assert db.get(Ark, published.ark) is not None


def test_打ち直しが合わなければ破棄しない(db, root, world, published):
    """**一覧を回すスクリプトが、意図せず全件消すことのないように。**"""
    other, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="消す", confirm=other.ark)
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="消す", confirm="")
    assert db.get(Ark, published.ark) is not None


def test_破棄は監査に残る(db, root, published):
    """**system の操作は全件記録される。** 消えた行について残るのはこれと
    `WithdrawnName` だけ。"""
    from arkhe.db.models import AuditEvent

    ops.purge_ark(db, root, ark=published.ark, reason="削除命令", confirm=published.ark)
    db.commit()
    rows = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "purge")))
    assert len(rows) == 1
    assert rows[0].target == published.ark
    assert rows[0].detail["reason"] == "削除命令" and rows[0].detail["published"] is True


def test_破棄した_ARK_は解決しなくなる(api, db, root, published):
    published.url = "https://example.ac.jp/thing"
    db.commit()
    assert api.get(f"/ark:/{published.ark}").status_code == 302
    ops.purge_ark(db, root, ark=published.ark, reason="削除命令", confirm=published.ark)
    db.commit()
    assert api.get(f"/ark:/{published.ark}").status_code == 404


def test_破棄の経路を通らない削除は今までどおり拒まれる(db, root, published):
    """**逃げ道を作っても、扉は閉じたまま。** `purge_ark` が名指ししたセッション
    以外では、公開した行は落ちない。"""
    with pytest.raises(NotDeletable):
        db.delete(published)
        db.flush()
    db.rollback()


def test_破棄の宣言はその_ARK_だけに効く(db, root, world, published):
    """**大域の旗にしない。** 宣言した 1 本のほかは、同じセッションでも落ちない。"""
    from arkhe.db.models import sanctioned_purge

    other, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    with sanctioned_purge(db, published.ark), pytest.raises(NotDeletable):
        db.delete(other)
        db.flush()
    db.rollback()


def test_破棄の宣言は抜けたら残らない(db, root, published):
    """例外で抜けても宣言は消える——**立てっぱなしが起きない**ことが、この
    仕掛けの価値のほとんど。"""
    from arkhe.db.models import sanctioned_purge

    with contextlib.suppress(RuntimeError), sanctioned_purge(db, published.ark):
        raise RuntimeError("途中で落ちた")
    with pytest.raises(NotDeletable):
        db.delete(published)
        db.flush()
    db.rollback()


def test_公開前のARKはpurgeからでも取り下げになる(db, root, reserved):
    """**同じ操作に 2 つの入口を作らない。** 公開前を purge で消しても、
    記録は取り下げのまま（`published_at` は入らない）。"""
    gone = ops.purge_ark(db, root, ark=reserved.ark, reason="下書きを消した",
                         confirm=reserved.ark)
    db.commit()
    assert gone.published_at is None


def test_APIから破棄できる(as_principal, principal_of, db, published):
    """**scope も到達範囲も別に要る。**"""
    ops_client = as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:purge"})
    )
    r = ops_client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "削除命令", "confirm": published.ark},
    )
    assert r.status_code == 200, r.text
    assert r.json()["was_published_at"] is not None
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


def test_delete_scopeだけでは破棄できない(as_principal, principal_of, published):
    client = as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:delete"})
    )
    r = client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "消す", "confirm": published.ark},
    )
    assert r.status_code == 403


def test_NAAN管理者はAPIからも破棄できない(as_principal, principal_of, db, published):
    client = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:purge"})
    )
    r = client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "消す", "confirm": published.ark},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "ARKHE-1310"
    assert db.get(Ark, published.ark) is not None


def test_画面から破棄できるのはRAの運用者だけ(as_principal, principal_of, db, published):
    """**押しても断られるだけのボタンを出さない。** 出し分けと認可は同じ判定。"""
    naan_admin = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:purge", "ark:mint"})
    )
    page = naan_admin.get(f"/admin/arks/{published.ark}")
    assert "/purge" not in page.text

    root_ui = as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:purge", "ark:mint"})
    )
    page = root_ui.get(f"/admin/arks/{published.ark}")
    assert "/purge" in page.text
    r = root_ui.post(
        f"/admin/arks/{published.ark}/purge",
        data={"reason": "削除命令", "confirm": f"ark:{published.ark}"},
    )
    assert r.status_code == 303
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


# ================================================ 閉域のリゾルバ


@pytest.fixture
def closed(app, settings, as_principal, root):
    """**閉域に置いたリゾルバ。** 公開前の ARK も解決する。

    設定 1 つで変わるので、`settings` を差し替えるだけでよい——判断の置き場所は
    1 か所（`resolution.serves`）で、公開の口と共有している。
    """
    settings.resolve_unpublished = True
    return as_principal(root)


def test_閉域のリゾルバは公開前のARKを解決する(closed, db, reserved):
    """**閉じた網の中で採番した ARK を、その網のリゾルバが解決できなければ
    配る意味が無い。**「閉じた対象にも同じ形の PID を配る」が成り立たなくなる。"""
    reserved.url = "https://closed.example.ac.jp/thing"
    db.commit()
    r = closed.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 302
    assert r.headers["location"] == "https://closed.example.ac.jp/thing"


def test_閉域のリゾルバは公開前のARKの記述も返す(closed, db, reserved):
    reserved.title = "閉域の観測データ"
    db.commit()
    r = closed.get(f"/ark:/{reserved.ark}?info")
    assert r.status_code == 200
    assert "閉域の観測データ" in r.text


def test_閉域のリゾルバでも公開前なら削除できる(closed, db, root, reserved):
    """**解決することと、消せることは別。** 名前は `WithdrawnName` に残るので、
    消した後にその名前が**別のものを指すことはない**（NR が守るのはそこ）。"""
    ops.withdraw_ark(db, root, ark=reserved.ark, reason="閉域でも取りやめはある")
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == reserved.ark)).all() == []


def test_公開のリゾルバは既定で公開前を解決しない(api, db, reserved, settings):
    """**既定は漏れない側。** 取り違えたときに出る側を既定にしない。"""
    assert settings.resolve_unpublished is False
    reserved.url = "https://closed.example.ac.jp/thing"
    db.commit()
    assert api.get(f"/ark:/{reserved.ark}").status_code == 404


# ================================================================ HTTP


def test_APIから公開できる(as_principal, principal_of, db, world):
    org = principal_of(manager=world["a"], scopes={"ark:mint"})
    client = as_principal(org)
    made = client.post("/api/mint", json={"reserve": True, "url": "https://x.example/1"})
    assert made.status_code == 201
    assert made.json()["published_at"] is None

    ark = made.json()["ark"]
    out = client.post("/api/publish", json={"ark": ark})
    assert out.status_code == 200
    assert out.json()["published_at"] is not None


def test_APIから取り下げられる(as_principal, principal_of, db, world):
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    r = client.post("/api/delete", json={"ark": ark, "reason": "登録を取りやめた"})
    assert r.status_code == 200
    assert r.json()["ark"] == ark
    assert client.post("/api/delete", json={"ark": ark}).status_code == 404


def test_公開したARKの削除は409(as_principal, principal_of, world):
    """**tombstone との違いを状態符号で示す。** 値も権限も正しいが、対象が
    その状態にない。"""
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={}).json()["ark"]
    r = client.post("/api/delete", json={"ark": ark})
    assert r.status_code == 409
    assert r.json()["code"] == "ARKHE-1501"


def test_delete_scopeが無ければ取り下げられない(as_principal, principal_of, world):
    """**負の場合。** 採番できることと、取り下げられることは別。"""
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:update"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    assert client.post("/api/delete", json={"ark": ark}).status_code == 403


def test_他組織のARKはAPIからも取り下げられない(as_principal, principal_of, db, world, reserved):
    other = principal_of(manager=world["b"], scopes={"ark:delete"})
    r = as_principal(other).post("/api/delete", json={"ark": reserved.ark})
    assert r.status_code in (403, 404)
    assert db.get(Ark, reserved.ark) is not None


# ================================================================ 画面と CLI


@pytest.fixture
def admin(as_principal, principal_of):
    """画面の主体。**scope も見る**ので、持たせて入る。"""
    return as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:mint", "ark:delete"})
    )


def test_画面から公開できる(admin, db, reserved):
    r = admin.post(f"/admin/arks/{reserved.ark}/publish")
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Ark, reserved.ark).published_at is not None


def test_画面から取り下げられる(admin, db, reserved):
    r = admin.post(f"/admin/arks/{reserved.ark}/delete", data={"reason": "下書きを消した"})
    assert r.status_code == 303
    # **別のセッションで消えている。** 手元の同一性マップではなく台帳に訊く。
    assert db.scalars(select(Ark.ark).where(Ark.ark == reserved.ark)).all() == []


def test_画面の詳細に公開前と出る(admin, reserved):
    page = admin.get(f"/admin/arks/{reserved.ark}")
    assert "公開前" in page.text


def test_一覧は状態で絞れる(db, root, world, reserved):
    """**画面と CLI は同じ式を通る。** 絞り込みを 2 か所に書かない。"""
    mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    only = db.scalars(narrow_arks(visible_arks(root), state="reserved")).all()
    assert [a.ark for a in only] == [reserved.ark]
    rest = db.scalars(narrow_arks(visible_arks(root), state="public")).all()
    assert reserved.ark not in [a.ark for a in rest]
