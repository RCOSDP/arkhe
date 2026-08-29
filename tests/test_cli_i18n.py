"""コマンドの国際化。

**言語は import の時点で決まる**（Typer が help を組み立てるのがそこだから）ので、
実行時に切り替えるテストは書けない。決め方そのものと、カタログの整合を見る。
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
        # `C` と `POSIX` は「英語」ではなく「言語の情報が無い」。次の変数を見る。
        ({"LANG": "C"}, "ja"),
        ({"LANG": "C", "LC_MESSAGES": "en_US.UTF-8"}, "en"),
        ({"LANG": "C.UTF-8"}, "ja"),
        # POSIX の優先順位: LC_ALL > LC_MESSAGES > LANG
        ({"LC_ALL": "en_GB.UTF-8", "LANG": "ja_JP.UTF-8"}, "en"),
        # 明示の指定はすべてに優先する
        ({"ARKHE_LANG": "en", "LC_ALL": "ja_JP.UTF-8"}, "en"),
        ({"ARKHE_LANG": "ja", "LANG": "en_US.UTF-8"}, "ja"),
        # 持っていない言語は既定に落とす（半端に英語へ倒さない）
        ({"LANG": "fr_FR.UTF-8"}, "ja"),
        ({"ARKHE_LANG": "fr"}, "ja"),
    ],
)
def test_言語は環境から決まる(env, want):
    assert cli_i18n.pick(env) == want


def test_カタログに抜けがない():
    """**片方だけ足して気づかない**を防ぐ。import 時にも落ちるが、意図として残す。"""
    ja = set(cli_i18n.JA)
    for lang, cat in cli_i18n.CATALOGS.items():
        assert set(cat) == ja, f"{lang} の鍵が {sorted(ja ^ set(cat))} でずれている"


def test_差し込み先が両言語で揃っている():
    """`{name}` の集合が言語で違うと、片方だけ KeyError で落ちる。"""
    import string

    def slots(s: str) -> set[str]:
        return {f for _, f, _, _ in string.Formatter().parse(s) if f}

    for key, ja in cli_i18n.JA.items():
        assert slots(ja) == slots(cli_i18n.EN[key]), f"{key} の差し込み先がずれている"


def test_訳が引ける():
    assert cli_i18n.CATALOGS["en"]["check.ok"] == "The configuration is valid"
    assert "{days}" not in cli_i18n.EN["client.breakglass.expires"].format(days=7)
