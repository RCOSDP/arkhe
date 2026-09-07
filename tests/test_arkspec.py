"""純関数層の単体テスト。

各テストは `ark_acceptance_criteria.md` の受け入れ条件 ID に対応する。
**Django も DB も使わない。** ARK 仕様の難所をここだけで固める。

> arklet 側のテストは `tests/ark/views_tests.py` の 41 件で**すべて HTTP レベル**
> であり、純関数の単体テストは存在しなかった。ここは新規に書いている。
"""

from __future__ import annotations

import pytest

from arkhe.arkspec.betanumeric import (
    BETANUMERIC,
    CONSONANTS,
    check_digit_base,
    generate_noid,
    noid_check_digit,
    verify_ark_check_digit,
    verify_check_digit,
)
from arkhe.arkspec.naming import (
    ArkParseError,
    ark_key,
    compact_ark,
    gen_prefixes,
    is_structural_at,
    normalize_percent,
    normalize_structural,
    parse_ark,
    split_after_normalized,
    strip_hyphens,
)
from arkhe.arkspec.shoulder import (
    InvalidShoulder,
    generate_shoulder,
    shoulder_capacity,
    split_shoulder,
    validate_shoulder,
)

# --------------------------------------------------------------------------
# betanumeric / チェックディジット
# --------------------------------------------------------------------------


def test_betanumeric_charset_excludes_vowels_and_ell():
    assert len(BETANUMERIC) == 29
    for banned in "aeioul":
        assert banned not in BETANUMERIC
    assert len(CONSONANTS) == 19


def test_check_digit_is_stable():
    """N7: 計算範囲を変えない（適合を維持する）。"""
    assert noid_check_digit("99999/kb1d191j10d") == noid_check_digit("99999/kb1d191j10d")
    assert len(noid_check_digit("99999kb1d191j10d")) == 1
    assert noid_check_digit("99999kb1d191j10d") in BETANUMERIC


def test_check_digit_detects_single_character_error():
    """NCDA が保証する「単一文字誤りの検出」。"""
    base = "99999kb1d191j10d"
    digit = noid_check_digit(base)
    misses = 0
    for i, char in enumerate(base):
        for replacement in BETANUMERIC:
            if replacement == char:
                continue
            corrupted = base[:i] + replacement + base[i + 1 :]
            if noid_check_digit(corrupted) == digit:
                misses += 1
    assert misses == 0, f"{misses} 件の単一文字誤りが検出できていない"


def test_check_digit_detects_adjacent_transposition():
    """NCDA が保証する「隣接転置の検出」。"""
    base = "99999kb1d191j10d"
    digit = noid_check_digit(base)
    for i in range(len(base) - 1):
        if base[i] == base[i + 1]:
            continue
        swapped = base[:i] + base[i + 1] + base[i] + base[i + 2 :]
        assert noid_check_digit(swapped) != digit, f"位置 {i} の転置が検出できない"


def test_verify_check_digit_roundtrip():
    """D1: 未登録 ARK はチェックディジットを検証してから 404 を返す。"""
    body = "99999kb1d191j10d"
    assert verify_check_digit(body + noid_check_digit(body))
    assert not verify_check_digit(body + "z" if noid_check_digit(body) != "z" else body + "b")
    assert not verify_check_digit("x")


def test_verify_ark_check_digit_takes_naan_and_name():
    """検査桁は **naan + "/" + shoulder + noid** に対して計算される（N7）。

    blade だけを渡すと合わない——この API の誤用は実際に踏んだので固定する。
    """
    naan, shoulder, noid = "99999", "kb1", "d191j10d"
    base = check_digit_base(naan, f"{shoulder}{noid}")
    name = f"{shoulder}{noid}{noid_check_digit(base)}"
    assert verify_ark_check_digit(naan, name)
    assert not verify_ark_check_digit("99998", name)  # NAAN 違いは弾く
    assert not verify_check_digit(name)  # name だけでは合わない


def test_check_digit_base_includes_the_slash():
    """**NAAN と name のあいだの `/` を含める。**

    `/` は betanumeric に無いのでスコアには入らないが、以降の文字の位置を 1 つ
    ずらすため、含めるかどうかで検査桁が変わる。arklet と揃えないと相互に検証
    できなくなる。
    """
    naan, name = "99999", "kb1d191j10d"
    assert check_digit_base(naan, name) == "99999/kb1d191j10d"
    with_slash = noid_check_digit(f"{naan}/{name}")
    without_slash = noid_check_digit(f"{naan}{name}")
    assert with_slash != without_slash, "スラッシュの有無で値が変わることを固定する"
    # arklet の採番と同じ組み立て（shoulder に先頭スラッシュを含む形）と一致する
    assert noid_check_digit(f"{naan}{'/kb1'}{'d191j10d'}") == with_slash


