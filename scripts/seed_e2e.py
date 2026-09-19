#!/usr/bin/env python3
"""通しの検査のための台帳を作る。**`tests/e2e/` と、手で確かめるときの共通の土台。**

    uv run python scripts/seed_e2e.py                 # 組んで、鍵を人が読む形で出す
    uv run python scripts/seed_e2e.py --json          # 同じものを機械が読む形で
    uv run python scripts/seed_e2e.py --arks 500      # 状態の混ざった ARK を足す
    uv run python scripts/seed_e2e.py --migrate       # 先に alembic upgrade head も

**`tests/e2e/` はこれを呼ぶ。** 検査の側に同じ組み立てを書くと、片方が必ず古くなる
——そして**呼ばれているから、腐らない**。手で確かめるときも同じ台帳から始められる。

## 何を組むか

  NAAN 99999      権威を持つ。ここに 3 つの組織を迎える
  NAAN 88888      **解決を外へ委ねた**。台帳に行は無く、解決は委譲先へ飛ぶ
  組織 a          名前空間 `/e1`。**上限なし**——ここに ARK を足す
  組織 b          `/b2`。**届かないこと**を確かめるための別組織
  組織 q          `/q1`、**1 日 1 本**。上限に当たることを確かめるためだけの組織

主体は**用途ごとに分ける**。1 つを使い回すと、止める検査が後続を巻き添えにする:

  ops / mint_only / other / quota / stop … API 鍵（`arkhe_…`）
  secret                                … client_secret（`arkhes_…`）
  admin                                 … 人。合言葉で管理画面に入る

## 足す ARK の状態

`--arks N` は **N 本を組織 a に**入れ、公開・公開前・保留・墓碑・修飾子つき・
取り下げ済みの名前を混ぜる。**組織 q には 1 本も入れない**——あそこは 1 日 1 本が
上限で、種を蒔いた時点で検査が上限に当たってしまう。

## 気をつけること

**既に台帳があるなら何もしない。** `--force` を付けたときだけ足す。**この道具は
検査のためのもの**で、実運用の台帳は `arkhe naan add` / `arkhe onboard` で組む。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NAAN = "99999"
#: 採番も解決も外に委ねた NAAN。**台帳に行は無い。**
DELEGATED_NAAN = "88888"
DELEGATE = "https://delegate.example.org"

#: **組織と名前空間は同じ鍵で引く。** a が主役、b は「届かないこと」を確かめる別組織、
#: q は上限に当たることだけのための組織。
ORGS = {"a": "E2E org", "b": "E2E 別組織", "q": "E2E 上限組織"}
SHOULDERS = {"a": "/e1", "b": "/b2", "q": "/q1"}

ADMIN_USER = "e2e-person"
#: **検査用の合言葉。** 本番に持ち込まない（この文字列はリポジトリに在る）。
ADMIN_PASSWORD = "correct horse battery staple"

ALL_SCOPES = (
    "ark:mint ark:update ark:read ark:tombstone ark:hold ark:import "
    "ark:delete ark:unpublish ark:purge"
)

#: (鍵の名, client_id, 組織, scope, 種類)
CLIENTS = [
    ("ops", "e2e-ops", "a", ALL_SCOPES, "api_key"),
    ("mint_only", "e2e-mint-only", "a", "ark:mint", "api_key"),
    ("other", "e2e-other", "b", "ark:mint ark:update ark:read", "api_key"),
    ("quota", "e2e-quota", "q", "ark:mint", "api_key"),
    ("stop", "e2e-stop", "a", "ark:mint ark:read", "api_key"),
    ("secret", "e2e-secret", "a", "ark:mint ark:read", "client_secret"),
]


def _sow(session, arks: int) -> dict[str, int]:
    """状態の混ざった ARK を、組織 a の名前空間に入れる。

    **画面と統計は「状態が混ざっている」ことでしか確かめられない。** 全部が
    公開済みの台帳では、保留の行がどう出るかも、公開前が `?info` に出ないことも、
    見て確かめられない。
    """
    from sqlalchemy import select

    from arkhe.auth.principal import Principal
    from arkhe.db.models import Authority, Shoulder
    from arkhe.domain import admin_ops as ops
    from arkhe.domain import minting

    root = Principal(client_id="seed-e2e", naan="", authority=Authority.SYSTEM)
    shoulder = session.scalar(
        select(Shoulder).where(
            Shoulder.naan == NAAN, Shoulder.shoulder == SHOULDERS["a"]
        )
    )
    tally = {"published": 0, "reserved": 0, "held": 0, "tombstoned": 0,
             "qualified": 0, "withdrawn": 0}
    minted = []
    for i in range(arks):
        # 10 本に 1 本は公開前。**解決せず、まだ消せる**状態のものを混ぜておく。
        reserve = i % 10 == 9
        ark, _ = minting.mint(
            session, shoulder=shoulder, created_by="seed-e2e", reserve=reserve,
            url=f"https://repo.example.ac.jp/records/{i}",
            title=f"検査用のデータセット {i + 1}",
        )
        minted.append(ark)
        tally["reserved" if reserve else "published"] += 1
    session.flush()

    public = [a for a in minted if a.published_at is not None]
    if public:
        # 保留（転送だけ止まる）・墓碑（行き先だけ消える）・修飾子つき
        ops.set_hold(
            session, root, kind="ark", key=public[0].ark,
            until=datetime.now(UTC) + timedelta(days=7), reason="検査用に止めてある",
        )
        tally["held"] = 1
        if len(public) > 1:
            public[1].url = ""
            public[1].updated_by = "seed-e2e"
            tally["tombstoned"] = 1
        if len(public) > 2:
            minting.register_qualified(
                session, base=public[2], qualifier="/part1", created_by="seed-e2e",
                url="https://repo.example.ac.jp/records/part",
            )
            tally["qualified"] = 1
    reserved = [a for a in minted if a.published_at is None]
    if reserved:
        # **公開前に取り下げた名前。** 二度と採られないことを、実物で確かめられる。
        ops.withdraw_ark(session, root, ark=reserved[0].ark, reason="検査用に取り下げた")
        tally["reserved"] -= 1
        tally["withdrawn"] = 1
    session.commit()
    return tally


def _cli(env: dict[str, str], *args: str) -> str:
    """**組み立ては CLI を通す。** 運用者が実際に使う道であり、ここを通したから
    「組織に結び付けない主体は採番できない」（ARKHE-1303）に気づけた。"""
    p = subprocess.run(
        ["uv", "run", "arkhe", *args], cwd=ROOT, env={**os.environ, **env},
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise SystemExit(f"arkhe {' '.join(args)} が落ちた\n{p.stdout}\n{p.stderr}")
    return p.stdout


def build(*, arks: int = 0, migrate: bool = False, force: bool = False) -> dict:
    from sqlalchemy import select

    from arkhe.db.models import Client, Manager, Naan
    from arkhe.db.session import session_factory

    env = {"ARKHE_AUTH": "apikey", "ARKHE_RESOLVER": "0"}
    if migrate:
        p = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT,
                           env={**os.environ, **env}, capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"alembic upgrade head が落ちた\n{p.stderr}")

    with session_factory()() as s:
        if s.scalar(select(Naan).limit(1)) is not None and not force:
            raise SystemExit(
                "台帳に既に NAAN がある。**何もしない**"
                "（足すなら --force。検査用の台帳は捨てて作り直すのが安い）"
            )
        # **途中まで在る台帳にも足せるようにする。** 検査は落ちる途中で終わるので、
        # 「NAAN だけ在って組織が無い」はふつうに起きる——そこで止まると、
        # 作り直すしか手が無くなる。
        have_naans = set(s.scalars(select(Naan.naan)))
        have_orgs = set(s.scalars(select(Manager.name)))
        have_clients = set(s.scalars(select(Client.client_id)))

    if NAAN not in have_naans:
        _cli(env, "naan", "add", NAAN, "E2E RA", "--policy", "NP | NR, OP, CC | 2026")
    if DELEGATED_NAAN not in have_naans:
        _cli(env, "naan", "add", DELEGATED_NAAN, "E2E 委譲先",
             "--no-authoritative", "--redirect", DELEGATE)

    for tag, name in ORGS.items():
        if name in have_orgs:
            continue
        quota = ["--quota", "1"] if tag == "q" else []
        _cli(env, "onboard", NAAN, name, "-s", SHOULDERS[tag], *quota)

    # id は `manager list` の 1 列目——CLI が「ids are input to other commands」と
    # 言っているとおりに読む。
    listing = _cli(env, "manager", "list")
    managers = {}
    for line in listing.splitlines():
        for tag, name in ORGS.items():
            if line.rstrip().endswith(name):
                managers[tag] = line.split()[0]
    if set(managers) != set(ORGS):
        raise SystemExit(f"組織の id を読めない:\n{listing}")

    keys = {}
    for tag, client_id, org, scopes, kind in CLIENTS:
        if client_id not in have_clients:
            _cli(env, "client", "add", client_id, NAAN,
                 "--manager", managers[org], "--scopes", scopes)
        # **鍵は刷った 1 度しか出ない。** 1 行目がその平文。既に主体が在るときも
        # 刷り直す——**古い鍵は失効させない**（並行させて切り替えるため）。
        keys[tag] = _cli(env, "client", "key", client_id, "--kind", kind).splitlines()[0]

    if ADMIN_USER not in have_clients:
        _cli(env, "client", "add", ADMIN_USER, NAAN, "--person",
             "--authority", "naan", "--scopes", ALL_SCOPES)
    _cli(env, "client", "passwd", ADMIN_USER, "--password", ADMIN_PASSWORD)

    tally = {}
    if arks:
        with session_factory()() as s:
            tally = _sow(s, arks)

    return {
        "naan": NAAN,
        "delegated_naan": DELEGATED_NAAN,
        "delegate": DELEGATE,
        "shoulders": SHOULDERS,
        "managers": managers,
        "clients": {tag: cid for tag, cid, *_ in CLIENTS},
        "keys": keys,
        "admin": {"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        "arks": tally,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arks", type=int, default=0, help="足す ARK の本数（状態を混ぜる）")
    ap.add_argument("--migrate", action="store_true", help="先に alembic upgrade head")
    ap.add_argument("--force", action="store_true", help="台帳に既に NAAN があっても足す")
    ap.add_argument("--json", action="store_true", help="機械が読む形で出す")
    args = ap.parse_args()

    out = build(arks=args.arks, migrate=args.migrate, force=args.force)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return

    print(f"NAAN {out['naan']}（委譲先 {out['delegated_naan']} → {out['delegate']}）")
    for tag, shoulder in out["shoulders"].items():
        print(f"  {out['naan']}{shoulder:<4} 組織 id {out['managers'][tag]:<3} {ORGS[tag]}")
    print("\n鍵（**この一度しか出ない**）:")
    for tag, key in out["keys"].items():
        print(f"  {tag:<10} {out['clients'][tag]:<14} {key}")
    print(f"\n管理画面: {out['admin']['username']} / {out['admin']['password']}")
    print("  ARKHE_ADMIN_LOGIN=password ＋ ARKHE_SESSION_SECRET が要る")
    if out["arks"]:
        print("\n入れた ARK: " + ", ".join(f"{k} {v}" for k, v in out["arks"].items()))


if __name__ == "__main__":  # pragma: no cover
    main()
