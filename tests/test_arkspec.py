"""Unit tests for the pure functions.

Each test matches an acceptance criterion in ark_acceptance_criteria.md. Nothing here
touches a database. The hard parts of the ARK specification are pinned down here.

arklet's tests were 41 cases in tests/ark/views_tests.py, all at the HTTP level; there
were no unit tests of the pure functions. These are new.
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
# betanumeric and check digits
# --------------------------------------------------------------------------


def test_betanumeric_charset_excludes_vowels_and_ell():
    assert len(BETANUMERIC) == 29
    for banned in "aeioul":
        assert banned not in BETANUMERIC
    assert len(CONSONANTS) == 19


def test_check_digit_is_stable():
    """N7: the range the digit is computed over never changes, so it stays
    interoperable."""
    assert noid_check_digit("99999/kb1d191j10d") == noid_check_digit("99999/kb1d191j10d")
    assert len(noid_check_digit("99999kb1d191j10d")) == 1
    assert noid_check_digit("99999kb1d191j10d") in BETANUMERIC


def test_check_digit_detects_single_character_error():
    """NCDA guarantees that a single wrong character is detected."""
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
    assert misses == 0, f"{misses} single-character errors went undetected"


def test_check_digit_detects_adjacent_transposition():
    """NCDA guarantees that swapping two neighbours is detected."""
    base = "99999kb1d191j10d"
    digit = noid_check_digit(base)
    for i in range(len(base) - 1):
        if base[i] == base[i + 1]:
            continue
        swapped = base[:i] + base[i + 1] + base[i] + base[i + 2 :]
        assert noid_check_digit(swapped) != digit, f"a swap at {i} went undetected"


def test_verify_check_digit_roundtrip():
    """D1: an unregistered ARK has its check digit verified before we answer 404."""
    body = "99999kb1d191j10d"
    assert verify_check_digit(body + noid_check_digit(body))
    assert not verify_check_digit(body + "z" if noid_check_digit(body) != "z" else body + "b")
    assert not verify_check_digit("x")


def test_verify_ark_check_digit_takes_naan_and_name():
    """N7: the digit is computed over naan + "/" + shoulder + noid.

    Passing only the blade does not match. That misuse actually happened, so it is
    pinned down here.
    """
    naan, shoulder, noid = "99999", "kb1", "d191j10d"
    base = check_digit_base(naan, f"{shoulder}{noid}")
    name = f"{shoulder}{noid}{noid_check_digit(base)}"
    assert verify_ark_check_digit(naan, name)
    assert not verify_ark_check_digit("99998", name)  # a different NAAN fails
    assert not verify_check_digit(name)  # the name alone does not match


def test_check_digit_base_includes_the_slash():
    """The / between the NAAN and the name is included.

    It is not in the betanumeric set, so it scores nothing, but it shifts every later
    character by one position, which changes the digit. Without matching arklet here,
    neither side could verify the other's names.
    """
    naan, name = "99999", "kb1d191j10d"
    assert check_digit_base(naan, name) == "99999/kb1d191j10d"
    with_slash = noid_check_digit(f"{naan}/{name}")
    without_slash = noid_check_digit(f"{naan}{name}")
    assert with_slash != without_slash, "the slash has to change the value"
    # The same assembly arklet used, with the leading slash inside the shoulder
    assert noid_check_digit(f"{naan}{'/kb1'}{'d191j10d'}") == with_slash


def test_generate_noid_uses_only_betanumeric():
    noid = generate_noid(8)
    assert len(noid) == 8
    assert set(noid) <= set(BETANUMERIC)
    with pytest.raises(ValueError):
        generate_noid(0)


# --------------------------------------------------------------------------
# A1  the label ignores case; the NAAN is lowercased and the name keeps its case
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["ark:", "ARK:", "Ark:", "aRk:"])
def test_a1_label_is_case_insensitive(label):
    parsed = parse_ark(f"{label}/99999/kb1d191j10ds")
    assert parsed.naan == "99999"
    assert parsed.name == "kb1d191j10ds"


def test_a1_naan_is_lowercased_but_name_keeps_case():
    parsed = parse_ark("ark:/BCD12/Kb1D191J10ds")
    assert parsed.naan == "bcd12"  # the NAAN is lowercased
    assert parsed.name == "Kb1D191J10ds"  # the name keeps its case


def test_a1_slash_after_label_is_optional():
    assert parse_ark("ark:99999/xyz").naan == "99999"
    assert parse_ark("ark:/99999/xyz").naan == "99999"


def test_a1_nma_prefix_is_returned():
    parsed = parse_ark("https://n2t.net/ark:/99999/xyz")
    assert parsed.nma == "https://n2t.net/"
    assert parsed.naan == "99999"


# --------------------------------------------------------------------------
# N2  a NAAN is a string, and a leading zero makes a different one
# --------------------------------------------------------------------------


def test_n2_leading_zero_is_a_different_naan():
    """arklet's most serious bug: int(naan) collapsed 099999 and 99999."""
    a = parse_ark("ark:/99999/xyz")
    b = parse_ark("ark:/099999/xyz")
    assert a.naan == "99999"
    assert b.naan == "099999"
    assert a.naan != b.naan
    assert ark_key(*a[1:]) != ark_key(*b[1:])


