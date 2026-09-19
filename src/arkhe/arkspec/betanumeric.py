"""The betanumeric character set and the NOID check digit.

ARK names are made of digits and consonants, with the vowels and l left out: the
betanumeric set. The convention assumes names will be copied by hand
(ark_domain_pid_design.md, 7):

- typing from a label, l and 1, or O and 0, cannot be confused
- no word appears by accident
- the NCDA check digit detects a single wrong character and a swap of neighbours

Derived from arklet (https://github.com/internetarchive/arklet), MIT License,
Copyright (c) Internet Archive. See LICENSE.

Acceptance criteria: N6 (betanumeric only) and N7 (the range the check digit is
computed over stays interoperable).
"""

from __future__ import annotations

import secrets

#: Ten digits and nineteen consonants, leaving out aeiou and l: 29 characters.
BETANUMERIC = "0123456789bcdfghjkmnpqrstvwxz"

#: Just the consonants, which is what a shoulder is made of before its digit.
CONSONANTS = "bcdfghjkmnpqrstvwxz"

_MODULUS = len(BETANUMERIC)  # 29


def noid_check_digit(name: str) -> str:
    """Return the NCDA check digit for a base compact name.

    N7: the specification places the digit at the end of the blade and computes it over
    the base compact name without the label, excluding any qualifier. Callers pass
    f"{naan}{shoulder}{noid}".

    Characters outside the betanumeric set score nothing, as in the original NOID.

    Derived from arklet.
    """
    total = 0
    for position, char in enumerate(name, start=1):
        score = BETANUMERIC.find(char)
        if score > 0:
            total += position * score
    return BETANUMERIC[total % _MODULUS]


def verify_check_digit(base_with_digit: str) -> bool:
    """Treat the last character as the check digit and verify it.

    What is passed is the whole base compact name: naan + shoulder + noid + digit.
    Passing only the blade always returns False, because N7 computes the digit over the
    base compact name without the label, which includes the NAAN. Normally, call
    verify_ark_check_digit(naan, name) instead.
    """
    if len(base_with_digit) < 2:
        return False
    body, digit = base_with_digit[:-1], base_with_digit[-1]
    return noid_check_digit(body) == digit


def check_digit_base(naan: str, name_without_digit: str) -> str:
    """Build the string the check digit is computed over: the base compact name.

    The slash between the NAAN and the name is included. The specification computes over
    the base compact name without the label, and a compact name is 99999/kb1... arklet
    included it too, as f"{naan}{shoulder}{noid}" with the shoulder written /kb1.

    The slash is not in the betanumeric set, so it scores nothing, but it shifts every
    later character by one position, which changes the digit. Without matching here, an
    ARK minted by arklet could not be verified.
    """
    return f"{naan}/{name_without_digit}"


def verify_ark_check_digit(naan: str, name: str) -> bool:
    """Verify the check digit of ark:<naan>/<name>. This is the function to call.

    D1: an unregistered ARK is verified here, and a mismatch answers 404 saying it looks
    like a transcription error. Forwarding without verifying throws away what NCDA
    guarantees: detecting one wrong character or a swap of neighbours.

    A qualifier, anything after a / or a ., is outside the digit (N7), so pass the base
    name alone, as cut out by the ancestor search.
    """
    if len(name) < 2:
        return False
    return noid_check_digit(check_digit_base(naan, name[:-1])) == name[-1]


def generate_noid(length: int) -> str:
    """Return a random betanumeric string.

    Derived from arklet.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    return "".join(secrets.choice(BETANUMERIC) for _ in range(length))