def test_generate_noid_uses_only_betanumeric():
    noid = generate_noid(8)
    assert len(noid) == 8
    assert set(noid) <= set(BETANUMERIC)
    with pytest.raises(ValueError):
        generate_noid(0)


# --------------------------------------------------------------------------
# A1  ラベルの大小非依存 / NAAN は小文字化・name は大小保持
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["ark:", "ARK:", "Ark:", "aRk:"])
def test_a1_label_is_case_insensitive(label):
    parsed = parse_ark(f"{label}/99999/kb1d191j10ds")
    assert parsed.naan == "99999"
    assert parsed.name == "kb1d191j10ds"


def test_a1_naan_is_lowercased_but_name_keeps_case():
    parsed = parse_ark("ark:/BCD12/Kb1D191J10ds")
    assert parsed.naan == "bcd12"  # NAAN は小文字化
    assert parsed.name == "Kb1D191J10ds"  # name の大小は保持


def test_a1_slash_after_label_is_optional():
    assert parse_ark("ark:99999/xyz").naan == "99999"
    assert parse_ark("ark:/99999/xyz").naan == "99999"


def test_a1_nma_prefix_is_returned():
    parsed = parse_ark("https://n2t.net/ark:/99999/xyz")
    assert parsed.nma == "https://n2t.net/"
    assert parsed.naan == "99999"


# --------------------------------------------------------------------------
# N2  NAAN は文字列。先頭ゼロは別の NAAN
# --------------------------------------------------------------------------


def test_n2_leading_zero_is_a_different_naan():
    """**arklet の最重要バグ。** `int(naan)` で `099999` と `99999` が潰れていた。"""
    a = parse_ark("ark:/99999/xyz")
    b = parse_ark("ark:/099999/xyz")
    assert a.naan == "99999"
    assert b.naan == "099999"
    assert a.naan != b.naan
    assert ark_key(*a[1:]) != ark_key(*b[1:])


def test_n2_naan_is_str_not_int():
    assert isinstance(parse_ark("ark:/99999/xyz").naan, str)


# --------------------------------------------------------------------------
# N3  betanumeric NAAN（歴史的 NAAN）
# --------------------------------------------------------------------------


def test_n3_betanumeric_naan_is_accepted():
    assert parse_ark("ark:/bcd12/xyz").naan == "bcd12"


def test_n3_naan_rejects_non_betanumeric():
    for bad in ["ark:/abc12/xyz", "ark:/ab-12/xyz", "ark:/12_45/xyz"]:
        with pytest.raises(ArkParseError):
            parse_ark(bad)


# --------------------------------------------------------------------------
# F1  NAAN の長さ制限
# --------------------------------------------------------------------------


def test_f1_naan_up_to_the_spec_minimum_is_accepted():
    """§2.3: "implementations **must support a minimum NAAN length of 16 octets**".

    **以前は 10 で弾いていた。** arklet が NAAN を `int()` に通すための防御を
    そのまま持っていたもので、N2（整数化しない）を決めた時点で理由は消えていた。
    """
    assert parse_ark("ark:/" + "9" * 16 + "/xyz").naan == "9" * 16
    assert parse_ark("ark:/" + "bcd" * 5 + "1" + "/xyz").naan == "bcd" * 5 + "1"
    with pytest.raises(ArkParseError):
        parse_ark("ark:/" + "9" * 17 + "/xyz")


def test_malformed_arks_are_rejected():
    for bad in ["", "not-an-ark", "ark:/99999", "ark:/99999/", "ark:/ /x", "ark:/99999/x/ark:/1/2"]:
        with pytest.raises(ArkParseError):
            parse_ark(bad)


# --------------------------------------------------------------------------
# A2  ハイフンは無意味
# --------------------------------------------------------------------------


def test_a2_hyphens_are_insignificant():
    assert strip_hyphens("kb1d-191j-10ds") == "kb1d191j10ds"
    assert strip_hyphens("kb1d191j10ds") == "kb1d191j10ds"


def test_a2_split_measures_head_without_hyphens_but_keeps_tail_verbatim():
    head, tail = split_after_normalized("kb1d-191j10ds/a-b/c", len("kb1d191j10ds"))
    assert strip_hyphens(head) == "kb1d191j10ds"
    assert tail == "/a-b/c"  # tail のハイフンは意味を持つので保持


# --------------------------------------------------------------------------
# N4  構造文字の正規化 / `.` は両側に非構造文字が要る
# --------------------------------------------------------------------------


def test_n4_consecutive_slashes_are_collapsed():
    assert normalize_structural("kb1xyz//entry") == "kb1xyz/entry"
    assert normalize_structural("kb1xyz///a//b") == "kb1xyz/a/b"