def test_n2_naan_is_str_not_int():
    assert isinstance(parse_ark("ark:/99999/xyz").naan, str)


# --------------------------------------------------------------------------
# N3  betanumeric NAANs, which exist for historical reasons
# --------------------------------------------------------------------------


def test_n3_betanumeric_naan_is_accepted():
    assert parse_ark("ark:/bcd12/xyz").naan == "bcd12"


def test_n3_a_naan_with_a_terminal_letter_reads_as_its_own_naan():
    """The ARKA Tech working group is considering letting a NAAN holder add a terminal
    letter to carry meaning: ark:12345c/987 for a "concept" object assigned by 12345.

    Nothing here implements that. This pins what happens today, so that a change to how
    NAANs are read cannot quietly make such an ARK unreadable: it parses, and 12345c is
    a different NAAN from 12345 (N2), which is what a string NAAN buys. Whether the two
    should be related, and how the check digit is then computed, is for the working
    group to settle.
    """
    variant = parse_ark("ark:12345c/987")
    assert variant.naan == "12345c"
    assert variant.naan != parse_ark("ark:12345/987").naan


def test_n3_naan_rejects_non_betanumeric():
    for bad in ["ark:/abc12/xyz", "ark:/ab-12/xyz", "ark:/12_45/xyz"]:
        with pytest.raises(ArkParseError):
            parse_ark(bad)


# --------------------------------------------------------------------------
# F1  how long a NAAN may be
# --------------------------------------------------------------------------


