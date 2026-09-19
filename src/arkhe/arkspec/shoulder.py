"""The shoulder convention, and how shoulders are assigned.

A shoulder is a namespace below a NAAN, and it is how a namespace is delegated to an
organisation.

Every NAAN uses one (design_ark_multitenant_authz.md, 2.1.1). Even where one
organisation holds one NAAN, it is given a default shoulder. Without that the model
would branch per NAAN, and the first-digit convention would hold for some NAANs and not
others.

Acceptance criteria:
  B2  a shoulder is a single segment; nesting is not allowed
  N5  it carries no meaning a reader could interpret. A discipline or an instrument
      belongs in format or in the payload, not in the name of an ARK
"""

from __future__ import annotations

import re
import secrets

from .betanumeric import CONSONANTS

#: The first-digit convention: a shoulder runs from the start of the name up to and
#: including the first digit, which is how the boundary between shoulder and blade is
#: found without a separator. Consonants followed by one digit; vowels and l are
#: excluded, so no word appears by accident.
SHOULDER_PATTERN = re.compile(rf"^/[{CONSONANTS}]+[0-9]$")

#: The length used here: two consonants and a digit. That holds 3,610 organisations,
#: which is 22.2% used at 800 of them (ark_ra_model.md, 5.0).
DEFAULT_SHOULDER_LENGTH = 3


class InvalidShoulder(ValueError):
    pass


def validate_shoulder(shoulder: str) -> None:
    """Check a shoulder against the first-digit convention.

    B2 forbids a slash after the shoulder, because it would imply both that the part
    before it names a real object and that the whole ARK is contained in that object.
    Neither is true.
    """
    if not shoulder.startswith("/"):
        raise InvalidShoulder("Shoulders must start with a forward slash")
    if not SHOULDER_PATTERN.match(shoulder):
        raise InvalidShoulder(
            "A shoulder must be a single segment of lowercase betanumeric "
            "consonants ending in one digit, e.g. '/x5'. It may not contain a "
            "further '/' or '.', which would falsely imply containment."
        )


def generate_shoulder(length: int = DEFAULT_SHOULDER_LENGTH) -> str:
    """Return one opaque shoulder that follows the convention.

    They are not assigned in sequence. /bb1, /bb2, /bb3 would leak the order
    organisations joined in, which is against the point of opacity. Like a NOID it is
    drawn at random, and the caller retries on a collision.

    A shoulder is not a secret; it marks a public namespace. Opaque here means carrying
    no meaning, not being hard to guess.
    """
    if length < 2:
        raise ValueError("shoulder length must be >= 2 (consonants + one digit)")
    body = "".join(secrets.choice(CONSONANTS) for _ in range(length - 1))
    # All ten digits are used. The betanumeric set has no vowels, so there is no o to
    # confuse with 0, and excluding one would cost a tenth of the capacity for nothing.
    return "/" + body + secrets.choice("0123456789")


def shoulder_capacity(length: int = DEFAULT_SHOULDER_LENGTH) -> int:
    """How many shoulders a given length holds.

    Three characters, two consonants and a digit, give 19 squared times 10, or 3,610.
    Against 800 organisations that is 22.2% used, with 4.5 times the room
    (ark_ra_model.md, 5.0).
    """
    return len(CONSONANTS) ** (length - 1) * 10


def split_shoulder(name: str) -> tuple[str, str]:
    """Split a name into (shoulder, blade) using the first-digit convention.

    Finding the boundary without a separator is the point of the convention. The
    shoulder runs from the start up to and including the first digit; with no digit the
    shoulder is empty.
    """
    for i, char in enumerate(name):
        if char.isdigit():
            return name[: i + 1], name[i + 1 :]
    return "", name
