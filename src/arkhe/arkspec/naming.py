"""Parsing, normalising and generating ancestors of ARK strings.

The hard parts of the specification are collected in this module. Nothing here touches a
database, so it can be verified on its own.

Derived in part from arklet (https://github.com/internetarchive/arklet),
MIT License, Copyright (c) Internet Archive. See LICENSE.

Acceptance criteria:
  A1  ARK: is matched case-insensitively. The NAAN is lowercased; the name keeps its
      case
  A2  hyphens carry no meaning and are ignored
  N2  a NAAN is kept and compared as a string (ark:099999/... and ark:99999/... differ)
  N3  betanumeric NAANs are accepted, which exist from before 2001
  N4  structural characters are normalised. A . is structural only with ordinary
      characters on both sides
  F1  the length limit on a NAAN: up to the 16 octets the specification requires
  D5  the longest ancestor wins
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from .betanumeric import BETANUMERIC

#: ARK reserves / for containment, meaning a part, and . for a variant. Both open the
#: qualifier area after the base name, so inheritance scans for both.
QUALIFIER_SEPARATORS = "/."

#: F1: draft-kunze-ark-42, 2.3: "For received ARKs, implementations **must
#: support a minimum NAAN length of 16 octets**."
#:
#: It used to be 10, inherited from arklet's len(naan) > 10, which existed because that
#: implementation passed a NAAN through int() and had to guard the conversion. N2 settles
#: that a NAAN is kept and compared as a string and never made an integer, so there is no
#: conversion to guard, and the limit was below what the specification requires for no
#: reason.
#:
#: Every NAAN assigned since 2001 is five digits, but this is the minimum a receiving
#: implementation must support, not a statement about the numbers we hand out.
MAX_NAAN_LENGTH = 16

#: F1: 3.1: "implementations must support a minimum length of **255 octets**
#: for the string composed of the Base Name plus Qualifier."
#:
#: Names are visible ASCII, so octets and characters are the same count; a percent
#: encoding counts as the three ASCII characters %XX.
MAX_NAME_LENGTH = 255

#: The length the ledger key (<naan>/<name>) needs: the two minimums added together.
MAX_ARK_LENGTH = MAX_NAAN_LENGTH + 1 + MAX_NAME_LENGTH

#: A1: the label matches case-insensitively.
_LABEL = re.compile(r"ark:", re.IGNORECASE)

#: N3: a NAAN is betanumeric, digits and consonants. Since 2001 they are five digits,
#: but older ones may be betanumeric.
_NAAN_CHARS = frozenset(BETANUMERIC)


class ParsedArk(NamedTuple):
    """nma is the host part that preceded the ARK, when there was one."""

    nma: str
    naan: str  # N2: a string, never an integer
    name: str  # A1: keeps its case


class ArkParseError(ValueError):
    """It cannot be read as an ARK."""


def parse_ark(ark: str, *, allow_naan_only: bool = False) -> ParsedArk:
    """Split an ARK string into (nma, naan, name).

    A1: ark:, ARK: and Ark: are all accepted; the NAAN is lowercased and the name keeps
    its case.
    N2: the NAAN is returned as a string. 099999 and 99999 are different NAANs.
    N3: betanumeric NAANs are accepted.
    F1: the length limits are applied first.
    D4: with allow_naan_only=True, ark:99999 with no name is accepted and name is "".
    """
    if not isinstance(ark, str):
        raise ArkParseError("not a string")

    parts = _LABEL.split(ark)
    if len(parts) != 2:
        raise ArkParseError("missing or repeated 'ark:' label")
    nma, rest = parts

    rest = rest.lstrip("/")
    naan, slash, name = rest.partition("/")
    if not slash or not name:
        # D4: an ARK that is only a NAAN is not malformed. ark:99999 names the
        # namespace itself, and n2t walks up to it as well. It is returned with an
        # empty name for callers that handle it; those that do not pass
        # allow_naan_only=False.
        if not allow_naan_only:
            raise ArkParseError("missing name part")
        name = ""

    # F1: length is checked before any conversion or comparison. Empty and too long
    # are different reasons: with one message, ark:/ would be told it exceeds 16
    # octets.
    if not naan:
        raise ArkParseError("missing NAAN")
    if len(naan) > MAX_NAAN_LENGTH:
        raise ArkParseError(f"NAAN is longer than {MAX_NAAN_LENGTH} octets")

    naan = naan.lower()  # A1: only the NAAN is lowercased
    if not set(naan) <= _NAAN_CHARS:  # N3
        raise ArkParseError("NAAN must be betanumeric")

    return ParsedArk(nma=nma, naan=naan, name=name)


def ark_key(naan: str, name: str) -> str:
    """The normalised key used for storage and comparison.

    For N2 the NAAN is joined as a string. Hyphens are removed by the caller (A2: pass a
    name that has been through strip_hyphens).
    """
    return f"{naan}/{name}"


def compact_ark(key: str) -> str:
    """Turn a ledger key (<naan>/<name>) into the compact ARK form.

    A5. draft-kunze-ark-42, 2.2:

    > There is a new form of the label, "ark:", and an old form, "ark:/", both of
    > which **must be recognized in perpetuity**. Implementations **should generate
    > new ARKs in the new form (without the "/")**.

    Accepting and generating are deliberately asymmetric. What is accepted stays both
    forms in perpetuity (parse_ark); what is generated uses the new form. Keeping the old
    one on the way out means the strings we hand round become someone else's input, and
    the old form never shrinks.

    It is one function because scattered f"ark:/{...}" would be fixed in one place and
    not another. One place decides the spelling.
    """
    return f"ark:{key}"


#: A3: the hyphen-like characters that are removed.
#:
#: draft-kunze-ark-42, 3.2: "All hyphens are removed. Implementors should
#: be aware that **non-ASCII hyphen-like characters (eg, U+2010 to U+2015) may
#: arrive in the place of hyphens**."
#:
#: The specification says "eg", so the list is an example, and what actually arrives
#: has been added. Documents written in a word processor often have - replaced with an
#: en dash automatically, and full-width input produces its own variant.
#:
#: U+30FC is not included. It looks similar but is a letter modifier rather than
#: punctuation, and removing it would silently delete a meaningful character. ARK names
#: are betanumeric, so a name containing it ends in a 404 anyway: the diagnosis is
#: "unregistered", which is better than rewriting an identifier.
HYPHENS = (
    "-"  # U+002D HYPHEN-MINUS
    "\u2010"  # HYPHEN
    "\u2011"  # NON-BREAKING HYPHEN
    "\u2012"  # FIGURE DASH
    "\u2013"  # EN DASH, the most common automatic replacement
    "\u2014"  # EM DASH
    "\u2015"  # HORIZONTAL BAR
    "\u2212"  # MINUS SIGN, from full-width input and from formulae
    "\uff0d"  # FULLWIDTH HYPHEN-MINUS
)
_HYPHEN_TABLE = dict.fromkeys(map(ord, HYPHENS))

#: The structural characters that separate components: / for containment, . for a
#: variant.
STRUCTURAL = "/."
_STRUCTURAL_RUN = re.compile(r"([/.])[/.]+")

#: A4: a percent-encoded triplet. Only what is a valid pair of hex digits counts.
_PERCENT_TRIPLET = re.compile(r"%([0-9A-Fa-f]{2})")


def normalize_percent(text: str) -> str:
    """Upper-case the hex of a percent encoding (normalisation, step 5).

    A4. draft-kunze-ark-42, 3.2, step 5: "the two characters following every
    occurrence of '%' are converted to uppercase. **The case of all other letters in
    the ARK string must be preserved.**"

    This is not only about keeping %2f and %2F from being different identifiers. 3.1
    gives the reason: upper-case hex is preferred because software that knows nothing
    about ARKs compares URLs for equality. Without it, two forms become different the
    moment they are compared outside this system.

    Anything that is not a valid triplet is left alone. A bare % or %zz is invalid, but
    correcting it here would silently turn broken input into a different string, and it
    may have arrived as part of a name. It is passed through and fails at lookup.
    """
    return _PERCENT_TRIPLET.sub(lambda m: "%" + m.group(1).upper(), text)


def strip_hyphens(text: str) -> str:
    """Remove hyphens.

    A2: hyphens are there for readability, or arrive from a line break, so they are
    ignored when comparing. A3: every character in HYPHENS is removed, not only the
    ASCII one.

    Derived from arklet, extended to non-ASCII for A3.
    """
    return text.translate(_HYPHEN_TABLE)


def normalize_structural(text: str) -> str:
    """Normalise the structural characters.

    N4. draft-kunze-ark-42, 3.2:

    > Structural characters (slash and period) are normalized: **initial and final
    > occurrences are removed**, and **two structural characters in a row (e.g., //
    > or ./) are replaced by the first character**, iterating until each occurrence
    > has at least one non-structural character on either side.

    This used to collapse only runs of slashes, on the reading that a . is structural
    only with ordinary characters on both sides and therefore should not be collapsed.
    That was a misreading: "ordinary characters on both sides" is the condition for
    stopping after collapsing ("iterating until ..."), not a reason not to collapse.
    Collapse first, then decide what is structural in the result.

    One substitution is enough because the pattern takes each run greedily. Afterwards no
    two structural characters are adjacent, which is the stopping condition.
    """
    return _STRUCTURAL_RUN.sub(r"\1", text.strip(STRUCTURAL))


def is_structural_at(text: str, index: int) -> bool:
    """Whether text[index] separates components.

    N4: for a ., the specification requires at least one ordinary character on each side
    before it separates anything. Without that check, abc..def would produce abc., an
    ancestor that cannot exist.
    """
    char = text[index]
    if char == "/":
        return True
    if char != ".":
        return False
    if index == 0 or index == len(text) - 1:
        return False
    return (
        text[index - 1] not in QUALIFIER_SEPARATORS and text[index + 1] not in QUALIFIER_SEPARATORS
    )


def gen_prefixes(name: str) -> Iterator[str]:
    """Yield the ancestors of a name, longest first.

    D5: resolution walks back from the end and stops at the first registered ancestor,
    which is the longest match. They are yielded longest first so that the caller can
    take the first hit.

    N4: it only cuts where a character really separates components.

    Derived from arklet, with the is_structural_at condition added.
    """
    for i in range(len(name) - 1, 0, -1):
        if name[i] in QUALIFIER_SEPARATORS and is_structural_at(name, i):
            yield name[:i]


def split_after_normalized(text: str, length: int) -> tuple[str, str]:
    """Split immediately after the character at length, counting without hyphens.

    The head is compared against stored ARKs, so it is measured with hyphens removed. The
    tail is a path into a resource this resolver did not mint, so it is returned exactly
    as it arrived, hyphens included.

    Derived from arklet.
    """
    seen = 0
    for i, char in enumerate(text):
        if char in HYPHENS:  # A3: non-ASCII hyphens are not counted either
            continue
        if seen == length:
            return text[:i], text[i:]
        seen += 1
    return text, ""
