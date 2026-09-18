"""参照ページが実装から遅れていないこと。

**「忘れずに書く」に頼らない。** これは arkhe の設計方針そのもの（決まりは
コードに持たせる）を、文書にも当てるだけのこと——覚えている前提の規則は
いずれ破られる。実際、この検査を入れた時点で設定 2 つとコマンド 1 つが
落ちていた。

対象は**表に並べる参照ページだけ**。散文の解説まで機械で縛ると、書く手が
止まって誰も直さなくなる。**例外は例示する ARK** ——あれは文面ではなく、
検査桁が合うかどうかという機械で確かめられる事実だから、散文の中にあっても
縛ってよい。
"""

from __future__ import annotations

import pathlib
import re

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


# --------------------------------------------------------------------------
# 例示する ARK は、実際に採番される形をしている
# --------------------------------------------------------------------------

#: 例示に使う NAAN。他所の NAAN（`ark:12345/…`、実在の `ark:67531/…`）は、
#: 名前の形もその機関のものなので、こちらの規約を当てない。
EXAMPLE_NAAN = "99999"

#: **わざと合わない例。** 検査桁が何を守っているかは、合わない例でしか見せられない。
DELIBERATELY_WRONG = {
    "x9tn1qkq2g8": "転記ミスを 404 と区別して見せる（ARKHE-1403）",
    "c7w545sj4zz": "外から来た名前を import が拒む（ARKHE-1012）",
}

#: `ark:99999/x9…` のように読者が自分の採番結果を入れる場所は、末尾の `…` で除く。
#: 修飾子（`/c3`・`.pdf`・`%2F…`）はここで切れる——N7 のとおり検査桁は base name に
#: 対して計算されるので、切れたところがちょうど検査すべき範囲になる。
_ARK = re.compile(r"ark:/?(\d{5})/([0-9a-z]+)(\u2026?)")

#: OpenAPI は実装から生成する。ここに含めると、**src の docstring に書いた例**も縛れる。
_PAGES = sorted(DOCS.rglob("*.md")) + sorted(DOCS.glob("assets/openapi-*.json"))


def _example_arks():
    """文書に出てくる `ark:99999/…` を (ページ, 行, 名前) で返す。"""
    for path in _PAGES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for naan, name, elided in _ARK.findall(line):
                if naan == EXAMPLE_NAAN and not elided:
                    yield path.relative_to(DOCS), lineno, name


def test_例示するARKは実際に採番される形をしている():
    """**読者は例からその形を覚える。** 採番されない形を見せると、桁数も文字集合も
    間違って伝わり、「配られる名前はこの長さか」と思われる。

    見るのは 2 つ——**betanumeric だけでできていること**（母音と `l` は入らない）と、
    **検査桁が合うこと**。どちらも `arkspec` が実際に課している規則なので、
    例が実装から離れれば必ずここで落ちる。
    """
    from arkhe.arkspec.betanumeric import BETANUMERIC, verify_ark_check_digit

    bad = []
    for page, lineno, name in _example_arks():
        if name in DELIBERATELY_WRONG:
            continue
        if outside := set(name) - set(BETANUMERIC):
            bad.append(f"{page}:{lineno} ark:99999/{name} — betanumeric に無い文字 "
                       f"{sorted(outside)}")
        elif not verify_ark_check_digit(EXAMPLE_NAAN, name):
            bad.append(f"{page}:{lineno} ark:99999/{name} — 検査桁が合わない")
    assert not bad, "採番されない形の例:\n  " + "\n  ".join(bad)


def test_わざと合わない例は本当に合わない():
    """**許可した例が腐るのを止める。** 名前を書き換えたのに `DELIBERATELY_WRONG` を
    直し忘れると、上の検査に穴が開いたまま気づけない。だから**合わないことを確かめ、
    文書にまだ在ることも確かめる**。
    """
    from arkhe.arkspec.betanumeric import verify_ark_check_digit

    for name, why in DELIBERATELY_WRONG.items():
        assert not verify_ark_check_digit(EXAMPLE_NAAN, name), f"{name} は合ってしまう（{why}）"

    used = {name for _, _, name in _example_arks()}
    assert not (set(DELIBERATELY_WRONG) - used), \
        f"文書に無い例が許可されたまま: {sorted(set(DELIBERATELY_WRONG) - used)}"


