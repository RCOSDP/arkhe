"""Localisation of the command line.

The language is fixed at import time, because that is when Typer builds its help, so a
test cannot switch it at run time. What is checked here is how the language is chosen and
whether the catalogues agree with each other.
"""

from __future__ import annotations

import pytest

from arkhe import cli_i18n


@pytest.mark.parametrize(
    "env,want",
    [
        ({}, "ja"),
        ({"LANG": "ja_JP.UTF-8"}, "ja"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANG": "en_GB"}, "en"),
        # C and POSIX do not mean English; they mean no language was stated. Look at
        # the next variable.
        ({"LANG": "C"}, "ja"),
        ({"LANG": "C", "LC_MESSAGES": "en_US.UTF-8"}, "en"),
        ({"LANG": "C.UTF-8"}, "ja"),
        # POSIX precedence: LC_ALL, then LC_MESSAGES, then LANG
        ({"LC_ALL": "en_GB.UTF-8", "LANG": "ja_JP.UTF-8"}, "en"),
        # An explicit setting wins over all of them
        ({"ARKHE_LANG": "en", "LC_ALL": "ja_JP.UTF-8"}, "en"),
        ({"ARKHE_LANG": "ja", "LANG": "en_US.UTF-8"}, "ja"),
        # A language we do not have falls back to the default rather than half English
        ({"LANG": "fr_FR.UTF-8"}, "ja"),
        ({"ARKHE_LANG": "fr"}, "ja"),
    ],
)
def test_the_language_comes_from_the_environment(env, want):
    assert cli_i18n.pick(env) == want


def test_no_catalogue_is_missing_a_key():
    """Adding a message to one language only would otherwise go unnoticed. Importing
    would fail too, but the intent belongs here."""
    ja = set(cli_i18n.JA)
    for lang, cat in cli_i18n.CATALOGS.items():
        assert set(cat) == ja, f"{lang} differs by {sorted(ja ^ set(cat))}"


def test_both_languages_have_the_same_placeholders():
    """If the set of {name} slots differs, one language raises KeyError."""
    import string

    def slots(s: str) -> set[str]:
        return {f for _, f, _, _ in string.Formatter().parse(s) if f}

    for key, ja in cli_i18n.JA.items():
        assert slots(ja) == slots(cli_i18n.EN[key]), f"{key} has different placeholders"


def test_a_translation_can_be_looked_up():
    assert cli_i18n.CATALOGS["en"]["check.ok"] == "The configuration is valid"
    assert "{days}" not in cli_i18n.EN["client.breakglass.expires"].format(days=7)
