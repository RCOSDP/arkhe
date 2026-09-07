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


# --------------------------------------------------------------------------
# 公開する OpenAPI は英語
# --------------------------------------------------------------------------


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_公開するOpenAPIに日本語が混ざらない(resolver):
    """**読者はこの台帳の外にいる。** 日本語が読めるとは限らない。

    docstring は日本語のまま残してあるので、`description` を渡し忘れると
    そこから日本語が仕様書に漏れる——**漏れたことに気づく手立てをここに置く**。
    口を足すたびに人が思い出す前提にはしない（この方針は `test_docs` 全体と同じ）。
    """
    import re

    from arkhe.app import create_app

    schema = create_app(
        Settings(resolver=resolver, database_url="sqlite://", auth=["apikey", "oauth2"],
                 admin_login="bearer", token_secret="x" * 32)
    ).openapi()

    cjk = re.compile(r"[ぁ-んァ-ヶ一-龥]")
    found = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and cjk.search(node):
            found.append(f"{path}: {node[:60]}")

    walk(schema)
    assert not found, "OpenAPI に日本語が混ざっている:\n  " + "\n  ".join(found)


# --------------------------------------------------------------------------
# 誤りの符号は参照ページに載っている
# --------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["reference/errors.md", "reference/errors.ja.md"])
def test_誤りの符号はすべて参照ページに載っている(page):
    """**符号を足したのに書き忘れる**を検査で止める。

    符号は「文面ではなくこれで判定してよい」と約束するものなので、
    **一覧に無い符号を返すのは約束を破ること**になる。設定とコマンドを
    同じやり方で縛っているのと同じ理由（このファイルの冒頭を見よ）。
    """
    from arkhe import errors

    text = (DOCS / page).read_text()
    missing = [c.number for c in errors.CODES if f"`{c.number}`" not in text]
    assert not missing, f"{page} に無い符号: {missing}"


def test_符号は重複せず番号順に並ぶ():
    """**符号は再利用しない。** 意味の違う 2 つが同じ番号だと、判定が壊れる。"""
    from arkhe import errors

    numbers = [c.number for c in errors.CODES]
    assert len(numbers) == len(set(numbers))
    assert numbers == sorted(numbers)
    assert all(n.startswith("ARKHE-") and n[6:].isdigit() for n in numbers)


def test_日本語の説明と英語の文面が両方ある():
    """**片方だけ書いて終わらせない。** 本文は英語、運用の説明は日本語で要る。"""
    import re

    from arkhe import errors

    cjk = re.compile(r"[ぁ-んァ-ヶ一-龥]")
    for c in errors.CODES:
        # 本文に日本語を混ぜない（`§` のような記号は英語の文でも使う）。
        assert c.message.strip() and not cjk.search(c.message), c.number
        assert cjk.search(c.ja), c.number