# --------------------------------------------------------------------------
# 実装に在る口と scope が、変更履歴に出ているか
# --------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: **この検査より前から在るもの。** 散文で説明されてはいるが、綴りでは当たらない
#: ——`/api/hold` は「転送の保留」、`/ark:{rest}` は解決の経路そのもので、パスを
#: そのまま書く場所が無い。**新しく足したものをここに入れてはいけない。**
#: 書く場所が無いのではなく、まだ書いていないだけだからである。
PREDATES_THE_CHECK = {
    "/api/hold",
    "/api/hold/release",
    "/api/register",
    "/api/update/bulk",
    "/ark:{rest}",
    "/ark:/{rest}",
    "ark:update",
}


def _exposed() -> set[str]:
    """**実装が外に出している口と scope。** OpenAPI から採る。

    あれは実装から生成され、`check.sh` がコミット済みとのずれで落とすので、
    **実装に在って OpenAPI に無い口は存在しえない**。
    """
    import json

    names: set[str] = set()
    for f in ("openapi-minter.json", "openapi-resolver.json"):
        spec = json.loads((DOCS / "assets" / f).read_text(encoding="utf-8"))
        names |= set(spec.get("paths", {}))
        for scheme in spec.get("components", {}).get("securitySchemes", {}).values():
            for flow in scheme.get("flows", {}).values():
                names |= set(flow.get("scopes", {}))
    return names


def test_口とscopeは変更履歴に出ている():
    """**足したことを書き忘れるのを止める。**

    0.3.0 で `POST /api/purge` と `ark:purge` を出したのに、変更履歴の日英どちらにも
    書いていなかった。実装もテストも守りも在り、`cli.md` にも `errors.md` にも
    OpenAPI にも出るのに、**変更履歴だけが黙っていた**——差分が 58 ファイルあれば
    起きる。とくに **scope は、変更履歴に無ければ運用者が知りようがない。**

    日英の両方を見る。片方にしか無ければ、そちらの読者には無いのと同じである。
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"{n} が {log} に無い"
               for n in sorted(_exposed() - PREDATES_THE_CHECK)
               for log, text in logs.items() if n not in text]
    assert not missing, "変更履歴に出ていない:\n  " + "\n  ".join(missing)


def test_古いものとして許した口が今も在る():
    """**許可リストが腐るのを止める。** 口の名前を変えたのに `PREDATES_THE_CHECK` を
    直し忘れると、**新しい綴りが誰にも見られないまま**通ってしまう。
    """
    gone = PREDATES_THE_CHECK - _exposed()
    assert not gone, f"実装に無いものが許可されたまま: {sorted(gone)}"


def _status_test_table() -> str:
    """STATUS.md の「テストの内訳」の囲み記事。

    **STATUS.md 全体ではなく、その囲みだけを見る。** 表の別の行にファイル名が
    出ているだけで通ってしまっては、一覧を見ていることにならない。
    """
    text = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    _, _, after = text.partition("テストの内訳")
    assert after, "STATUS.md に「テストの内訳」が無い"
    parts = after.split("```")
    assert len(parts) >= 3, "「テストの内訳」の下に囲み記事が無い"
    return parts[1]


def test_テストの内訳は実在するファイルとそろっている():
    """**唯一の一覧になったものが遅れるのを止める。**

    この一覧は AGENTS.md にもあり、**そちらが 5 本ぶん遅れていた**。重複を
    やめて STATUS.md だけにしたので、ここが遅れると**もう誰も気づけない**。

    両方向を見る。**足したファイルが載っていない**のは一覧の穴だが、
    **載っているファイルが無い**のも同じくらい悪い——名前を変えたときに
    古い名前が残り、読んだ人が探しても見つからない。
    """
    listed = set(re.findall(r"test_\w+\.py", _status_test_table()))
    files = {p.name for p in (ROOT / "tests").glob("test_*.py")}
    assert not (files - listed), f"STATUS.md の内訳に無い: {sorted(files - listed)}"
    assert not (listed - files), f"内訳にあるが実在しない: {sorted(listed - files)}"


#: 変更履歴の検査より前から在る画面。**綴りでは当たらないものもある**
#: ——`/admin/callback` は OIDC の戻り先で、読む人が行く場所ではない。
#: **新しく足した画面をここに入れてはいけない。**
PAGES_PREDATING_THE_CHECK = {
    "/admin/",
    "/admin/arks",
    "/admin/audit",
    "/admin/callback",
    "/admin/client/new",
    "/admin/clients",
    "/admin/holds",
    "/admin/login",
    "/admin/manager/new",
    "/admin/mint",
    "/admin/naan/new",
    "/admin/shoulder/new",
}


def _admin_pages() -> set[str]:
    """管理画面の**ページ**。`GET` で、経路に変数を持たないものだけ。

    変数を持つもの（`/admin/arks/{ark}`）と `POST` の操作は、読む人が綴りで
    書く対象ではない——**書けないものを書けと言う検査にしない。**
    """
    from fastapi.routing import APIRoute

    from arkhe.api import admin

    return {
        r.path
        for r in admin.router.routes
        if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
    }


def test_管理画面のページは変更履歴に出ている():
    """**画面は OpenAPI に出ないので、口と scope の検査では拾えない。**

    0.5.0 で統計のページを足したとき、変更履歴の日英どちらにも書いていなかった
    ——CLI と API は書いてあったのに、**あとから足した画面だけが落ちた**。
    0.3.0 で `purge` を落としたのと同じ形である。出す前に人が気づいたが、
    **仕組みで止まったわけではない。**
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"{p} が {log} に無い"
               for p in sorted(_admin_pages() - PAGES_PREDATING_THE_CHECK)
               for log, text in logs.items() if p not in text]
    assert not missing, "変更履歴に出ていない画面:\n  " + "\n  ".join(missing)


