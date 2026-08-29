"""参照ページが実装から遅れていないこと。

**「忘れずに書く」に頼らない。** これは arkhe の設計方針そのもの（決まりは
コードに持たせる）を、文書にも当てるだけのこと——覚えている前提の規則は
いずれ破られる。実際、この検査を入れた時点で設定 2 つとコマンド 1 つが
落ちていた。

対象は**表に並べる参照ページだけ**。散文の解説まで機械で縛ると、書く手が
止まって誰も直さなくなる。
"""

from __future__ import annotations

import pathlib

import pytest

from arkhe import cli
from arkhe.settings import Settings

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"


def _commands(app, prefix: str = "") -> list[str]:
    out = [f"{prefix}{c.name or c.callback.__name__.replace('_', '-')}"
           for c in app.registered_commands]
    for g in app.registered_groups:
        out += _commands(g.typer_instance, f"{prefix}{g.name} ")
    return sorted(out)


@pytest.mark.parametrize("page", ["reference/configuration.md", "reference/configuration.ja.md"])
def test_設定はすべて参照ページに載っている(page):
    doc = (DOCS / page).read_text(encoding="utf-8")
    missing = [f"ARKHE_{n.upper()}" for n in Settings.model_fields
               if f"ARKHE_{n.upper()}" not in doc]
    assert not missing, f"{page} に無い設定: {missing}"


@pytest.mark.parametrize("page", ["reference/cli.md", "reference/cli.ja.md"])
def test_コマンドはすべて参照ページに載っている(page):
    doc = (DOCS / page).read_text(encoding="utf-8")
    missing = [c for c in _commands(cli.app) if f"arkhe {c}" not in doc]
    assert not missing, f"{page} に無いコマンド: {missing}"


def test_日本語版と英語版の行数がそろっている():
    """**片方だけ足す**のを見つける。訳文の一致までは見ない（無理だし、要らない）。

    表の行が片方に無ければ、そちらの読者にはその設定もコマンドも存在しない。
    """
    def rows(text: str) -> int:
        return sum(1 for ln in text.splitlines() if ln.startswith("| `"))

    for stem in ("reference/configuration", "reference/cli"):
        en = rows((DOCS / f"{stem}.md").read_text(encoding="utf-8"))
        ja = rows((DOCS / f"{stem}.ja.md").read_text(encoding="utf-8"))
        assert en == ja, f"{stem}: 表の行数が en={en} ja={ja}"