def test_n4_period_needs_non_structural_on_both_sides():
    assert is_structural_at("a.b", 1)
    assert not is_structural_at("a..b", 1)  # 右が構造文字
    assert not is_structural_at("a..b", 2)  # 左が構造文字
    assert not is_structural_at(".ab", 0)  # 先頭
    assert not is_structural_at("ab.", 2)  # 末尾


def test_n4_no_impossible_ancestor_from_double_period():
    """`abc..def` から `abc.` という存在しえない祖先候補を作らない。"""
    assert "abc." not in list(gen_prefixes("abc..def"))


# --------------------------------------------------------------------------
# D5 / B3  祖先は最長一致。`.`（変種）も走査対象
# --------------------------------------------------------------------------


def test_d5_ancestors_are_yielded_longest_first():
    got = list(gen_prefixes("nx1npwkrkq4v/entry/instrument/detector"))
    assert got == [
        "nx1npwkrkq4v/entry/instrument",
        "nx1npwkrkq4v/entry",
        "nx1npwkrkq4v",
    ]


def test_b3_variant_separator_is_scanned():
    """mzML ↔ mzMLb のような「同一対象の別形態」は `.` で表す。"""
    assert "mz3kfj02c3wm" in list(gen_prefixes("mz3kfj02c3wm.mzml"))


def test_ancestors_mix_containment_and_variant():
    got = list(gen_prefixes("mz3kfj02c3wm.mzml/spectrum/1042"))
    assert got[0] == "mz3kfj02c3wm.mzml/spectrum"
    assert got[-1] == "mz3kfj02c3wm"


def test_no_ancestors_for_a_bare_name():
    assert list(gen_prefixes("kb1d191j10ds")) == []


# --------------------------------------------------------------------------
# B2 / N5  shoulder の規約と不透明性
# --------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["/x5", "/kb1", "/bcd7", "/z9"])
def test_b2_valid_shoulders(good):
    validate_shoulder(good)


@pytest.mark.parametrize(
    "bad",
    ["kb1", "/kb", "/1kb", "/kb1/", "/kb.1", "/kb1/x2", "/KB1", "/ka1", "/kl1", "/"],
)
def test_b2_invalid_shoulders(bad):
    with pytest.raises(InvalidShoulder):
        validate_shoulder(bad)


def test_n5_generated_shoulders_are_opaque_and_valid():
    for _ in range(200):
        s = generate_shoulder()
        validate_shoulder(s)
        assert len(s) == 4  # '/' + 2 子音 + 1 数字
        assert s[-1].isdigit()  # first-digit 規約の末尾


def test_shoulder_capacity_matches_the_design():
    assert shoulder_capacity(3) == 3610  # 800 組織で使用率 22.2%
    assert shoulder_capacity(2) == 190


def test_generated_shoulders_do_not_leak_join_order():
    """連番だと加入順が漏れる。乱数なので隣接値が連続しないことを確かめる。"""
    seq = [generate_shoulder() for _ in range(50)]
    assert len(set(seq)) > 40  # 衝突だらけでないこと
    assert seq != sorted(seq)  # 生成順に並んでいない


def test_first_digit_convention_splits_without_a_separator():
    """**区切り文字なしで shoulder と blade の境界が判定できる。**"""
    assert split_shoulder("kb1k4m2p9x") == ("kb1", "k4m2p9x")
    assert split_shoulder("bb1z93ht2dv2") == ("bb1", "z93ht2dv2")
    assert split_shoulder("nodigits") == ("", "nodigits")


# --------------------------------------------------------------------------
# N4  構造文字の正規化（draft-kunze-ark-42 §3.2）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,want",
    [
        # "two structural characters in a row … replaced by the first character"
        ("abc//def", "abc/def"),
        ("abc///def", "abc/def"),
        ("abc..def", "abc.def"),
        ("abc./def", "abc.def"),
        ("abc/.def", "abc/def"),
        ("a//.//b", "a/b"),
        # "initial and final occurrences are removed"
        ("abc/", "abc"),
        ("abc.", "abc"),
        ("/abc", "abc"),
        (".abc", "abc"),
        ("/abc/", "abc"),
        # 触らないもの
        ("abc/def", "abc/def"),
        ("abc.def", "abc.def"),
        ("abc", "abc"),
    ],
)
def test_n4_structural_normalization_follows_the_spec(src, want):
    assert normalize_structural(src) == want


def test_n4_normalization_converges_in_one_pass():
    """「収束するまで反復」を 1 回の sub で満たせること。

    正規表現が走り全体を貪欲に取るので、結果に構造文字の隣接は残らない。
    """
    got = normalize_structural("a/././/./b")
    assert got == "a/b"
    assert normalize_structural(got) == got  # 冪等


def test_n4_a_name_of_only_structural_characters_collapses_to_nothing():
    """病的な入力。**空になっても落ちない**こと（呼び出し側で未登録として扱う）。"""
    assert normalize_structural("...") == ""
    assert normalize_structural("/") == ""


