"""統廃合と承継のテスト（`ark_succession.md`）。

**上位の原則は「識別子は壊さない」。** 組織が消えても解決は続ける。
"""

from __future__ import annotations

import pytest

from jc2ark.ark.models import Ark, Naan, Shoulder, ShoulderStatus
from jc2ark.ark.onboarding import onboard, succeed
from jc2ark.ark.repository import DjangoArkRepository
from jc2ark.ark.resolution import Outcome, resolve

pytestmark = pytest.mark.django_db


@pytest.fixture
def naan():
    return Naan.objects.create(naan="99999", name="JC2", na_policy="NP | NR, OP, CC | 2026 |")


def _mint(m, url):
    ark, _ = Ark.objects.mint(shoulder=m.default_shoulder, url=url)
    return ark


def _resolves_to(ark):
    naan_part, _, name = ark.ark.partition("/")
    return resolve(DjangoArkRepository(), naan_part, name)


# --------------------------------------------------------------------------
# 統合（A + B → C）
# --------------------------------------------------------------------------


def test_merger_keeps_every_identifier_resolving(naan):
    """**A ＋ B → C。既存 ARK は 1 本も変わらない。解決先も変わらない。**"""
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    b = onboard(naan=naan, name="B大学", label="ingest").manager
    c = onboard(naan=naan, name="C大学（統合後）", label="ingest").manager

    ark_a = _mint(a, "https://a.example/1")
    ark_b = _mint(b, "https://b.example/1")

    succeed(predecessor=a, successor=c)
    succeed(predecessor=b, successor=c)

    for ark, url in ((ark_a, "https://a.example/1"), (ark_b, "https://b.example/1")):
        r = _resolves_to(ark)
        assert r.outcome is Outcome.REDIRECT
        assert r.location == url, "解決先が変わっていない"

    # 名前空間は C に移った
    assert {s.manager_id for s in Shoulder.objects.filter(manager__isnull=False)} == {c.pk}


def test_successor_can_mint_into_the_inherited_namespace(naan):
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    c = onboard(naan=naan, name="C大学", label="ingest").manager
    a_shoulder = a.default_shoulder.shoulder

    succeed(predecessor=a, successor=c)
    c.refresh_from_db()
    sh = Shoulder.objects.get(shoulder=a_shoulder)
    ark, _ = Ark.objects.mint(shoulder=sh, url="https://c.example/1")
    assert ark.shoulder.manager_id == c.pk


def test_succession_revokes_the_old_credentials(naan):
    """承継後は**承継先の資格情報で採番する**。"""
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    c = onboard(naan=naan, name="C大学", label="ingest").manager
    assert a.clients.filter(active=True).count() == 1
    succeed(predecessor=a, successor=c)
    assert a.clients.filter(active=True).count() == 0
    assert c.clients.filter(active=True).count() == 1


def test_succession_is_recorded_in_the_lineage_and_the_audit(naan):
    from jc2ark.ark.models import AuditEvent

    a = onboard(naan=naan, name="A大学", label="ingest").manager
    c = onboard(naan=naan, name="C大学", label="ingest").manager
    succeed(predecessor=a, successor=c)
    a.refresh_from_db()
    assert a.succeeded_by_id == c.pk and not a.active
    assert list(c.predecessors.values_list("name", flat=True)) == ["A大学"]
    ev = AuditEvent.objects.get(action="succeed")
    assert "A大学 -> C大学" in ev.target


def test_retire_stops_new_minting_but_keeps_resolving(naan):
    """`--retire`: **新規採番は止めるが、既存 ARK は解決し続ける。**"""
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    c = onboard(naan=naan, name="C大学", label="ingest").manager
    ark = _mint(a, "https://a.example/1")

    succeed(predecessor=a, successor=c, retire_shoulders=True)
    sh = Shoulder.objects.get(pk=ark.shoulder_id)
    assert sh.status == ShoulderStatus.RETIRED
    assert not sh.can_mint_here
    assert _resolves_to(ark).location == "https://a.example/1"


# --------------------------------------------------------------------------
# S2  名前空間の再利用を防ぐ
# --------------------------------------------------------------------------


def test_shoulders_are_never_deleted(naan):
    """**削除は NR 違反の芽。** 乱数割当が同じ文字列を再び当てうる。"""
    m = onboard(naan=naan, name="A大学", label="ingest").manager
    with pytest.raises(RuntimeError, match="NR 違反"):
        m.default_shoulder.delete()


def test_a_retired_shoulder_is_not_handed_out_again(naan):
    """行が残っているので unique 制約で再割当されない。"""
    m = onboard(naan=naan, name="A大学", label="ingest").manager
    taken = m.default_shoulder.shoulder
    m.default_shoulder.status = ShoulderStatus.RETIRED
    m.default_shoulder.save()
    others = {onboard(naan=naan, name=f"機関{i}", label="l").shoulder.shoulder for i in range(40)}
    assert taken not in others


# --------------------------------------------------------------------------
# 閉学（承継先なし）
# --------------------------------------------------------------------------


def test_closure_without_a_successor_keeps_resolving(naan):
    """**承継先が無くても解決は続ける。** 引き受けるのが我々の役割。"""
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    ark = _mint(a, "https://a.example/1")
    a.active = False
    a.save()
    for sh in a.shoulders.all():
        sh.status = ShoulderStatus.RETIRED
        sh.save()
    a.clients.update(active=False)
    assert _resolves_to(ark).outcome is Outcome.REDIRECT


def test_lost_target_falls_back_to_the_description(naan):
    """§2.4: リンク先が消えたら **url を空にして記述を返す**（FAIR A2）。"""
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    ark = _mint(a, "https://a.example/1")
    ark.url = ""
    ark.title = "A大学 紀要 第1号"
    ark.commitment = "識別子とメタデータは維持するが、対象の所在は失われた"
    ark.save()
    r = _resolves_to(ark)
    assert r.outcome is Outcome.DESCRIBE
    assert r.status == 200


# --------------------------------------------------------------------------
# NAAN をまたぐ承継は自動化しない
# --------------------------------------------------------------------------


def test_cross_naan_succession_is_refused(naan):
    """§2.2: レジストリの `who` 変更（ARK Alliance への人手申請）が要るので、
    ここでは扱わない。"""
    other = Naan.objects.create(naan="12345", name="岡崎")
    a = onboard(naan=naan, name="A大学", label="ingest").manager
    b = onboard(naan=other, name="NIBB", label="ingest").manager
    with pytest.raises(ValueError, match="NAAN をまたぐ"):
        succeed(predecessor=a, successor=b)


def test_succeed_command(naan, capsys):
    from django.core.management import call_command

    onboard(naan=naan, name="A大学", label="ingest")
    onboard(naan=naan, name="C大学", label="ingest")
    call_command("succeed", "A大学", "C大学", "--retire")
    out = capsys.readouterr().out
    assert "承継を記録した" in out
    assert "既存 ARK は 1 本も変わらない" in out
