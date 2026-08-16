"""オンボーディングのテスト（P5）。"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from jc2ark.ark.models import Ark, Client, Naan
from jc2ark.ark.onboarding import issue_break_glass, onboard
from jc2ark.arkspec.shoulder import validate_shoulder

pytestmark = pytest.mark.django_db


@pytest.fixture
def naan():
    return Naan.objects.create(naan="99999", name="JC2")


def test_onboarding_is_one_transaction(naan):
    r = onboard(naan=naan, name="基礎生物学研究所", label="ingest")
    validate_shoulder(r.shoulder.shoulder)
    assert r.manager.default_shoulder_id == r.shoulder.pk, "default_shoulder が必ず設定される"
    assert r.client.manager_id == r.manager.pk, "資格情報は shoulder ではなく Manager に紐づく"
    assert r.client_secret and len(r.client_secret) > 30
    # 発行済み資格情報で実際に採番できる
    ark, _ = Ark.objects.mint(shoulder=r.manager.default_shoulder, created_by=r.client.client_id)
    assert ark.shoulder.manager_id == r.manager.pk


def test_client_id_does_not_reuse_the_shoulder(naan):
    """shoulder は公開名前空間に現れるので、資格情報の識別子と同じにしない。"""
    r = onboard(naan=naan, name="機関", label="ingest")
    assert r.shoulder.shoulder.strip("/") not in r.client.client_id


def test_secret_is_hashed_and_not_recoverable(naan):
    r = onboard(naan=naan, name="機関", label="ingest")
    stored = Client.objects.get(pk=r.client.pk).client_secret
    assert stored != r.client_secret, "平文で保存しない"


def test_shoulders_do_not_leak_join_order(naan):
    got = [onboard(naan=naan, name=f"機関{i}", label="l").shoulder.shoulder for i in range(30)]
    assert len(set(got)) == 30
    assert got != sorted(got), "連番なら加入順が漏れる"


def test_break_glass_requires_a_reason(naan):
    with pytest.raises(ValueError):
        issue_break_glass(naan=naan, label="  ")


def test_break_glass_expires(naan):
    c, _ = issue_break_glass(naan=naan, label="incident-2026-08", hours=72)
    assert c.authority == "naan"
    assert c.manager_id is None
    assert c.expires_at is not None


def test_onboard_command(naan, capsys):
    call_command("onboard", "99999", "分子科学研究所", "--label", "ims-ingest")
    out = capsys.readouterr().out
    assert "オンボーディング完了" in out
    assert "再表示できない" in out


def test_breakglass_list_command(naan, capsys):
    issue_break_glass(naan=naan, label="incident-1")
    call_command("breakglass", "99999", "-", "--list")
    assert "有効な break-glass: 1 件" in capsys.readouterr().out
