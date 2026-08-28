"""モデルの不変条件。**規約を人に守らせるのではなく、構造で不可能にする。**"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from arkhe.db.models import Ark, Naan, NotDeletable
from arkhe.domain import minting


def test_NR_ARKは削除できない(db, world):
    """行を消すと解決が止まる＝**識別子が壊れる**。tombstone に付け替えるか
    url を空にする。"""
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(NotDeletable):
        db.delete(ark)
        db.flush()


def test_NR_shoulderは削除できない(db, world):
    """乱数割当が同じ文字列を再び当てうる＝**NR 違反の芽**。"""
    with pytest.raises(NotDeletable):
        db.delete(world["sh_a"])
        db.flush()


def test_E1_同じARKを二度作れない(db, world):
    """**arklet で最重大の欠陥**——主キー衝突が UPDATE に化け、既存 ARK の
    向き先を黙って書き換えていた。"""
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    db.add(
        Ark(
            ark=ark.ark, naan="99999", shoulder_id=world["sh_a"].id,
            assigned_name=ark.assigned_name,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_D3_権威を持つなら転送先を持てない(db):
    db.add(Naan(naan="70000", name="bad", is_authoritative=True, redirect="https://x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_D3_権威を持たないなら転送先が要る(db):
    db.add(Naan(naan="70001", name="bad", is_authoritative=False, redirect=""))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_N2_NAANは文字列として扱う(db, root):
    """`099999` と `99999` は**別の NAAN**。整数化してはならない。"""
    from arkhe.domain import admin_ops as ops

    ops.create_naan(db, root, naan="99999", name="a")
    ops.create_naan(db, root, naan="099999", name="b")
    db.commit()
    assert db.get(Naan, "99999").name == "a"
    assert db.get(Naan, "099999").name == "b"


def test_採番は衝突しても採り直す(db, world):
    """衝突回数を返すのは、名前空間の枯渇が静かに進むのを検知できるようにするため。"""
    arks = [minting.mint(db, shoulder=world["sh_a"], created_by="t") for _ in range(20)]
    db.commit()
    assert len({a.ark for a, _ in arks}) == 20
    assert all(c == 0 for _, c in arks)  # 8 桁なら 20 本で衝突しない


def test_B4_修飾子はbaseの名前空間の内側にしか生えない(db, world):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    child = minting.register_qualified(db, base=base, qualifier="/page/1", created_by="t")
    db.commit()
    assert child.shoulder_id == base.shoulder_id
    assert child.assigned_name.startswith(base.assigned_name)


def test_B4_既に在る修飾子は上書きしない(db, world):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    minting.register_qualified(db, base=base, qualifier="/p", created_by="t")
    db.commit()
    with pytest.raises(minting.AlreadyRegistered):
        minting.register_qualified(db, base=base, qualifier="/p", created_by="t")


@pytest.mark.parametrize("bad", ["page", "-x", ""])
def test_B4_修飾子は区切り文字で始める(db, world, bad):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(ValueError):
        minting.register_qualified(db, base=base, qualifier=bad, created_by="t")


def test_ER図が実装と食い違わない():
    """**図は放っておくと古くなる。** 表と主要な列が図に出ているかを見る。

    全列の一致までは求めない（図は要点を選ぶもの）。ただし**表を足したのに図に
    書かなかった**、**列を消したのに図に残っている**は検出する。
    """
    import re
    from pathlib import Path

    from arkhe.db.models import Base

    doc = Path(__file__).resolve().parents[1] / "docs" / "reference" / "data-model.ja.md"
    text = doc.read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text, re.S).group(1)

    for name, table in Base.metadata.tables.items():
        assert name.upper() in block, f"{name} が ER 図に無い"
        drawn = set(re.findall(rf"{name.upper()} \{{(.*?)\n    \}}", block, re.S))
        if not drawn:
            continue
        lines = next(iter(drawn)).strip().splitlines()
        cols = {ln.split()[1] for ln in lines if len(ln.split()) > 1}
        real = set(table.columns.keys())
        # 図にあるのに実装に無い列は、消し忘れか綴り違い（title は what_title と表記）
        stale = {c for c in cols if c not in real and c not in {"what_title"}}
        assert not stale, f"{name}: 図にあるが実装に無い列 {sorted(stale)}"


def test_版は一か所からしか来ない():
    """**版を 2 か所に書くと、必ずどちらかが古くなる。**

    `pyproject.toml` を唯一の出どころとし、パッケージも OpenAPI もそこから読む。
    """
    import tomllib
    from pathlib import Path

    import arkhe

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert arkhe.__version__ == declared

    # **版を代入している箇所がほかに無いこと。**
    # 素の文字列検索だと `127.0.0.1` の中の `0.0.1` に当たるので、
    # 「version= に版のリテラルを渡している」形だけを見る。
    import re

    pattern = re.compile(rf'version\s*=\s*["\']{re.escape(declared)}["\']')
    hits = [
        str(f.relative_to(root))
        for f in (root / "src").rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert not hits, f"版が直書きされている: {hits}"


def test_変更履歴が日英で揃っている():
    """**片方だけ更新するのを防ぐ。**

    版の見出しが両方に同じだけあることを見る。文面の一致までは求めない
    （訳は訳であって写しではない）。
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def versions(name: str) -> list[str]:
        text = (root / name).read_text(encoding="utf-8")
        return re.findall(r"^## \[([^\]]+)\]", text, re.M)

    en, ja = versions("CHANGELOG.md"), versions("CHANGELOG.ja.md")
    # 「未リリース」の見出しだけ語が違うので、そこを揃えてから比べる
    norm = {"Unreleased": "-", "未リリース": "-"}
    assert [norm.get(v, v) for v in en] == [norm.get(v, v) for v in ja], (en, ja)

    import tomllib

    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert declared in en, f"{declared} の項が変更履歴に無い"