def test_f1_naan_up_to_the_spec_minimum_is_accepted():
    """2.3: implementations must support a minimum NAAN length of 16 octets.

    This used to refuse anything over 10, a guard arklet needed because it passed NAANs
    through int(). Once N2 settled that they are strings, the reason was gone.
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
# A2  hyphens carry no meaning
# --------------------------------------------------------------------------


def test_a2_hyphens_are_insignificant():
    assert strip_hyphens("kb1d-191j-10ds") == "kb1d191j10ds"
    assert strip_hyphens("kb1d191j10ds") == "kb1d191j10ds"


def test_a2_split_measures_head_without_hyphens_but_keeps_tail_verbatim():
    head, tail = split_after_normalized("kb1d-191j10ds/a-b/c", len("kb1d191j10ds"))
    assert strip_hyphens(head) == "kb1d191j10ds"
    assert tail == "/a-b/c"  # hyphens in the tail do mean something, so they stay


# --------------------------------------------------------------------------
# N4  normalising structural characters; a . needs ordinary characters on both sides
# --------------------------------------------------------------------------


def test_n4_consecutive_slashes_are_collapsed():
    assert normalize_structural("kb1xyz//entry") == "kb1xyz/entry"
    assert normalize_structural("kb1xyz///a//b") == "kb1xyz/a/b"


def test_n4_period_needs_non_structural_on_both_sides():
    assert is_structural_at("a.b", 1)
    assert not is_structural_at("a..b", 1)  # structural on the right
    assert not is_structural_at("a..b", 2)  # structural on the left
    assert not is_structural_at(".ab", 0)  # at the start
    assert not is_structural_at("ab.", 2)  # at the end


def test_n4_no_impossible_ancestor_from_double_period():
    """abc..def must not produce abc., an ancestor that cannot exist."""
    assert "abc." not in list(gen_prefixes("abc..def"))


# --------------------------------------------------------------------------
# D5 / B3  the longest ancestor wins, and . for variants is scanned too
# --------------------------------------------------------------------------


def test_d5_ancestors_are_yielded_longest_first():
    got = list(gen_prefixes("nx1npwkrkq4v/entry/instrument/detector"))
    assert got == [
        "nx1npwkrkq4v/entry/instrument",
        "nx1npwkrkq4v/entry",
        "nx1npwkrkq4v",
    ]


def test_b3_variant_separator_is_scanned():
    """Another form of the same object, such as mzML against mzMLb, uses a dot."""
    assert "mz3kfj02c3wm" in list(gen_prefixes("mz3kfj02c3wm.mzml"))


def test_ancestors_mix_containment_and_variant():
    got = list(gen_prefixes("mz3kfj02c3wm.mzml/spectrum/1042"))
    assert got[0] == "mz3kfj02c3wm.mzml/spectrum"
    assert got[-1] == "mz3kfj02c3wm"


def test_no_ancestors_for_a_bare_name():
    assert list(gen_prefixes("kb1d191j10ds")) == []


# --------------------------------------------------------------------------
# B2 / N5  the shoulder convention, and keeping it opaque
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
        assert len(s) == 4  # a slash, two consonants and a digit
        assert s[-1].isdigit()  # the digit that ends a shoulder


def test_shoulder_capacity_matches_the_design():
    assert shoulder_capacity(3) == 3610  # 800 organisations would use 22.2%
    assert shoulder_capacity(2) == 190


def test_generated_shoulders_do_not_leak_join_order():
    """Sequential shoulders would leak the order organisations joined in."""
    seq = [generate_shoulder() for _ in range(50)]
    assert len(set(seq)) > 40  # not full of collisions
    assert seq != sorted(seq)  # not in generation order


def test_first_digit_convention_splits_without_a_separator():
    """The boundary between shoulder and blade is found without a separator."""
    assert split_shoulder("kb1k4m2p9x") == ("kb1", "k4m2p9x")
    assert split_shoulder("bb1z93ht2dv2") == ("bb1", "z93ht2dv2")
    assert split_shoulder("nodigits") == ("", "nodigits")


# --------------------------------------------------------------------------
# N4  normalising structural characters (draft-kunze-ark-42, 3.2)
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
        # left alone
        ("abc/def", "abc/def"),
        ("abc.def", "abc.def"),
        ("abc", "abc"),
    ],
)
def test_n4_structural_normalization_follows_the_spec(src, want):
    assert normalize_structural(src) == want


def test_n4_normalization_converges_in_one_pass():
    """One substitution is enough for what the specification calls repeating until it
    converges, because the pattern takes each run greedily.
    """
    got = normalize_structural("a/././/./b")
    assert got == "a/b"
    assert normalize_structural(got) == got  # idempotent


def test_n4_a_name_of_only_structural_characters_collapses_to_nothing():
    """A pathological input must not raise; the caller treats the empty result as an
    unregistered name."""
    assert normalize_structural("...") == ""
    assert normalize_structural("/") == ""


# --------------------------------------------------------------------------
# A3  hyphen-like characters that are not ASCII
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
    """An ARK pasted out of a word processor or a PDF still works.

    The specification says non-ASCII hyphen-like characters, for example U+2010 to
    U+2015, may arrive in place of hyphens. Editors really do replace - with an en dash.
    """
    assert strip_hyphens(f"kb1d{char}191j{char}10ds") == "kb1d191j10ds", name


def test_a3_the_prolonged_sound_mark_is_not_a_hyphen():
    """U+30FC is a letter modifier, not punctuation, so it is kept.

    Dropping it because it looks similar would silently delete a meaningful character.
    ARK names are betanumeric, so a name containing it ends up unregistered anyway,
    which is better than rewriting an identifier.
    """
    mark = "\u30fc"  # KATAKANA-HIRAGANA PROLONGED SOUND MARK
    assert strip_hyphens(f"kb1d{mark}191j") == f"kb1d{mark}191j"


def test_a3_split_counts_past_every_hyphen_flavour():
    """The split between head and tail must not drift.

    If only ASCII hyphens were skipped while counting, every other kind would shift the
    position and the qualifier would be cut in the wrong place.
    """
    head, tail = split_after_normalized("kb1d–191j－10ds/entry", 12)
    assert strip_hyphens(head) == "kb1d191j10ds"
    assert tail == "/entry"


# --------------------------------------------------------------------------
# A4  percent encoding (draft-kunze-ark-42, 3.1 and step 5 of 3.2)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,want",
    [
        # Step 5: "the two characters following every occurrence of '%' are
        # converted to uppercase"
        ("x54%2fc2", "x54%2Fc2"),
        ("x54%7d", "x54%7D"),
        ("%2f%2e%2d", "%2F%2E%2D"),
        # "The case of all other letters in the ARK string must be preserved."
        ("Ab%2fCd", "Ab%2FCd"),
        # Anything that is not a valid triplet is left alone, so broken input does
        # not silently become a different string
        ("50%off", "50%off"),
        ("x%zz", "x%zz"),
        ("x%2", "x%2"),
        ("x%", "x%"),
    ],
)
def test_a4_percent_hex_is_uppercased_and_nothing_else(src, want):
    assert normalize_percent(src) == want


def test_a4_encoded_slash_is_not_a_structural_character():
    """%2F is the only way to write a / that is not a separator, which 3.2 permits for
    exactly that purpose.

    Decoding it would turn x54%2Fc2, one name, into x54/c2, meaning c2 inside x54. That
    is a different identifier with a different ancestor.
    """
    name = normalize_percent("x54%2fc2")
    assert name == "x54%2Fc2"
    assert normalize_structural(name) == name  # not folded as a structural character
    assert list(gen_prefixes(name)) == []      # it has no ancestors
    assert list(gen_prefixes("x54/c2")) == ["x54"]  # a plain slash does


def test_a4_encoded_hyphen_survives_hyphen_removal():
    """%2D is kept. A hyphen is reserved, and encoding it to hide it is allowed.

    Dropping it would erase the difference between a hyphen that is ignored because it
    means nothing and one that was encoded to mean something.
    """
    assert strip_hyphens("kb1-d%2D191j") == "kb1d%2D191j"


# --------------------------------------------------------------------------
# A5  the old and new label forms (draft-kunze-ark-42, 2.2)
# --------------------------------------------------------------------------


def test_a5_generation_uses_the_new_label_form():
    """We generate the new form. One place decides the spelling, so it can be pinned
    down here."""
    assert compact_ark("99999/x9abc") == "ark:99999/x9abc"
    assert compact_ark("99999") == "ark:99999"  # an ARK that is only a NAAN, too


@pytest.mark.parametrize("src", ["ark:99999/x9abc", "ark:/99999/x9abc", "ARK:/99999/x9abc"])
def test_a5_both_label_forms_are_still_accepted(src):
    """Both forms are accepted: the specification says they must be recognised in
    perpetuity."""
    p = parse_ark(src)
    assert (p.naan, p.name) == ("99999", "x9abc")
