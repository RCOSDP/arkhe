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
    body = resolver_client.get(f"/ark:/{minted.ark}??").content.decode()
    assert "policy: NP | NR, OP, CC | 2026 |" in body
    assert "commitment-level: permanent-dynamic" in body


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


# --------------------------------------------------------------------------
# C1  inflection の 4 形態
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_bare_question_mark_returns_erc_anvl(resolver_client, minted):
    """`?` — **ERC/ANVL の簡潔な記述。** ARK が伝統的に返してきた形。

    裸の `?` は `QUERY_STRING` だけでは見分けられないので、**gunicorn が入れる
    `RAW_URI`** で判定する（実測: アクセスログにも `GET …/name?` と残る）。
    """
    r = resolver_client.get(f"/ark:/{minted.ark}", RAW_URI=f"/ark:/{minted.ark}?")
    assert r.status_code == 200
    body = r.content.decode()
    assert body.startswith("erc:")
    assert "what: テスト資料" in body
    assert "who: NII" in body


@pytest.mark.django_db
def test_without_raw_uri_the_bare_question_mark_is_ignored(resolver_client, minted):
    """`RAW_URI` が無い環境では諦める。**仕様上 `?` は optional** なので壊れない。"""
    assert resolver_client.get(f"/ark:/{minted.ark}").status_code == 302


@pytest.mark.django_db
def test_double_question_mark_is_not_confused_with_the_single_one(resolver_client, minted):
    """`??` は `QUERY_STRING == "?"` で判定するので、`RAW_URI` があっても揺れない。"""
    body = resolver_client.get(
        f"/ark:/{minted.ark}??", RAW_URI=f"/ark:/{minted.ark}??"
    ).content.decode()
    assert "policy: NP | NR, OP, CC" in body


@pytest.mark.django_db
def test_all_four_inflections_are_distinct(resolver_client, minted):
    k = minted.ark
    got = {
        "(なし)": resolver_client.get(f"/ark:/{k}").status_code,
        "?": resolver_client.get(f"/ark:/{k}", RAW_URI=f"/ark:/{k}?")["Content-Type"],
        "?info": resolver_client.get(f"/ark:/{k}?info")["Content-Type"],
        "?json": resolver_client.get(f"/ark:/{k}?json")["Content-Type"],
        "??": resolver_client.get(f"/ark:/{k}??")["Content-Type"],
    }
    assert got["(なし)"] == 302
    assert got["?"].startswith("text/plain")
    assert got["?info"].startswith("text/html")
    assert got["?json"].startswith("application/json")
    # `??` は **JSON ではなく ANVL**。実測で n2t.net もそう返す（2026-08-17）。
    assert got["??"].startswith("text/plain")


@pytest.mark.django_db
def test_brief_survives_suffix_passthrough(resolver_client, minted):
    """C5: **祖先から継承しても答えられる**（FAIR A2）。"""
    p = f"/ark:/{minted.ark}/entry/detector"
    r = resolver_client.get(p, RAW_URI=p + "?")
    assert r.status_code == 200
    assert r.content.decode().startswith("erc:")


@pytest.mark.django_db
def test_missing_kernel_elements_get_the_reserved_code(resolver_client, minted):
    """ERC: **値が無くても要素は落とさず、理由を示す符号を置く。**

    draft-kunze-erc-01「a best effort に失敗したら、その場に標準値を置かねば
    ならない」。空欄にすると「まだ入れていない」と「元から無い」が区別できない。
    """
    minted.who = ""
    minted.when = ""
    minted.save(update_fields=["who", "when"])
    body = resolver_client.get(
        f"/ark:/{minted.ark}", RAW_URI=f"/ark:/{minted.ark}?"
    ).content.decode()
    assert "who: (:unav)" in body
    assert "when: (:unav)" in body
    assert body.count("\n") == 5  # erc: ＋ 4 要素。**要素は必ず 4 つ**


@pytest.mark.django_db
def test_double_question_mark_is_brief_plus_the_commitment(resolver_client, minted):
    """`??` = `?` ＋ 永続性宣言。draft-42 の「more metadata」と
    arks.org の「maintenance commitment」は、こう組めば両立する。"""
    k = minted.ark
    brief = resolver_client.get(f"/ark:/{k}", RAW_URI=f"/ark:/{k}?").content.decode()
    more = resolver_client.get(f"/ark:/{k}??").content.decode()
    for line in brief.splitlines():
        assert line in more.splitlines(), f"`?` の {line!r} が `??` に無い"
    assert "policy: " in more
    assert "commitment-level: " in more


