"""体験用の台帳を用意する。**冪等**（既にあれば何もしない）。

`compose/oidc` の起動時に一度だけ走る。実運用では使わない——本番の台帳は
`arkhe naan add` / `arkhe onboard` / `arkhe client add` で組む。
"""

from __future__ import annotations

import os

from sqlalchemy import select

from arkhe.auth.principal import Principal
from arkhe.db.models import Authority, Client, Naan
from arkhe.db.session import session_factory
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting

#: Keycloak の realm に入れてある利用者と、arkhe 側で与える到達範囲。
#: **`client_id` は認可サーバが返す `preferred_username` と一致させる。**
PEOPLE = [
    ("ops", Authority.SYSTEM, None, "運用者（全 NAAN）"),
    ("naan-admin", Authority.NAAN, None, "NAAN 管理者（99999 配下）"),
    ("nibb", Authority.MANAGER, "基礎生物学研究所", "組織管理者"),
]

INSTITUTIONS = [
    ("99999", "基礎生物学研究所", "/x9", 12),
    ("99999", "分子科学研究所", "/y2", 7),
    ("99999", "生理学研究所", "/w4", 3),
    ("27932", "北海道大学", "/b7", 21),
    ("27932", "九州大学", "/k5", 5),
]


def main() -> None:
    root = Principal(client_id="seed", naan="", authority=Authority.SYSTEM)
    factory = session_factory()
    with factory() as s:
        if s.scalar(select(Naan).limit(1)) is not None:
            print("台帳は用意済みです（何もしません）")
            return

        ops.create_naan(
            s, root, naan="99999", name="国立情報学研究所（試験 NAAN）",
            na_policy="NP | NR, OP, CC | 2026 | https://arkhe.example.org/policy",
        )
        ops.create_naan(s, root, naan="27932", name="JAIRO Cloud")
        ops.create_naan(
            s, root, naan="12345", name="旧システム（委譲）",
            is_authoritative=False, redirect="https://legacy.example.org",
        )
        s.flush()

        managers: dict[str, int] = {}
        for naan, inst, sh, n in INSTITUTIONS:
            m, shd = ops.onboard_manager(
                s, root, naan=naan, name=inst, shoulder=sh,
                quota_per_day=1000 if n > 10 else None,
            )
            s.flush()
            managers[inst] = m.id
            for i in range(n):
                minting.mint(
                    s, shoulder=shd, created_by="seed",
                    url=f"https://repo.example.ac.jp/records/{i}",
                    title=f"{inst} のデータセット {i + 1}",
                )

        # shoulder の 4 状態を揃える（画面で状態の違いが見えるように）
        d = ops.add_shoulder(s, root, naan="99999", shoulder="/z1")
        s.flush()
        ops.set_shoulder_status(
            s, root, shoulder_id=d.id, status="delegated",
            minter="https://mint.partner.example.org", note="外部 minter に委譲",
        )
        r = ops.add_shoulder(s, root, naan="27932", shoulder="/r0")
        s.flush()
        ops.set_shoulder_status(s, root, shoulder_id=r.id, status="retired", note="移行完了")
        ops.add_shoulder(
            s, root, naan="99999", shoulder="/q0", status="reserved", note="将来用に確保"
        )

        # 機械の主体（API から採番するもの）
        for cid, naan, inst, scopes, label in [
            ("nibb-invenio", "99999", "基礎生物学研究所", "ark:mint ark:update", "InvenioRDM"),
            ("hokudai-weko", "27932", "北海道大学", "ark:mint ark:update", "WEKO"),
        ]:
            c = ops.register_client(
                s, root, client_id=cid, naan=naan, manager_id=managers[inst],
                scopes=scopes, label=label,
            )
            s.flush()
            ops.issue_credential(s, root, client_pk=c.id)

        # 人の主体（Keycloak の利用者に対応する）
        for username, authority, inst, label in PEOPLE:
            if s.scalar(select(Client).where(Client.client_id == username)):
                continue
            ops.register_client(
                s, root, client_id=username, naan="99999",
                manager_id=managers[inst] if inst else None,
                authority=authority.value, subject_type="person", label=label,
                scopes="ark:mint ark:update ark:read ark:tombstone",
                expires_at=None if authority is not Authority.NAAN else _far_future(),
            )
        s.commit()
        print("体験用の台帳を用意しました")
        print("  Keycloak の利用者:", ", ".join(u for u, *_ in PEOPLE))


def _far_future():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(days=3650)


if __name__ == "__main__":  # pragma: no cover
    if os.environ.get("ARKHE_SKIP_SEED"):
        print("種蒔きを飛ばします（ARKHE_SKIP_SEED）")
    else:
        main()
