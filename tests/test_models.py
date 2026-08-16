"""モデルの単体テスト（P2）。

**出口条件は「オンボーディングを 1 通り通せること」**——`test_onboarding_walkthrough`
がそれを担う。
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from jc2ark.ark.models import Ark, Client, CommitmentLevel, Manager, Naan, Shoulder
from jc2ark.arkspec.betanumeric import verify_ark_check_digit
from jc2ark.arkspec.shoulder import generate_shoulder, split_shoulder

pytestmark = pytest.mark.django_db


@pytest.fixture
def naan():
    return Naan.objects.create(naan="99999", name="JC2 PoC", is_authoritative=True)


@pytest.fixture
def manager(naan):
    return Manager.objects.create(naan=naan, name="機関A")


@pytest.fixture
def shoulder(naan, manager):
    s = Shoulder.objects.create(shoulder="/kb1", naan=naan, manager=manager)
    manager.default_shoulder = s
    manager.save()
    return s


# --------------------------------------------------------------------------
# N2  NAAN は文字列
# --------------------------------------------------------------------------

def test_n2_leading_zero_naans_coexist():
    """`099999` と `99999` は**別の行**として共存できる。"""
    Naan.objects.create(naan="99999", name="A")
    Naan.objects.create(naan="099999", name="B")
    assert Naan.objects.count() == 2
    assert Naan.objects.get(pk="99999").name == "A"


# --------------------------------------------------------------------------
# D3  権威と転送先は排他
# --------------------------------------------------------------------------

def test_d3_authoritative_naan_cannot_have_a_redirect():
    with pytest.raises(IntegrityError):
        Naan.objects.create(naan="12345", name="X", is_authoritative=True, redirect="https://x/")


def test_d3_non_authoritative_naan_requires_a_redirect():
    with pytest.raises(IntegrityError):
        Naan.objects.create(naan="12345", name="X", is_authoritative=False, redirect="")


def test_d3_delegated_naan_is_allowed(naan):
    other = Naan.objects.create(
        naan="12345", name="他所", is_authoritative=False, redirect="https://other.example/"
    )
    assert not other.is_authoritative


# --------------------------------------------------------------------------
# B2  shoulder の規約
# --------------------------------------------------------------------------

def test_b2_shoulder_validator_rejects_multi_segment(naan):
    s = Shoulder(shoulder="/kb1/x2", naan=naan)
    with pytest.raises(ValidationError):
        s.full_clean()


def test_b2_shoulder_is_unique_per_naan(naan, manager):
    Shoulder.objects.create(shoulder="/kb1", naan=naan, manager=manager)
    with pytest.raises(IntegrityError):
        Shoulder.objects.create(shoulder="/kb1", naan=naan, manager=manager)


# --------------------------------------------------------------------------
# E1 / I6  既存 ARK を黙って上書きしない
# --------------------------------------------------------------------------

def test_e1_bare_save_cannot_create_an_ark(shoulder, naan):
    """**arklet で最重大だった欠陥を、モデル側で不可能にする。**"""
    a = Ark(ark="99999/kb1aaaaaaaa", naan=naan, shoulder=shoulder, assigned_name="kb1aaaaaaaa")
    with pytest.raises(RuntimeError, match="force_insert"):
        a.save()


def test_e1_existing_ark_is_not_overwritten(shoulder):
    ark, _ = Ark.objects.mint(shoulder=shoulder, url="https://a.example/")
    with pytest.raises(IntegrityError), transaction.atomic():
        Ark.objects.create(
            ark=ark.ark, naan=shoulder.naan, shoulder=shoulder, assigned_name=ark.assigned_name
        )


def test_updating_an_existing_ark_still_works(shoulder):
    ark, _ = Ark.objects.mint(shoulder=shoulder, url="https://a.example/")
    ark.url = "https://b.example/"
    ark.save()  # 既存行の更新は通る
    assert Ark.objects.get(pk=ark.ark).url == "https://b.example/"


# --------------------------------------------------------------------------
# 採番
# --------------------------------------------------------------------------

def test_mint_produces_a_verifiable_ark(shoulder):
    ark, collisions = Ark.objects.mint(shoulder=shoulder, url="https://x.example/", title="t")
    assert collisions == 0
    naan, _, name = ark.ark.partition("/")
    assert naan == "99999"
    assert name.startswith("kb1")
    assert split_shoulder(name)[0] == "kb1"
    assert verify_ark_check_digit(naan, name), "検査桁が合わない"
    assert str(ark) == f"ark:/{ark.ark}"


def test_mint_records_who(shoulder):
    ark, _ = Ark.objects.mint(shoulder=shoulder, created_by="client-abc")
    assert ark.created_by == "client-abc"
    assert ark.updated_by == "client-abc"
    assert ark.created_at is not None


def test_mint_is_unique_across_many(shoulder):
    made = {Ark.objects.mint(shoulder=shoulder)[0].ark for _ in range(50)}
    assert len(made) == 50


# --------------------------------------------------------------------------
# I5  条件つき unique 制約でローテーションを表現する
# --------------------------------------------------------------------------

def _client(manager, naan, label, active=True, **kw):
    return Client.objects.create(
        name=label, label=label, manager=manager, naan=naan, active=active,
        client_type=Client.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS, **kw
    )


def test_i5_two_active_clients_cannot_share_a_label(manager, naan):
    _client(manager, naan, "ingest")
    with pytest.raises(IntegrityError):
        _client(manager, naan, "ingest")


def test_i5_rotation_deactivate_then_reissue(manager, naan):
    """旧を無効化すれば同じ label で新規発行できる＝ローテーションが型で表現される。"""
    old = _client(manager, naan, "ingest")
    old.active = False
    old.save()
    new = _client(manager, naan, "ingest")
    assert new.pk != old.pk
    assert Client.objects.filter(label="ingest", active=True).count() == 1


def test_break_glass_client_carries_expiry(manager, naan):
    c = _client(
        manager, naan, "incident-2026-08", authority=Client.Authority.NAAN,
        expires_at=timezone.now() + timezone.timedelta(hours=72),
    )
    assert c.authority == "naan"
    assert c.expires_at is not None


# --------------------------------------------------------------------------
# P2 の出口条件: オンボーディングを 1 通り通せる
# --------------------------------------------------------------------------

def test_onboarding_walkthrough():
    """判定 → Manager → shoulder → default → Client → 採番 まで通す。

    `design_ark_multitenant_authz.md` §2.4。**全 NAAN で shoulder を使う**ので、
    個別 NAAN の機関でも手順は同じになる。
    """
    # 1. 判定: 個別 NAAN を渡す機関（岡崎3研究所を想定）
    n = Naan.objects.create(naan="12345", name="基礎生物学研究所", is_authoritative=True,
                            na_policy="NP | NR, OP, CC | 2026 |")
    # 2. Manager
    m = Manager.objects.create(naan=n, name="NIBB", commitment_level=CommitmentLevel.PERMANENT_STABLE)
    # 3. shoulder（3 文字・乱数・不透明）
    s = Shoulder.objects.create(shoulder=generate_shoulder(), naan=n, manager=m)
    s.full_clean()
    # 4. default_shoulder を必ず設定する
    m.default_shoulder = s
    m.save()
    # 5. Client
    c = _client(m, n, "nibb-ingest", allowed_scopes="ark:mint")
    # 6. 採番
    ark, _ = Ark.objects.mint(shoulder=m.default_shoulder, url="https://nibb.example/r/1",
                              created_by=c.client_id)
    naan_part, _, name = ark.ark.partition("/")
    assert naan_part == "12345"
    assert verify_ark_check_digit(naan_part, name)
    assert ark.shoulder.manager == m
    assert m.commitment_level == "permanent-stable"
