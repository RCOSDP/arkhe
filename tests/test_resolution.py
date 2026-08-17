"""解決フローのテスト（P3）。

前半は **Django を使わない決定ロジックの単体テスト**（偽リポジトリを差す）。
後半は HTTP レベル。arklet の `views_tests.py` 41 件が担っていた層をここで持つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jc2ark.ark.resolution import (
    ArkRepository,
    Inflection,
    Outcome,
    base_name,
    expand_redirect,
    resolve,
)

# ==========================================================================
# 偽リポジトリによる決定ロジックの単体テスト（Django 不要）
# ==========================================================================


@dataclass
class FakeArk:
    url: str = ""
    commitment: str = ""


@dataclass
class FakeNaan:
    is_authoritative: bool = True
    redirect: str = ""
    na_policy: str = ""


@dataclass
class FakeShoulder:
    redirect: str = ""


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


#: 検査桁が合う名前。**前回 arklet が実測で採番した ARK と同一**
#: （`ark:/99999/kb1d191j10ds`）なので、移植の整合を兼ねた固定値になっている。
GOOD = "kb1d191j10ds"


def _repo(**kw):
    base = FakeRepo(naans={"99999": FakeNaan(is_authoritative=True)})
    for k, v in kw.items():
        getattr(base, k).update(v)
    return base


def test_check_digit_fixture_is_actually_valid():
    """以降のテストが依存する前提を先に固定する。"""
    from jc2ark.arkspec.betanumeric import verify_ark_check_digit

    assert verify_ark_check_digit("99999", GOOD)


# --- 完全一致 --------------------------------------------------------------


def test_exact_match_redirects():
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="https://x.example/1")}), "99999", GOOD)
    assert (r.outcome, r.status, r.location) == (Outcome.REDIRECT, 302, "https://x.example/1")


def test_d6_ark_without_url_is_described_not_redirected():
    """D6: 転送先が無いなら**裸の suffix にリダイレクトしない**。

    物理オブジェクトではこれが主たる応答になる（記述そのものが答え）。
    """
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="")}), "99999", GOOD)
    assert r.outcome is Outcome.DESCRIBE
    assert r.status == 200


def test_a2_hyphens_are_ignored_on_lookup():
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="https://x/")}), "99999", "kb1d-191j-10ds")
    assert r.outcome is Outcome.REDIRECT


# --- D5 / B3  祖先 passthrough --------------------------------------------


def test_d5_longest_ancestor_wins():
    """**arklet は最短一致だった**（`order_by(Length)` が昇順）ので、コレクション
    配下のアイテムがコレクションに解決されていた。"""
    repo = _repo(
        arks={
            f"99999/{GOOD}": FakeArk(url="https://plate/"),
            f"99999/{GOOD}/a/1": FakeArk(url="https://cold/A1"),
        }
    )
    r = resolve(repo, "99999", f"{GOOD}/a/1/0/0")
    assert r.location == "https://cold/A1/0/0"
    assert r.inherited_from == f"99999/{GOOD}/a/1"


def test_passthrough_appends_the_suffix():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/scan.nxs")})
    r = resolve(repo, "99999", f"{GOOD}/entry/instrument/detector")
    assert r.location == "https://repo/scan.nxs/entry/instrument/detector"
    assert r.suffix == "/entry/instrument/detector"


def test_b3_variant_separator_is_scanned():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/run.mzMLb")})
    r = resolve(repo, "99999", f"{GOOD}.mzml")
    assert r.location == "https://repo/run.mzMLb.mzml"


def test_c5_inflection_survives_passthrough():
    """C5: 祖先のメタデータを、**要求された ARK の名前で**返す（FAIR A2）。"""
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/scan.nxs")})
    r = resolve(repo, "99999", f"{GOOD}/entry", Inflection.JSON)
    assert r.outcome is Outcome.DESCRIBE
    assert r.status == 200
    assert r.requested == f"99999/{GOOD}/entry"
    assert r.inherited_from == f"99999/{GOOD}"


def test_d6_passthrough_to_urlless_ancestor_describes():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="")})
    r = resolve(repo, "99999", f"{GOOD}/entry")
    assert r.outcome is Outcome.DESCRIBE  # 裸の suffix に飛ばさない


# --- D1  チェックディジット ------------------------------------------------


def test_d1_mistranscribed_name_is_reported_as_such():
    r = resolve(_repo(), "99999", GOOD[:-1] + ("b" if GOOD[-1] != "b" else "c"))
    assert r.outcome is Outcome.NOT_FOUND
    assert "mistranscribed" in r.reason


def test_d1_is_not_applied_to_other_peoples_naans():
    """他所の NAAN はチェックディジットを使っているとは限らない。"""
    repo = FakeRepo(naans={"12345": FakeNaan(is_authoritative=False, redirect="https://other/")})
    r = resolve(repo, "12345", "anything-at-all")
    assert r.outcome is Outcome.FORWARD


# --- D3  自 NAAN の未知名は 404 -------------------------------------------


def test_d3_authoritative_naan_returns_404_not_a_redirect():
    """**arklet の実配備では自分自身へ 302 して無限ループになっていた。**"""
    r = resolve(_repo(), "99999", GOOD)
    assert r.outcome is Outcome.NOT_FOUND
    assert r.status == 404
    assert r.location == ""


# --- D2  未知 NAAN は n2t へ ----------------------------------------------


def test_d2_unknown_naan_is_forwarded_to_the_global_resolver():
    r = resolve(FakeRepo(), "12345", "abcde")
    assert r.outcome is Outcome.FORWARD
    assert r.location == "https://n2t.net/ark:/12345/abcde"


def test_d2_metadata_for_an_unknown_naan_is_404_not_a_forward():
    r = resolve(FakeRepo(), "12345", "abcde", Inflection.JSON)
    assert r.outcome is Outcome.NOT_FOUND


# --- shoulder 単位の解決委譲（T8） ----------------------------------------


def test_t8_shoulder_redirect_delegates_unregistered_names():
    repo = _repo(
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://vocab.example/ark:$id")}
    )
    r = resolve(repo, "99999", GOOD)
    assert r.outcome is Outcome.REDIRECT
    assert r.location == f"https://vocab.example/ark:99999/{GOOD}"


def test_registered_ark_wins_over_shoulder_redirect():
    """委譲は「この shoulder のもので、**まだ登録されていない**もの」にだけ効く。"""
    repo = _repo(
        arks={f"99999/{GOOD}": FakeArk(url="https://mine/")},
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://elsewhere/$id")},
    )
    assert resolve(repo, "99999", GOOD).location == "https://mine/"


@pytest.mark.parametrize(
    "template,expected_status,expected",
    [
        ("https://x.example/ark:$id", 302, "https://x.example/ark:99999/kb1abc"),
        ("https://x.example/${blade}", 302, "https://x.example/abc"),
        ("303 https://x.example/ark:$id", 303, "https://x.example/ark:99999/kb1abc"),
        ("301 https://x.example/${blade}", 301, "https://x.example/abc"),
    ],
)
def test_redirect_template_expansion(template, expected_status, expected):
    assert expand_redirect(template, "99999", "kb1abc") == (expected_status, expected)


# --- N4 / base name --------------------------------------------------------


def test_n4_double_slash_is_collapsed_before_lookup():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/x")})
    r = resolve(repo, "99999", f"{GOOD}//entry")
    assert r.location == "https://repo/x/entry"


def test_base_name_stops_at_the_first_structural_character():
    assert base_name("kb1abc/entry") == "kb1abc"
    assert base_name("kb1abc.mzml") == "kb1abc"
    assert base_name("kb1abc") == "kb1abc"
    assert base_name("kb1..abc") == "kb1..abc"  # 構造文字として成立しない


# ==========================================================================
# HTTP レベル
# ==========================================================================

pytestmark_http = pytest.mark.django_db


def _use_role(settings, role):
    """プロセスの役割を切り替える（URL 構成が変わる）。"""
    import importlib

    settings.JC2ARK_ROLE = role
    settings.IS_RESOLVER = role == "resolver"
    settings.IS_ADMIN = role == "admin"
    from jc2ark.entrypoints import urls

    importlib.reload(urls)
    settings.ROOT_URLCONF = "jc2ark.entrypoints.urls"


@pytest.fixture
def resolver_client(settings, client):
    _use_role(settings, "resolver")
    yield client
    _use_role(settings, "minter")


@pytest.fixture
def minted(db):
    from jc2ark.ark.models import Ark, Manager, Naan, Shoulder

    n = Naan.objects.create(naan="99999", name="JC2", na_policy="NP | NR, OP, CC | 2026 |")
    m = Manager.objects.create(naan=n, name="機関A")
    s = Shoulder.objects.create(shoulder="/kb1", naan=n, manager=m)
    m.default_shoulder = s
    m.save()
    ark, _ = Ark.objects.mint(
        shoulder=s, url="https://repo.example/records/1", title="テスト資料", who="NII"
    )
    return ark


@pytest.mark.django_db
def test_http_resolve_redirects(resolver_client, minted):
    r = resolver_client.get(f"/ark:/{minted.ark}")
    assert r.status_code == 302
    assert r["Location"] == "https://repo.example/records/1"


@pytest.mark.django_db
def test_http_label_is_case_insensitive(resolver_client, minted):
    assert resolver_client.get(f"/ARK:/{minted.ark}").status_code == 302


@pytest.mark.django_db
def test_http_passthrough(resolver_client, minted):
    r = resolver_client.get(f"/ark:/{minted.ark}/entry/detector")
    assert r["Location"] == "https://repo.example/records/1/entry/detector"


@pytest.mark.django_db
def test_http_info_inflection_renders(resolver_client, minted):
    r = resolver_client.get(f"/ark:/{minted.ark}?info")
    assert r.status_code == 200
    assert "テスト資料" in r.content.decode()


@pytest.mark.django_db
def test_http_json_inflection(resolver_client, minted):
    r = resolver_client.get(f"/ark:/{minted.ark}?json")
    body = r.json()
    assert body["ark"] == f"ark:/{minted.ark}"
    assert body["what"] == "テスト資料"
    assert body["commitment_level"] == "permanent-dynamic"


@pytest.mark.django_db
def test_c4_policy_inflection_returns_both_layers(resolver_client, minted):
    """`??` は **NAA ポリシー（NAAN 単位）と NMA コミットメント（対象単位）の両方**を返す。"""
    r = resolver_client.get(f"/ark:/{minted.ark}??")
    body = r.json()
    assert body["na_policy"] == "NP | NR, OP, CC | 2026 |"
    assert body["commitment_level"] == "permanent-dynamic"


@pytest.mark.django_db
def test_c2_inflection_is_not_appended_to_the_forwarded_url(resolver_client, minted):
    """C2: `??` を転送先に付けて渡さない。"""
    r = resolver_client.get(f"/ark:/{minted.ark}")
    assert "?" not in r["Location"]


@pytest.mark.django_db
def test_http_d3_unknown_name_under_our_naan_is_404(resolver_client, minted):
    from jc2ark.arkspec.betanumeric import check_digit_base, noid_check_digit

    stem = "kb1zzzzzzzz"
    name = stem + noid_check_digit(check_digit_base("99999", stem))
    r = resolver_client.get(f"/ark:/99999/{name}")
    assert r.status_code == 404
    assert "authoritative" in r.content.decode()


@pytest.mark.django_db
def test_http_d2_unknown_naan_goes_to_n2t(resolver_client, minted):
    r = resolver_client.get("/ark:/12345/abcde")
    assert r.status_code == 302
    assert r["Location"] == "https://n2t.net/ark:/12345/abcde"


@pytest.mark.django_db
def test_n1_well_known_ark(resolver_client, minted):
    r = resolver_client.get("/.well-known/ark")
    body = r.json()
    assert body["ark_resolver"] is True
    assert "99999" in body["naans"]
    assert body["na_policy"]["99999"].startswith("NP | NR, OP, CC")


@pytest.mark.django_db
def test_minter_does_not_expose_resolution(client, minted, settings):
    """**arklet は combined で minter も 302 を返していた。** ここでは分ける。"""
    assert settings.JC2ARK_ROLE == "minter"
    assert client.get(f"/ark:/{minted.ark}").status_code == 404
