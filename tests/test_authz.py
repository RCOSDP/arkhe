"""認証・認可のテスト（P4）。

**arklet で実測した越境をすべて 403 に変える**のが目的。受け入れ条件 T1〜T13。

arklet の実測（2026-08-16、kind クラスタ）:
    mint   A のキー → B の shoulder      -> 200   ← 越境
    update B のキー → A の ARK           -> 200   ← 解決先を書き換えられた
    bulk_mint 混在                        -> 200
    bulk_query 認可なし                   -> 200
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from jc2ark.ark.models import Ark, Client, Manager, Naan, Shoulder

pytestmark = pytest.mark.django_db

SECRET = "s3cret-value-for-tests"


@pytest.fixture
def world():
    n = Naan.objects.create(naan="99999", name="JC2")
    other = Naan.objects.create(naan="12345", name="岡崎（別 NAAN）")
    a = Manager.objects.create(naan=n, name="機関A")
    b = Manager.objects.create(naan=n, name="機関B")
    sa = Shoulder.objects.create(shoulder="/kb1", naan=n, manager=a)
    sb = Shoulder.objects.create(shoulder="/kb2", naan=n, manager=b)
    a.default_shoulder, b.default_shoulder = sa, sb
    a.save()
    b.save()
    return {"naan": n, "other": other, "A": a, "B": b, "sa": sa, "sb": sb}


def make_client(manager, naan, label, scopes="ark:mint ark:update ark:read", **kw):
    c = Client(
        name=label,
        label=label,
        manager=manager,
        naan=naan,
        allowed_scopes=scopes,
        client_type=Client.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS,
        client_secret=SECRET,
        **kw,
    )
    c.save()
    return c


def token(http, client, scope=None):
    body = {
        "grant_type": "client_credentials",
        "client_id": client.client_id,
        "client_secret": SECRET,
    }
    if scope:
        body["scope"] = scope
    r = http.post("/o/token/", body)
    return r.status_code, json.loads(r.content or b"{}")


def auth(http, client, scope=None):
    st, body = token(http, client, scope)
    assert st == 200, body
    return {"HTTP_AUTHORIZATION": f"Bearer {body['access_token']}"}


def post(http, path, hdrs, payload):
    return http.post(path, data=json.dumps(payload), content_type="application/json", **hdrs)


def put(http, path, hdrs, payload):
    return http.put(path, data=json.dumps(payload), content_type="application/json", **hdrs)


# --------------------------------------------------------------------------
# T12  クライアント登録に無い scope をトークン要求で取れない
# --------------------------------------------------------------------------


def test_t12_unlisted_scope_cannot_be_requested(client, world):
    """**S1-2 で見つけた権限昇格。** `SCOPES_BACKEND_CLASS` が無いと 200 で取れる。"""
    c = make_client(world["A"], world["naan"], "mint-only", scopes="ark:mint")
    assert token(client, c, "ark:mint")[0] == 200
    st, body = token(client, c, "ark:update")
    assert st == 400
    assert body["error"] == "invalid_scope"
    assert token(client, c, "ark:mint ark:update")[0] == 400


# --------------------------------------------------------------------------
# T1 / R1  shoulder の越境
# --------------------------------------------------------------------------


def test_t1_minting_into_another_managers_shoulder_is_denied(client, world):
    """arklet では 200 だった。"""
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    assert post(client, "/mint", h, {"shoulder": "/kb1"}).status_code == 201  # 自分の
    assert post(client, "/mint", h, {"shoulder": "/kb2"}).status_code == 403  # 他機関の


def test_shoulder_is_optional_and_defaults_to_the_managers(client, world):
    """**振り分けの本体。** 呼び出し側は shoulder を送らなくてよい。"""
    ca = make_client(world["A"], world["naan"], "a")
    r = post(client, "/mint", auth(client, ca), {"url": "https://x.example/1"})
    assert r.status_code == 201
    assert r.json()["ark"].startswith("ark:/99999/kb1")


def test_mint_records_the_client(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    r = post(client, "/mint", auth(client, ca), {})
    ark = Ark.objects.get(pk=r.json()["ark"].removeprefix("ark:/"))
    assert ark.created_by == ca.client_id


# --------------------------------------------------------------------------
# T2 / M3  他機関の ARK の解決先を書き換えられない
# --------------------------------------------------------------------------


def test_t2_updating_another_managers_ark_is_denied(client, world):
    """**arklet では 200 で、resolver の 302 先が実際に変わった。**"""
    ca = make_client(world["A"], world["naan"], "a")
    cb = make_client(world["B"], world["naan"], "b")
    made = post(client, "/mint", auth(client, ca), {"url": "https://a.example/"}).json()["ark"]

    r = put(client, "/update", auth(client, cb), {"ark": made, "url": "https://hijacked.example/"})
    assert r.status_code in (403, 404)
    assert Ark.objects.get(pk=made.removeprefix("ark:/")).url == "https://a.example/"


def test_owner_can_still_update(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    made = post(client, "/mint", h, {"url": "https://a.example/"}).json()["ark"]
    assert put(client, "/update", h, {"ark": made, "url": "https://b.example/"}).status_code == 200
    assert Ark.objects.get(pk=made.removeprefix("ark:/")).url == "https://b.example/"


def test_update_requires_the_update_scope(client, world):
    ca = make_client(world["A"], world["naan"], "a", scopes="ark:mint")
    h = auth(client, ca)
    made = post(client, "/mint", h, {}).json()["ark"]
    assert put(client, "/update", h, {"ark": made, "url": "https://x.example/"}).status_code == 403


# --------------------------------------------------------------------------
# T3  bulk_mint の混在
# --------------------------------------------------------------------------


def test_t3_bulk_mint_cannot_mix_in_another_managers_shoulder(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    r = post(
        client,
        "/bulk_mint",
        auth(client, ca),
        {"data": [{"shoulder": "/kb1"}, {"shoulder": "/kb2"}, {"shoulder": "/kb1"}]},
    )
    assert r.status_code == 403
    assert Ark.objects.count() == 0, "1 件でも範囲外なら何も作らない"


def test_bulk_mint_succeeds_within_range(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    r = post(client, "/bulk_mint", auth(client, ca), {"data": [{}, {"shoulder": "/kb1"}]})
    assert r.status_code == 201
    assert len(r.json()["minted"]) == 2


# --------------------------------------------------------------------------
# T4 / M4  bulk_query の認可
# --------------------------------------------------------------------------


def test_t4_bulk_query_requires_authorization(client, world):
    """**arklet は `authorize()` を一切呼んでいなかった。**"""
    assert post(client, "/bulk_query", {}, {"data": ["99999/kb1x"]}).status_code == 401


def test_bulk_query_only_returns_what_the_client_may_see(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    cb = make_client(world["B"], world["naan"], "b")
    mine = post(client, "/mint", auth(client, ca), {}).json()["ark"]
    theirs = post(client, "/mint", auth(client, cb), {}).json()["ark"]
    r = post(client, "/bulk_query", auth(client, ca), {"data": [mine, theirs]})
    got = {row["ark"] for row in r.json()["data"]}
    assert got == {mine}


# --------------------------------------------------------------------------
# T5 / M5  bulk_update は部分適用しない
# --------------------------------------------------------------------------


def test_t5_bulk_update_is_all_or_nothing(client, world):
    """arklet は順序不定の queryset を入力と zip しており、**別の ARK に他レコードの
    値を書き込みうる**うえ、件数が違えば黙って切り詰めていた。"""
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    a1 = post(client, "/mint", h, {"url": "https://one.example/"}).json()["ark"]
    a2 = post(client, "/mint", h, {"url": "https://two.example/"}).json()["ark"]
    r = put(
        client,
        "/bulk_update",
        h,
        {
            "data": [
                {"ark": a1, "url": "https://new1.example/"},
                {"ark": "99999/kb1nosuchark", "url": "https://x.example/"},  # 存在しない
                {"ark": a2, "url": "https://new2.example/"},
            ]
        },
    )
    assert r.status_code == 404
    assert Ark.objects.get(pk=a1.removeprefix("ark:/")).url == "https://one.example/", (
        "部分適用されていない"
    )
    assert Ark.objects.get(pk=a2.removeprefix("ark:/")).url == "https://two.example/"


def test_bulk_update_maps_by_ark_not_by_position(client, world):
    """**順序に依存しない**ことを固定する（zip 不整合の再発防止）。"""
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    arks = [
        post(client, "/mint", h, {"url": f"https://n{i}.example/"}).json()["ark"] for i in range(5)
    ]
    r = put(
        client,
        "/bulk_update",
        h,
        {"data": [{"ark": a, "title": f"t{i}"} for i, a in enumerate(reversed(arks))]},
    )
    assert r.status_code == 200
    for i, a in enumerate(reversed(arks)):
        assert Ark.objects.get(pk=a.removeprefix("ark:/")).title == f"t{i}"


# --------------------------------------------------------------------------
# T9 / T10 / T13  break-glass と即時失効
# --------------------------------------------------------------------------


def test_t9_naan_authority_reaches_every_shoulder(client, world):
    c = make_client(
        None,
        world["naan"],
        "break-glass",
        authority=Client.Authority.NAAN,
        expires_at=timezone.now() + timezone.timedelta(hours=72),
    )
    h = auth(client, c)
    assert post(client, "/mint", h, {"shoulder": "/kb1"}).status_code == 201
    assert post(client, "/mint", h, {"shoulder": "/kb2"}).status_code == 201


def test_naan_authority_must_name_the_shoulder(client, world):
    """既定を持たないので、誤って他機関に打つ事故を防ぐ。"""
    c = make_client(None, world["naan"], "bg", authority=Client.Authority.NAAN)
    assert post(client, "/mint", auth(client, c), {}).status_code == 400


def test_r2_naan_authority_operations_are_audited(client, world):
    from jc2ark.ark.models import AuditEvent

    c = make_client(None, world["naan"], "bg", authority=Client.Authority.NAAN)
    post(client, "/mint", auth(client, c), {"shoulder": "/kb1"})
    ev = AuditEvent.objects.get()
    assert (ev.action, ev.authority, ev.client_id) == ("mint", "naan", c.client_id)


def test_manager_scoped_operations_are_not_audited(client, world):
    from jc2ark.ark.models import AuditEvent

    ca = make_client(world["A"], world["naan"], "a")
    post(client, "/mint", auth(client, ca), {})
    assert AuditEvent.objects.count() == 0


def test_t10_expired_client_is_rejected_even_with_a_live_token(client, world):
    """**DOT 標準ではトークンは TTL まで有効。** permission で即時に弾く。"""
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    assert post(client, "/mint", h, {}).status_code == 201
    ca.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    ca.save()
    assert post(client, "/mint", h, {}).status_code == 403


def test_deactivating_a_client_takes_effect_immediately(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    assert post(client, "/mint", h, {}).status_code == 201
    ca.active = False
    ca.save()
    assert post(client, "/mint", h, {}).status_code == 403


def test_t13_deactivating_the_manager_takes_effect_immediately(client, world):
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    assert post(client, "/mint", h, {}).status_code == 201
    world["A"].active = False
    world["A"].save()
    assert post(client, "/mint", h, {}).status_code == 403


# --------------------------------------------------------------------------
# NAAN 境界（arklet でも正しく効いていた。回帰させない）
# --------------------------------------------------------------------------


def test_naan_boundary_still_holds(client, world):
    other_m = Manager.objects.create(naan=world["other"], name="NIBB")
    other_s = Shoulder.objects.create(shoulder="/zx3", naan=world["other"], manager=other_m)
    other_m.default_shoulder = other_s
    other_m.save()
    ca = make_client(world["A"], world["naan"], "a")
    assert post(client, "/mint", auth(client, ca), {"shoulder": "/zx3"}).status_code == 403


# --------------------------------------------------------------------------
# 未認証・OpenAPI
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,method", [("/mint", "post"), ("/bulk_mint", "post"), ("/bulk_query", "post")]
)
def test_unauthenticated_requests_are_rejected(client, world, path, method):
    assert (
        getattr(client, method)(path, data="{}", content_type="application/json").status_code == 401
    )


def test_openapi_declares_the_scopes(client, world):
    r = client.get("/openapi.json?format=json")
    schema = r.json()
    assert schema["paths"]["/mint"]["post"]["security"][0]["oauth2"] == ["ark:mint"]
    assert schema["paths"]["/update"]["put"]["security"][0]["oauth2"] == ["ark:update"]


# --------------------------------------------------------------------------
# R3  割当量
# --------------------------------------------------------------------------


def test_r3_quota_stops_a_runaway_manager(client, world):
    world["A"].quota_per_day = 2
    world["A"].save()
    ca = make_client(world["A"], world["naan"], "a")
    h = auth(client, ca)
    assert post(client, "/mint", h, {}).status_code == 201
    assert post(client, "/mint", h, {}).status_code == 201
    assert post(client, "/mint", h, {}).status_code == 429


def test_r3_bulk_mint_checks_the_whole_batch(client, world):
    world["A"].quota_per_day = 3
    world["A"].save()
    ca = make_client(world["A"], world["naan"], "a")
    r = post(client, "/bulk_mint", auth(client, ca), {"data": [{}, {}, {}, {}]})
    assert r.status_code == 429
    assert Ark.objects.count() == 0


def test_r3_break_glass_is_not_throttled(client, world):
    """障害対応で止まっては困るので、break-glass は quota の対象外。"""
    world["A"].quota_per_day = 0
    world["A"].save()
    c = make_client(None, world["naan"], "bg", authority=Client.Authority.NAAN)
    assert post(client, "/mint", auth(client, c), {"shoulder": "/kb1"}).status_code == 201


# --------------------------------------------------------------------------
# 同一 shoulder に複数のクライアント（鍵を共有しない）
# --------------------------------------------------------------------------


def test_multiple_clients_share_a_shoulder_but_not_keys(client, world):
    """**同一 naan.shoulder に対して採番する主体は複数いるのが普通。**

    InvenioRDM の web-api / worker、一括投入バッチ、外部システム。
    それぞれに別の資格情報を出し、**鍵は共有しない**。
    """
    from jc2ark.ark.onboarding import issue_client

    api, s_api = issue_client(manager=world["A"], label="web-api", shoulder=world["sa"])
    wrk, s_wrk = issue_client(manager=world["A"], label="worker", shoulder=world["sa"])
    assert api.client_id != wrk.client_id
    assert s_api != s_wrk

    for c, sec in ((api, s_api), (wrk, s_wrk)):
        r = client.post(
            "/o/token/",
            {"grant_type": "client_credentials", "client_id": c.client_id, "client_secret": sec},
        )
        tok = json.loads(r.content)["access_token"]
        made = post(client, "/mint", {"HTTP_AUTHORIZATION": f"Bearer {tok}"}, {})
        assert made.status_code == 201
        # **同じ shoulder に入る**
        assert made.json()["ark"].startswith("ark:/99999/kb1")
        # **誰が採番したかは分かれる**
        assert (
            Ark.objects.get(pk=made.json()["ark"].removeprefix("ark:/")).created_by == c.client_id
        )


def test_revoking_one_client_does_not_affect_the_others(client, world):
    """鍵を分けておく最大の利点。**1 つ漏れても、それだけ止められる。**"""
    from jc2ark.ark.onboarding import issue_client

    api, s_api = issue_client(manager=world["A"], label="web-api", shoulder=world["sa"])
    wrk, s_wrk = issue_client(manager=world["A"], label="worker", shoulder=world["sa"])

    def mint_with(c, sec):
        r = client.post(
            "/o/token/",
            {"grant_type": "client_credentials", "client_id": c.client_id, "client_secret": sec},
        )
        tok = json.loads(r.content).get("access_token")
        if tok is None:
            return 401
        return post(client, "/mint", {"HTTP_AUTHORIZATION": f"Bearer {tok}"}, {}).status_code

    assert mint_with(api, s_api) == 201
    api.active = False
    api.save()
    assert mint_with(api, s_api) in (401, 403), "止めた側は使えない"
    assert mint_with(wrk, s_wrk) == 201, "もう一方は動き続ける"


def test_clients_can_have_different_scopes_on_the_same_shoulder(client, world):
    """用途ごとに絞れる。**投入専用には mint だけ渡す。**"""
    from jc2ark.ark.onboarding import issue_client

    ingest, s1 = issue_client(
        manager=world["A"], label="ingest", scopes="ark:mint", shoulder=world["sa"]
    )
    curate, s2 = issue_client(
        manager=world["A"], label="curate", scopes="ark:mint ark:update", shoulder=world["sa"]
    )

    def hdr(c, sec):
        r = client.post(
            "/o/token/",
            {"grant_type": "client_credentials", "client_id": c.client_id, "client_secret": sec},
        )
        return {"HTTP_AUTHORIZATION": f"Bearer {json.loads(r.content)['access_token']}"}

    h1, h2 = hdr(ingest, s1), hdr(curate, s2)
    made = post(client, "/mint", h1, {"url": "https://a.example/"}).json()["ark"]
    assert put(client, "/update", h1, {"ark": made, "url": "https://b.example/"}).status_code == 403
    assert put(client, "/update", h2, {"ark": made, "url": "https://b.example/"}).status_code == 200


def test_a_pinned_client_cannot_use_another_shoulder_of_the_same_manager(client, world):
    """shoulder に固定したクライアントは、同じ機関の別 shoulder にも行けない。"""
    from jc2ark.ark.models import Shoulder
    from jc2ark.ark.onboarding import issue_client

    other = Shoulder.objects.create(shoulder="/kb9", naan=world["naan"], manager=world["A"])
    c, sec = issue_client(manager=world["A"], label="pinned", shoulder=world["sa"])
    r = client.post(
        "/o/token/",
        {"grant_type": "client_credentials", "client_id": c.client_id, "client_secret": sec},
    )
    h = {"HTTP_AUTHORIZATION": f"Bearer {json.loads(r.content)['access_token']}"}
    assert post(client, "/mint", h, {"shoulder": other.shoulder}).status_code == 403
    assert post(client, "/mint", h, {"shoulder": "/kb1"}).status_code == 201


def test_two_active_clients_cannot_share_a_label(world):
    """**用途名で区別できるようにする。** どれを失効させるか迷わないため。"""
    from django.db import IntegrityError

    from jc2ark.ark.onboarding import issue_client

    issue_client(manager=world["A"], label="web-api")
    with pytest.raises(IntegrityError):
        issue_client(manager=world["A"], label="web-api")


def test_issue_client_command(world, capsys):
    from django.core.management import call_command

    call_command("issue_client", "機関A", "batch-importer", "--shoulder", "/kb1")
    out = capsys.readouterr().out
    assert "追加クライアントを発行した" in out
    assert "共有しないこと" in out


# --------------------------------------------------------------------------
# shoulder の管理状態（リザーブ枠・採番の委譲・引退）
# --------------------------------------------------------------------------


def _hdr(http, c, sec):
    r = http.post(
        "/o/token/",
        {"grant_type": "client_credentials", "client_id": c.client_id, "client_secret": sec},
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {json.loads(r.content)['access_token']}"}


def test_reserved_shoulder_cannot_be_minted_into(client, world):
    """**リザーブ枠**は名前空間を押さえるだけ。採番はできない。"""
    from jc2ark.ark.models import ShoulderStatus
    from jc2ark.ark.onboarding import issue_client

    world["sa"].status = ShoulderStatus.RESERVED
    world["sa"].note = "第2段階の機関テナント用に確保"
    world["sa"].save()
    c, sec = issue_client(manager=world["A"], label="x", shoulder=world["sa"])
    r = post(client, "/mint", _hdr(client, c, sec), {})
    assert r.status_code == 403
    assert "reserved" in json.dumps(r.json())


def test_delegated_shoulder_answers_307_with_the_minter(client, world):
    """**採番が外部 minter にある shoulder は、案内する。プロキシしない。**

    代理で呼ぶと、応答が失われたときに「向こうでは採番されたがこちらは知らない
    ARK」が生まれる。NR を宣言する識別子では取り返しがつかない。
    """
    from jc2ark.ark.models import ShoulderStatus
    from jc2ark.ark.onboarding import issue_client

    world["sa"].status = ShoulderStatus.DELEGATED
    world["sa"].minter = "https://nibb.example/ark/mint"
    world["sa"].save()
    c, sec = issue_client(manager=world["A"], label="x", shoulder=world["sa"])
    r = post(client, "/mint", _hdr(client, c, sec), {})
    assert r.status_code == 307
    assert r["Location"] == "https://nibb.example/ark/mint"
    assert Ark.objects.count() == 0, "こちらでは採番していない"


def test_delegated_shoulder_requires_a_minter():
    """行き先の無い委譲は作らせない（案内できないため）。"""
    from django.db import IntegrityError

    from jc2ark.ark.models import Naan, Shoulder, ShoulderStatus

    n = Naan.objects.create(naan="99999", name="x")
    with pytest.raises(IntegrityError):
        Shoulder.objects.create(shoulder="/kb1", naan=n, status=ShoulderStatus.DELEGATED)


def test_retired_shoulder_stops_minting_but_keeps_resolving(client, world):
    """**引退しても既存 ARK は解決し続ける**（NR を守る）。"""
    from jc2ark.ark.models import ShoulderStatus
    from jc2ark.ark.onboarding import issue_client

    c, sec = issue_client(manager=world["A"], label="x", shoulder=world["sa"])
    h = _hdr(client, c, sec)
    made = post(client, "/mint", h, {"url": "https://a.example/"}).json()["ark"]

    world["sa"].status = ShoulderStatus.RETIRED
    world["sa"].save()
    assert post(client, "/mint", h, {}).status_code == 403

    from jc2ark.ark.repository import DjangoArkRepository
    from jc2ark.ark.resolution import Outcome, resolve

    key = made.removeprefix("ark:/")
    naan, _, name = key.partition("/")
    assert resolve(DjangoArkRepository(), naan, name).outcome is Outcome.REDIRECT


def test_bulk_mint_stops_if_any_shoulder_is_not_mintable(client, world):
    from jc2ark.ark.models import ShoulderStatus
    from jc2ark.ark.onboarding import issue_client

    world["sb"].status = ShoulderStatus.RESERVED
    world["sb"].save()
    c, sec = issue_client(manager=world["A"], label="x")  # 機関 A の全 shoulder
    # 機関 A は /kb1 のみなので、/kb2 は範囲外 → 403（reserved の前に弾かれる）
    r = post(client, "/bulk_mint", _hdr(client, c, sec), {"data": [{}, {"shoulder": "/kb2"}]})
    assert r.status_code == 403
    assert Ark.objects.count() == 0


def test_reserve_shoulder_helper(world):
    """リザーブ枠は**乱数割当で当たらない**（unique 制約が効く）。"""
    from jc2ark.ark.models import ShoulderStatus
    from jc2ark.ark.onboarding import reserve_shoulder

    r = reserve_shoulder(naan=world["naan"], note="第2段階用")
    assert r.status == ShoulderStatus.RESERVED
    assert r.manager_id is None

    d = reserve_shoulder(
        naan=world["naan"], note="岡崎の自前 minter 用", minter="https://nibb.example/mint"
    )
    assert d.status == ShoulderStatus.DELEGATED


def test_well_known_advertises_delegated_minters(client, world, settings):
    """**採番が外に出ている名前空間は公開して案内する。**"""
    from jc2ark.ark.models import ShoulderStatus

    world["sa"].status = ShoulderStatus.DELEGATED
    world["sa"].minter = "https://nibb.example/ark/mint"
    world["sa"].save()
    from tests.test_resolution import _use_role

    _use_role(settings, "resolver")
    try:
        body = client.get("/.well-known/ark").json()
        assert body["minters"]["99999/kb1"] == "https://nibb.example/ark/mint"
    finally:
        _use_role(settings, "minter")


# --------------------------------------------------------------------------
# 発行 / 更新 / 墓碑化 の権限分離
# --------------------------------------------------------------------------


def test_mint_update_and_tombstone_are_separate_powers(client, world):
    """**「発行はさせないが更新はさせる」**は実際に起きる（離脱した機関の転送先維持）。

    墓碑化を update と分けるのは、**それが「対象が失われた」という宣言**であり、
    転送先の付け替えとは意味も影響も違うから。取り消しにくく、公開されると信頼に
    関わるので、投入バッチのような日常の書き手には渡さない。
    """
    from jc2ark.ark.onboarding import issue_client

    ingest, s1 = issue_client(manager=world["A"], label="ingest", scopes="ark:mint")
    keeper, s2 = issue_client(manager=world["A"], label="keeper", scopes="ark:update")
    curator, s3 = issue_client(
        manager=world["A"], label="curator", scopes="ark:update ark:tombstone"
    )
    h1, h2, h3 = (_hdr(client, c, s) for c, s in ((ingest, s1), (keeper, s2), (curator, s3)))

    made = post(client, "/mint", h1, {"url": "https://a.example/"}).json()["ark"]
    assert post(client, "/mint", h2, {}).status_code == 403, "更新係は発行できない"

    assert put(client, "/update", h2, {"ark": made, "url": "https://b.example/"}).status_code == 200
    assert put(client, "/tombstone", h2, {"ark": made}).status_code == 403, "更新係は墓碑化できない"
    assert put(client, "/tombstone", h3, {"ark": made}).status_code == 200


def test_tombstone_clears_the_target_but_keeps_the_identifier(client, world):
    """**ARK は削除できない。** 消せるのは対象への到達性だけ。"""
    from jc2ark.ark.onboarding import issue_client

    c, sec = issue_client(manager=world["A"], label="curator", scopes="ark:mint ark:tombstone")
    h = _hdr(client, c, sec)
    made = post(client, "/mint", h, {"url": "https://a.example/", "title": "紀要 第1号"}).json()[
        "ark"
    ]
    key = made.removeprefix("ark:/")

    put(client, "/tombstone", h, {"ark": made, "commitment": "対象は失われた。識別子は維持する"})
    a = Ark.objects.get(pk=key)
    assert a.url == "", "転送先は消える"
    assert a.title == "紀要 第1号", "**メタデータは残る**（FAIR A2）"
    assert a.commitment.startswith("対象は失われた")

    # リゾルバは記述そのものを返す
    from jc2ark.ark.repository import DjangoArkRepository
    from jc2ark.ark.resolution import Outcome, resolve

    naan_part, _, name = key.partition("/")
    assert resolve(DjangoArkRepository(), naan_part, name).outcome is Outcome.DESCRIBE


def test_tombstone_can_point_at_a_tombstone_page(client, world):
    from jc2ark.ark.onboarding import issue_client

    c, sec = issue_client(manager=world["A"], label="x", scopes="ark:mint ark:tombstone")
    h = _hdr(client, c, sec)
    made = post(client, "/mint", h, {"url": "https://a.example/"}).json()["ark"]
    put(client, "/tombstone", h, {"ark": made, "url": "https://a.example/tombstone/1"})
    assert Ark.objects.get(pk=made.removeprefix("ark:/")).url.endswith("/tombstone/1")


def test_tombstone_respects_the_manager_boundary(client, world):
    from jc2ark.ark.onboarding import issue_client

    a, sa = issue_client(manager=world["A"], label="x", scopes="ark:mint")
    b, sb = issue_client(manager=world["B"], label="y", scopes="ark:tombstone")
    made = post(client, "/mint", _hdr(client, a, sa), {"url": "https://a.example/"}).json()["ark"]
    r = put(client, "/tombstone", _hdr(client, b, sb), {"ark": made})
    assert r.status_code in (403, 404)
    assert Ark.objects.get(pk=made.removeprefix("ark:/")).url == "https://a.example/"


# ==========================================================================
# B4  修飾子付き ARK の登録
# ==========================================================================


def test_b4_a_qualifier_can_be_registered_on_an_existing_ark(client, world):
    """**suffix passthrough の既定を 1 点だけ上書きする。**"""
    c = make_client(world["A"], world["naan"], "b4")
    h = auth(client, c)
    base = post(client, "/mint", h, {"url": "https://repo.example/scan.nxs"}).json()["ark"]
    r = post(
        client,
        "/register",
        h,
        {
            "ark": base,
            "qualifier": "/entry/detector",
            "url": "https://cold.example/det",
        },
    )
    assert r.status_code == 201, r.content
    assert r.json()["ark"] == f"{base}/entry/detector"


def test_b4_the_registered_qualifier_wins_over_passthrough(client, world):
    """登録した 1 点だけが別の所在に向き、**兄弟は祖先から継ぐ**こと。"""
    from jc2ark.ark.repository import DjangoArkRepository
    from jc2ark.ark.resolution import resolve

    c = make_client(world["A"], world["naan"], "b4b")
    h = auth(client, c)
    base = post(client, "/mint", h, {"url": "https://repo.example/scan.nxs"}).json()["ark"]
    post(
        client,
        "/register",
        h,
        {
            "ark": base,
            "qualifier": "/entry/detector",
            "url": "https://cold.example/det",
        },
    )
    name = base.removeprefix("ark:/99999/")
    repo = DjangoArkRepository()
    assert resolve(repo, "99999", f"{name}/entry/detector").location == "https://cold.example/det"
    assert resolve(repo, "99999", f"{name}/entry/other").location == (
        "https://repo.example/scan.nxs/entry/other"
    )


def test_b4_variant_qualifier_works_too(client, world):
    c = make_client(world["A"], world["naan"], "b4c")
    h = auth(client, c)
    base = post(client, "/mint", h, {"url": "https://repo.example/run.mzML"}).json()["ark"]
    r = post(
        client,
        "/register",
        h,
        {
            "ark": base,
            "qualifier": ".mzMLb",
            "url": "https://repo.example/run.mzMLb",
        },
    )
    assert r.status_code == 201
    assert r.json()["ark"] == f"{base}.mzMLb"


def test_b4_a_qualifier_must_start_with_a_structural_character(client, world):
    """`entry` のような裸の文字列は**別の名前**であって修飾子ではない。"""
    c = make_client(world["A"], world["naan"], "b4d")
    h = auth(client, c)
    base = post(client, "/mint", h, {"url": "https://x.example/"}).json()["ark"]
    assert post(client, "/register", h, {"ark": base, "qualifier": "entry"}).status_code == 400


def test_b4_registering_twice_does_not_overwrite(client, world):
    """E1: **既に在るものを黙って上書きしない。** 更新は `update` の仕事。"""
    c = make_client(world["A"], world["naan"], "b4e")
    h = auth(client, c)
    base = post(client, "/mint", h, {"url": "https://x.example/"}).json()["ark"]
    body = {"ark": base, "qualifier": "/a", "url": "https://first.example/"}
    assert post(client, "/register", h, body).status_code == 201
    again = post(client, "/register", h, {**body, "url": "https://second.example/"})
    assert again.status_code == 400
    assert "既に登録済み" in again.content.decode()


def test_b4_update_scope_alone_cannot_create_a_qualifier(client, world):
    """**新しく解決可能な識別子が増える**ので `ark:mint` が要る。

    発行と更新を分けた趣旨がここで効く——投入バッチに更新だけ渡す運用で、
    識別子を増やされては困る。
    """
    c = make_client(world["A"], world["naan"], "b4f", scopes="ark:update")
    mint_client = make_client(world["A"], world["naan"], "b4f-mint")
    base = post(client, "/mint", auth(client, mint_client), {"url": "https://x.example/"})
    r = post(client, "/register", auth(client, c), {"ark": base.json()["ark"], "qualifier": "/a"})
    assert r.status_code == 403


def test_b4_cannot_qualify_another_managers_ark(client, world):
    c_a = make_client(world["A"], world["naan"], "b4g")
    c_b = make_client(world["B"], world["naan"], "b4h")
    base = post(client, "/mint", auth(client, c_a), {"url": "https://x.example/"}).json()["ark"]
    r = post(client, "/register", auth(client, c_b), {"ark": base, "qualifier": "/a"})
    assert r.status_code in (403, 404)


# ==========================================================================
# F4  冪等な採番（outbox の受け側）
# ==========================================================================


def test_f4_resending_the_same_request_id_does_not_mint_twice(client, world):
    """**採番は再試行できない**——`NR` を宣言する識別子は取り消せないので、応答が
    失われたときに再送すると誰も指していない ARK が増える。控えがあれば安全になる。
    """
    c = make_client(world["A"], world["naan"], "f4")
    h = auth(client, c)
    body = {"url": "https://repo.example/1", "request_id": "batch-7/row-42"}
    first = post(client, "/mint", h, body)
    second = post(client, "/mint", h, body)
    assert first.status_code == 201
    assert second.status_code == 200  # 再送は「作った」ではない
    assert first.json()["ark"] == second.json()["ark"]
    assert Ark.objects.count() == 1


def test_f4_request_ids_are_scoped_to_the_client(client, world):
    """**他機関の `request_id` と衝突しない。** 鍵の推測で他所の ARK も引けない。"""
    ca = make_client(world["A"], world["naan"], "f4a")
    cb = make_client(world["B"], world["naan"], "f4b")
    body = {"url": "https://repo.example/1", "request_id": "row-1"}
    a = post(client, "/mint", auth(client, ca), body)
    b = post(client, "/mint", auth(client, cb), body)
    assert a.status_code == b.status_code == 201
    assert a.json()["ark"] != b.json()["ark"]


def test_f4_without_a_request_id_nothing_changes(client, world):
    """鍵を付けない呼び出しは従来どおり。**毎回新しい番号。**"""
    c = make_client(world["A"], world["naan"], "f4c")
    h = auth(client, c)
    a = post(client, "/mint", h, {"url": "https://repo.example/1"})
    b = post(client, "/mint", h, {"url": "https://repo.example/1"})
    assert a.json()["ark"] != b.json()["ark"]


def test_f4_a_partially_delivered_batch_can_be_resent_whole(client, world):
    """**切れた塊をそのまま再送できる。** 万オーダーの投入で効く。"""
    c = make_client(world["A"], world["naan"], "f4d")
    h = auth(client, c)
    rows = [{"url": f"https://repo.example/{i}", "request_id": f"row-{i}"} for i in range(5)]
    first = post(client, "/bulk_mint", h, {"data": rows[:3]})
    assert first.status_code == 201 and first.json()["created"] == 3
    whole = post(client, "/bulk_mint", h, {"data": rows})
    assert whole.status_code == 201
    assert (whole.json()["created"], whole.json()["replayed"]) == (2, 3)
    assert Ark.objects.count() == 5
    # **並びが入力どおりであること**——再送ぶんと新規ぶんが混ざるので
    assert [a["url"] for a in whole.json()["minted"]] == [r["url"] for r in rows]
    # 先に採番した 3 本は同じ ARK のまま
    assert [a["ark"] for a in whole.json()["minted"][:3]] == [
        a["ark"] for a in first.json()["minted"]
    ]


def test_f4_resending_a_fully_delivered_batch_creates_nothing(client, world):
    c = make_client(world["A"], world["naan"], "f4e")
    h = auth(client, c)
    rows = [{"url": f"https://repo.example/{i}", "request_id": f"r{i}"} for i in range(3)]
    post(client, "/bulk_mint", h, {"data": rows})
    again = post(client, "/bulk_mint", h, {"data": rows})
    assert again.status_code == 200  # 何も作っていない
    assert again.json()["created"] == 0
    assert Ark.objects.count() == 3


def test_f4_the_receipt_is_written_in_the_same_transaction(client, world):
    """控えを別トランザクションにすると、**書く前に落ちたときに二重採番**になる。"""
    from unittest.mock import patch

    from jc2ark.ark.models import MintReceipt

    c = make_client(world["A"], world["naan"], "f4f")
    h = auth(client, c)
    with patch.object(MintReceipt.objects, "create", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            post(client, "/mint", h, {"url": "https://x.example/", "request_id": "k"})
    assert Ark.objects.count() == 0  # 採番も巻き戻っていること
