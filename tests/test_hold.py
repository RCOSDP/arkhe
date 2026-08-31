"""転送の一時停止（hold）。

**止めるのは転送であって、解決ではない。** ここで確かめたいのはその一点で、
残りはその系である——記述は答え続けるか、期限は勝手に切れるか、狭いほうが
優先するか、止められない主体が止められないか。

前半は決定ロジック（DB を使わない）、後半は HTTP と台帳。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Ark, ArkChange, Authority, Naan, Shoulder
from arkhe.domain import admin_ops as ops
from arkhe.domain.authz import Invalid
from arkhe.domain.minting import mint
from arkhe.domain.resolution import ArkRepository, Inflection, Outcome, resolve

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=3)
EARLIER = NOW - timedelta(days=1)


# ============================================================ 決定ロジック


@dataclass
class FakeNaan:
    is_authoritative: bool = True
    redirect: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""


@dataclass
class FakeShoulder:
    redirect: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""
    naan_obj: FakeNaan | None = None


@dataclass
class FakeArk:
    url: str = "https://example.ac.jp/thing"
    commitment: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""
    shoulder: FakeShoulder | None = None


@dataclass
class FakeRepo(ArkRepository):
    arks: dict = field(default_factory=dict)
    naans: dict = field(default_factory=dict)
    shoulders: dict = field(default_factory=dict)

    def get_ark(self, key):
        return self.arks.get(key)

    def get_arks(self, keys):
        return {k: self.arks[k] for k in keys if k in self.arks}

    def get_naan(self, naan):
        return self.naans.get(naan)

    def get_shoulder(self, naan, shoulder):
        return self.shoulders.get((naan, shoulder))


def _repo(ark: FakeArk) -> FakeRepo:
    return FakeRepo(arks={"99999/x9abc": ark}, naans={"99999": FakeNaan()})


def test_保留中は転送せず記述を返す():
    """**404 でも 503 でもない。** その識別子は存在していて、行き先を出さないだけ。"""
    res = resolve(
        _repo(FakeArk(hold_until=LATER, hold_reason="移行中")), "99999", "x9abc", now=NOW
    )
    assert res.outcome is Outcome.DESCRIBE
    assert res.status == 200
    assert res.hold.reason == "移行中"
    assert res.hold.scope == "ark"


def test_期限が切れた保留は効かない():
    """**戻し忘れが残らない。** バッチで戻すのではなく、解決のたびに時計を見る。"""
    res = resolve(_repo(FakeArk(hold_until=EARLIER)), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.REDIRECT


def test_保留中でも記述の問い合わせは答える():
    """`?info` も `??` も止めない。**永続性の宣言を引っ込めることになる。**"""
    res = resolve(
        _repo(FakeArk(hold_until=LATER)), "99999", "x9abc", Inflection.POLICY, now=NOW
    )
    assert res.outcome is Outcome.DESCRIBE
    assert res.hold is not None


def test_shoulderの保留は配下のARKに効く():
    ark = FakeArk(shoulder=FakeShoulder(hold_until=LATER, hold_reason="委譲先が落ちている"))
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.DESCRIBE
    assert res.hold.scope == "shoulder"


def test_NAANの保留は配下すべてに効く():
    ark = FakeArk(shoulder=FakeShoulder(naan_obj=FakeNaan(hold_until=LATER)))
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.hold.scope == "naan"


def test_狭いほうの理由を返す():
    """1 件を止めた理由のほうが、名前空間ごと止めた理由より具体的である。"""
    ark = FakeArk(
        hold_until=LATER,
        hold_reason="この 1 件",
        shoulder=FakeShoulder(hold_until=LATER, hold_reason="名前空間ごと"),
    )
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.hold.scope == "ark"
    assert res.hold.reason == "この 1 件"


#: 検査桁が合う名前（`test_resolution.py` と同じ固定値）。**委譲の経路は
#: 検査桁の検証より後**にあるので、ここだけ正しい名前が要る。
GOOD = "kb1d191j10ds"


def test_委譲した名前空間も止められる():
    """台帳に行が無くても止まる。**委譲先を上位から止められるのはここだけ。**"""
    repo = FakeRepo(
        naans={"99999": FakeNaan()},
        shoulders={
            ("99999", "/kb1"): FakeShoulder(
                redirect="https://sub.example.ac.jp/ark:/$id",
                hold_until=LATER,
                hold_reason="委譲先が落ちている",
            )
        },
    )
    res = resolve(repo, "99999", GOOD, now=NOW)
    assert res.outcome is Outcome.HELD
    assert res.status == 200
    assert res.hold.reason == "委譲先が落ちている"


def test_保留していない委譲は通る():
    repo = FakeRepo(
        naans={"99999": FakeNaan()},
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://sub.example.ac.jp/$id")},
    )
    assert resolve(repo, "99999", GOOD, now=NOW).outcome is Outcome.REDIRECT


def test_他所のNAANへの取次も止められる():
    repo = FakeRepo(
        naans={
            "12345": FakeNaan(
                is_authoritative=False, redirect="https://other.example", hold_until=LATER
            )
        }
    )
    assert resolve(repo, "12345", "abc", now=NOW).outcome is Outcome.HELD


def test_素のdatetimeも保留として扱う():
    """**SQLite は tz を落とす。** そこで例外になると、止めたつもりが転送され続ける。"""
    naive = LATER.replace(tzinfo=None)
    res = resolve(_repo(FakeArk(hold_until=naive)), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.DESCRIBE


# ================================================================ 台帳と HTTP


@pytest.fixture
def minted(db, world):
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    return ark


@pytest.fixture
def api(as_principal, root):
    return as_principal(root)


def _in(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def test_理由の無い保留は掛けられない(db, root, world):
    """理由は公開の口に出るし、**外す判断にも要る**。"""
    with pytest.raises(Invalid):
        ops.set_hold(db, root, kind="naan", key="99999", until=_in(1), reason="  ")


def test_過去までの保留は掛けられない(db, root, world):
    with pytest.raises(Invalid):
        ops.set_hold(db, root, kind="naan", key="99999", until=_in(-1), reason="うっかり")


def test_上限より長い保留は掛けられない(db, root, world):
    """**長い保留は恒久と変わらない。** 延ばしたければ掛け直す（監査に残る）。"""
    with pytest.raises(Invalid):
        ops.set_hold(
            db, root, kind="naan", key="99999", until=_in(120),
            reason="長すぎる", max_days=90,
        )


def test_組織の管理者は名前空間を止められない(db, world, principal_of):
    """1 組織の判断で、**他組織の識別子まで巻き込めてはいけない。**"""
    org = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.set_hold(
            db, org, kind="shoulder", key=world["sh_a"].id, until=_in(1), reason="止めたい"
        )


def test_他組織のARKは止められない(db, world, minted, principal_of):
    """**負の場合。** 止めるのも「触る」操作なので、届かない相手には効かない。"""
    other = principal_of(manager=world["b"])
    with pytest.raises(Forbidden):
        ops.set_hold(db, other, kind="ark", key=minted.ark, until=_in(1), reason="止めたい")


def test_保留はARKの履歴に残る(db, root, minted):
    """監査は NAAN 単位以上しか残さない。**止めたのは組織かもしれない。**"""
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="行き先が怪しい")
    db.commit()
    actions = list(db.scalars(select(ArkChange.action).where(ArkChange.ark == minted.ark)))
    assert "hold" in actions


def test_保留中のARKはリゾルバが転送しない(api, db, root, minted):
    minted.url = "https://example.ac.jp/thing"
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="移行中")
    db.commit()
    r = api.get(f"/ark:/{minted.ark}")
    assert r.status_code == 200
    assert "移行中" in r.text
    assert api.get(f"/ark:/{minted.ark}?json").json()["hold"]["reason"] == "移行中"


def test_保留を外すと転送が戻る(api, db, root, minted):
    minted.url = "https://example.ac.jp/thing"
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="移行中")
    db.commit()
    ops.release_hold(db, root, kind="ark", key=minted.ark)
    db.commit()
    assert api.get(f"/ark:/{minted.ark}").status_code == 302


def test_APIから止められる(as_principal, principal_of, db, world, minted):
    p = principal_of(
        authority=Authority.NAAN, manager=world["a"],
        scopes={"ark:mint", "ark:update", "ark:read", "ark:hold"},
    )
    client = as_principal(p)
    r = client.put(
        "/api/hold",
        json={"ark": f"ark:/{minted.ark}", "until": _in(2).isoformat(), "reason": "移行中"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["hold_reason"] == "移行中"


def test_hold_scopeが無ければ止められない(as_principal, principal_of, world, minted):
    """**面白いのは通らなかったほうである。** 付け替えの権限で止められては困る。"""
    p = principal_of(manager=world["a"], scopes={"ark:update"})
    r = as_principal(p).put(
        "/api/hold",
        json={"ark": f"ark:/{minted.ark}", "until": _in(2).isoformat(), "reason": "移行中"},
    )
    assert r.status_code == 403


def test_保留の一覧は到達範囲で絞られる(db, root, world, principal_of):
    ops.set_hold(db, root, kind="naan", key="88888", until=_in(1), reason="別 NAAN")
    db.commit()
    org = principal_of(manager=world["a"])
    assert [h["target"] for h in ops.held(db, root)] == ["88888"]
    assert ops.held(db, org) == []


def test_shoulderの委譲はCLIと同じ操作で設定できる(db, root, world):
    """**画面にしかない操作を作らない。** 委譲の設定は自動化したいところ。"""
    sh = ops.set_shoulder_redirect(
        db, root, shoulder_id=world["sh_a"].id,
        redirect="303 https://sub.example.ac.jp/ark:/$id",
    )
    db.commit()
    assert sh.redirect.startswith("303 ")


def test_保留した名前空間は_well_known_に出る(api, db, root, world):
    """分散構成では、**上位が止めたことを下位が機械的に確かめられる**必要がある。"""
    ops.set_hold(
        db, root, kind="shoulder", key=world["sh_a"].id, until=_in(1),
        reason="委譲先が落ちている",
    )
    db.commit()
    held = api.get("/.well-known/ark").json()["held"]
    assert held and held[0]["reason"] == "委譲先が落ちている"


def test_モデルの3つがすべて保留を持つ():
    """**層をまたいで同じ形。** 片方だけ持つと、止め方が対象によって変わる。"""
    for model in (Naan, Shoulder, Ark):
        assert {"hold_until", "hold_reason", "hold_by"} <= set(model.__table__.columns.keys())