@pytest.mark.django_db
def test_json_still_carries_the_policy(resolver_client, minted):
    """`??` を ANVL に寄せたので、**JSON が要る利用者は `?json` で全部取れる**こと。"""
    d = resolver_client.get(f"/ark:/{minted.ark}?json").json()
    assert d["na_policy"].startswith("NP | NR, OP, CC")
    assert "commitment" in d


@pytest.mark.django_db
def test_optional_labels_are_omitted_rather_than_marked_unavailable(resolver_client, minted):
    """**符号で埋めるのは kernel の 4 要素だけ。**

    対象単位の `commitment` が空でも、約束は `commitment-level` で分かっている。
    そこに `(:unav)` を置くと「我々の約束が不明」と読めてしまう。
    """
    assert minted.commitment == ""
    body = resolver_client.get(f"/ark:/{minted.ark}??").content.decode()
    assert "commitment: " not in body
    assert "commitment-level: permanent-dynamic" in body
    # kernel の 4 要素は落とさない（この記録は `when` が空）
    assert "when: (:unav)" in body


@pytest.mark.django_db
def test_info_shows_the_kernel_even_when_values_are_missing(resolver_client, minted):
    """`?info` でも kernel の 4 要素を落とさない。**`?` と同じ理由。**"""
    minted.who = ""
    minted.when = ""
    minted.save(update_fields=["who", "when"])
    body = resolver_client.get(f"/ark:/{minted.ark}?info").content.decode()
    for label in ("who", "what", "when", "where"):
        assert f"<dt>{label}</dt>" in body
    assert body.count("(:unav)") == 2


@pytest.mark.django_db
def test_info_carries_the_permanence_declaration(resolver_client, minted):
    """C4: **`?info` は仕様上の必須 inflection。**

    ここに永続性宣言が無いと、人間の読み手は「誰がどれだけ面倒を見るのか」を
    知る手段が無い（`??` は optional なので、そちらに置くだけでは足りない）。
    """
    body = resolver_client.get(f"/ark:/{minted.ark}?info").content.decode()
    assert "NP | NR, OP, CC" in body
    assert "permanent-dynamic" in body
    assert "恒久・内容は更新されうる" in body  # 符号だけでなく人間向けの表示名も


@pytest.mark.django_db
def test_info_links_to_the_other_representations_with_absolute_paths(resolver_client, minted):
    """導線が無いと `?` や `??` の存在に気づけない。

    **先頭の `/` が要る**——相対のまま `ark:/…` と書くと、ブラウザが `ark:` を
    URI スキームとみなして遷移に失敗する。
    """
    body = resolver_client.get(f"/ark:/{minted.ark}?info").content.decode()
    for suffix in ("?", "??", "?json"):
        assert f'href="/ark:/{minted.ark}{suffix}"' in body
    assert 'href="ark:/' not in body  # スキーム扱いされる書き方が残っていないこと


@pytest.mark.django_db
def test_info_leaks_no_template_comments(resolver_client, minted):
    """**Django の `{# #}` は単一行専用。** 複数行に跨ると剥がれずに配信される。

    `{% comment %}` を使うこと。設計意図を書いたコメントが利用者に見えてしまう。
    """
    body = resolver_client.get(f"/ark:/{minted.ark}?info").content.decode()
    assert "{#" not in body and "#}" not in body
    assert "draft-kunze-erc-01" not in body  # 実際に漏れていた文言


@pytest.mark.django_db
def test_info_writes_the_inherited_ark_in_full(resolver_client, minted):
    """継承元も `ark:/…` と書く。**素の鍵で見せると別物に見える。**"""
    body = resolver_client.get(f"/ark:/{minted.ark}/entry?info").content.decode()
    assert f"<code>ark:/{minted.ark}</code>" in body


# --------------------------------------------------------------------------
# N4 / A3  正規化が解決に効いていること
# --------------------------------------------------------------------------