# --------------------------------------------------------------------------
# A3  非 ASCII のハイフン様文字
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "char,name",
    [
        ("-", "HYPHEN-MINUS"),
        ("‐", "HYPHEN"),
        ("‑", "NON-BREAKING HYPHEN"),
        ("‒", "FIGURE DASH"),
        ("–", "EN DASH"),
        ("—", "EM DASH"),
        ("―", "HORIZONTAL BAR"),
        ("−", "MINUS SIGN"),
        ("－", "FULLWIDTH HYPHEN-MINUS"),
    ],
)
def test_a3_hyphen_like_characters_are_removed(char, name):
    """**Word や PDF から貼られた ARK が落ちないこと。**

    仕様: "non-ASCII hyphen-like characters (eg, U+2010 to U+2015) may arrive in
    the place of hyphens"。`-` が `–` に自動置換されるのは日本語の文書で実際に起きる。
    """
    assert strip_hyphens(f"kb1d{char}191j{char}10ds") == "kb1d191j10ds", name


def test_a3_the_prolonged_sound_mark_is_not_a_hyphen():
    """`ー`（U+30FC）は落とさない。**punctuation ではなく修飾文字。**

    見た目が似ているからと落とすと、日本語として意味のある文字を黙って消すことに
    なる。ARK の名前は betanumeric なので、混入していれば結局は未登録になる——
    識別子を書き換えてしまうよりよい。
    """
    assert strip_hyphens("kb1dー191j") == "kb1dー191j"


def test_a3_split_counts_past_every_hyphen_flavour():
    """**head/tail の分割位置がずれないこと。**

    数える側が ASCII だけ飛ばしていると、非 ASCII のハイフンぶん位置がずれて
    修飾子の切り出しを間違える。
    """
    head, tail = split_after_normalized("kb1d–191j－10ds/entry", 12)
    assert strip_hyphens(head) == "kb1d191j10ds"
    assert tail == "/entry"


# --------------------------------------------------------------------------
# A4  %-エンコード（draft-kunze-ark-42 §3.1・§3.2 手順5）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,want",
    [
        # 手順5: "the two characters following every occurrence of '%' are
        # converted to uppercase"
        ("x54%2fc2", "x54%2Fc2"),
        ("x54%7d", "x54%7D"),
        ("%2f%2e%2d", "%2F%2E%2D"),
        # "The case of all other letters in the ARK string must be preserved."
        ("Ab%2fCd", "Ab%2FCd"),
        # 三つ組として成立しないものは触らない（**壊れた入力を別の文字列にしない**）
        ("50%off", "50%off"),
        ("x%zz", "x%zz"),
        ("x%2", "x%2"),
        ("x%", "x%"),
    ],
)
def test_a4_percent_hex_is_uppercased_and_nothing_else(src, want):
    assert normalize_percent(src) == want


def test_a4_encoded_slash_is_not_a_structural_character():
    """**`%2F` は「区切りではない `/`」を書く唯一の方法**（§3.2「隠す目的なら可」）。

    復号すると `x54%2Fc2`（1 つの名前）が `x54/c2`（`x54` に含まれる `c2`）に化ける
    ——別の識別子であり、祖先も変わる。
    """
    name = normalize_percent("x54%2fc2")
    assert name == "x54%2Fc2"
    assert normalize_structural(name) == name  # 構造文字として畳まれない
    assert list(gen_prefixes(name)) == []      # 祖先を生やさない
    assert list(gen_prefixes("x54/c2")) == ["x54"]  # 素の `/` はこちら


def test_a4_encoded_hyphen_survives_hyphen_removal():
    """`%2D` は落とさない。**ハイフンは予約文字で、隠す目的の %-エンコードは合法。**

    落とすと「無意味だから無視される `-`」と「意味を持たせるために隠した `-`」の
    区別が消える。
    """
    assert strip_hyphens("kb1-d%2D191j") == "kb1d%2D191j"


# --------------------------------------------------------------------------
# A5  ラベルの新旧（draft-kunze-ark-42 §2.2）
# --------------------------------------------------------------------------


def test_a5_generation_uses_the_new_label_form():
    """生成は新形式。**表記を決める場所を 1 つにしてある**ので、ここで固定できる。"""
    assert compact_ark("99999/x9abc") == "ark:99999/x9abc"
    assert compact_ark("99999") == "ark:99999"  # NAAN だけの ARK も同じ


@pytest.mark.parametrize("src", ["ark:99999/x9abc", "ark:/99999/x9abc", "ARK:/99999/x9abc"])
def test_a5_both_label_forms_are_still_accepted(src):
    """受理は両形式。**"must be recognized in perpetuity"** なので、狭めない。"""
    p = parse_ark(src)
    assert (p.naan, p.name) == ("99999", "x9abc")