def test_古いものとして許した画面が今も在る():
    """**許可リストが腐るのを止める。** 経路を変えて直し忘れると、新しい綴りが
    誰にも見られないまま通ってしまう。
    """
    gone = PAGES_PREDATING_THE_CHECK - _admin_pages()
    assert not gone, f"実装に無い画面が許可されたまま: {sorted(gone)}"


#: 変更履歴に綴りが出ていないコマンド。**いまは空である**——検査を入れた時点では
#: 13 件あったが、それぞれが入った版の節に遡って埋めた。
#:
#: **空のまま保つ。** ここに足したくなったら、足すのではなく変更履歴を書く。
COMMANDS_PREDATING_THE_CHECK: set[str] = set()


def test_運用コマンドは変更履歴に出ている():
    """**参照ページは縛っていたが、変更履歴は見ていなかった。**

    `cli.md` に載っているかは前から見ている——だが載っているだけでは、
    **いつ増えたのか**が読む人に伝わらない。`arkhe stat` はたまたま書けていた
    が、仕組みで止まっていたわけではない。
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"arkhe {c} が {log} に無い"
               for c in _commands(cli.app)
               if c not in COMMANDS_PREDATING_THE_CHECK
               for log, text in logs.items() if f"arkhe {c}" not in text]
    assert not missing, "変更履歴に出ていないコマンド:\n  " + "\n  ".join(missing)


def test_古いものとして許したコマンドが今も在る():
    """**許可リストが腐るのを止める。** 名前を変えて直し忘れると、新しい綴りが
    誰にも見られないまま通ってしまう。
    """
    gone = COMMANDS_PREDATING_THE_CHECK - set(_commands(cli.app))
    assert not gone, f"実装に無いコマンドが許可されたまま: {sorted(gone)}"


# --------------------------------------------------------------------------
# STATUS.md が主張する「今の値」が、実際の値と合っているか
# --------------------------------------------------------------------------


def test_STATUSの版はpyprojectと一致する():
    """**リリースで動く数字を、リリースの手が触らなければ必ずずれる。**

    実際 0.1.0 と 0.2.0 のあいだ触られず、「版 0.0.9」のまま 2 版ぶん据え置きに
    なっていた。手順（AGENTS.md）に入れたが、**手順は守られないことがある**。
    """
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    want = version["project"]["version"]
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert f"**{want}**" in status, f"STATUS.md が {want} を版として書いていない"


def test_STATUSの移行headは実際のheadと一致する():
    """**`alembic check` はスキーマと模型を見るが、文書は見ない。**

    実際にずれていた——0.4.0 の移行を足したあと、STATUS.md は 0.3.0 の head を
    指したままだった。**機械で読める値なので、読んで確かめる。**
    """
    import re

    # **注釈の書き方が揃っていない**（`str | … | None` と `Union[str, …]`、
    # 引用符も両方ある）。型ではなく**代入されている文字列**だけを見る。
    revisions, downs = set(), set()
    for f in (ROOT / "alembic" / "versions").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if m := re.search(r'^revision\b[^=]*=\s*["\']([^"\']+)["\']', text, re.M):
            revisions.add(m.group(1))
        if m := re.search(r'^down_revision\b[^=]*=\s*["\']([^"\']+)["\']', text, re.M):
            downs.add(m.group(1))
    heads = revisions - downs
    assert len(heads) == 1, f"head が単一でない: {sorted(heads)}"
    head = heads.pop()
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert head in status, f"STATUS.md が今の head（{head}）を書いていない"