def test_n4_trailing_slash_does_not_leak_into_the_target():
    """`…/name/` は素の ARK と同一。**末尾スラッシュを転送先に付けない。**

    仕様: "initial and final occurrences are removed"。
    """
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/x")})
    bare = resolve(repo, "99999", GOOD)
    with_slash = resolve(repo, "99999", GOOD + "/")
    assert with_slash.location == bare.location == "https://repo/x"
    assert with_slash.suffix == ""


def test_n4_double_period_reaches_the_variant_instead_of_looking_mistranscribed():
    """`x..mzml` は `x.mzml` に正規化され、祖先に届く。

    **直す前は「転記ミス」という別の診断で 404 になっていた**——正規化されない
    まま名前全体で検査桁が計算されていたため。変種要求の打ち間違いは実際に起きる。
    """
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/run.mzMLb")})
    r = resolve(repo, "99999", f"{GOOD}..mzml")
    assert r.outcome is Outcome.REDIRECT
    assert r.location == "https://repo/run.mzMLb.mzml"
    assert r.suffix == ".mzml"


def test_n4_leading_period_is_dropped():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/x")})
    assert resolve(repo, "99999", "." + GOOD).outcome is Outcome.REDIRECT


@pytest.mark.parametrize("dash", ["-", "‐", "‑", "‒", "–", "—", "―", "−", "－"])
def test_a3_hyphen_like_characters_resolve(dash):
    """**Word や PDF から貼られた ARK が解決すること。**"""
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/x")})
    mangled = GOOD[:4] + dash + GOOD[4:]
    assert resolve(repo, "99999", mangled).location == "https://repo/x"


@pytest.mark.django_db
def test_http_normalization_applies_end_to_end(resolver_client, minted):
    k = minted.ark
    for variant in (f"/ark:/{k}/", f"/ark:/{k}//", f"/ark:/{k[:8]}–{k[8:]}"):
        r = resolver_client.get(variant)
        assert r.status_code == 302, variant
        assert r["Location"] == "https://repo.example/records/1", variant


# --------------------------------------------------------------------------
# D4  NAAN だけの ARK
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_d4_naan_only_ark_describes_the_namespace(resolver_client, minted):
    """`ark:/99999` は名前空間そのものを指す。**400 で突き返さない。**"""
    r = resolver_client.get("/ark:/99999")
    assert r.status_code == 200
    body = r.content.decode()
    assert "ark:/99999" in body
    assert "NP | NR, OP, CC" in body


@pytest.mark.django_db
def test_d4_naan_only_ark_answers_every_inflection(resolver_client, minted):
    got = {
        "?json": resolver_client.get("/ark:/99999?json"),
        "?info": resolver_client.get("/ark:/99999?info"),
        "??": resolver_client.get("/ark:/99999??"),
    }
    assert got["?json"].json()["naan"] == "99999"
    assert got["?json"].json()["authoritative"] is True
    assert got["?info"]["Content-Type"].startswith("text/html")
    assert "policy: NP | NR, OP, CC" in got["??"].content.decode()


@pytest.mark.django_db
def test_d4_does_not_list_the_shoulders(resolver_client, minted):
    """**N5: shoulder は不透明。** 並べると機関の構成が読めてしまう。

    委譲済み minter は `/.well-known/ark` で公開しているので、必要な情報は別経路で
    取れる。ここで機関ごとの割り当てまで見せる理由が無い。
    """
    for path in ("/ark:/99999", "/ark:/99999?json"):
        body = resolver_client.get(path).content.decode()
        assert "/kb1" not in body
        assert "機関A" not in body


@pytest.mark.django_db
def test_d4_unknown_naan_only_ark_goes_to_the_global_resolver(resolver_client, minted):
    """D2 と揃える。**知らない名前空間は上位に投げる。**"""
    r = resolver_client.get("/ark:/77777")
    assert r.status_code == 302
    assert r["Location"] == "https://n2t.net/ark:/77777"


@pytest.mark.django_db
def test_d4_a_foreign_naan_is_forwarded_to_its_own_resolver(resolver_client, minted):
    from jc2ark.ark.models import Naan

    Naan.objects.create(
        naan="67890", name="他所", is_authoritative=False, redirect="https://other.example/"
    )
    r = resolver_client.get("/ark:/67890")
    assert r.status_code == 302
    assert r["Location"].startswith("https://other.example/")
