"""Build a ledger to try things out. It is idempotent: with one already there, it does
nothing.

It runs once when compose/oidc starts. It is not for production, where a ledger is built
with arkhe naan add, arkhe onboard and arkhe client add.

Nothing real appears here

The institution names and the NAANs are all invented. Putting a real name in the demo
ledger reads as though that institution uses arkhe, and a screenshot or a recording
would make it look settled, whatever was intended.

The same goes for NAANs: none that are assigned. 99999 is reserved by the specification
for testing, and 12345 and 54321 are values for examples.
"""

from __future__ import annotations

import os

from sqlalchemy import select

from arkhe.auth.principal import Principal
from arkhe.db.models import Authority, Client, Naan
from arkhe.db.session import session_factory
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting

#: The users in the Keycloak realm, and the reach arkhe gives them. The client_id has
#: to match the preferred_username the authorisation server returns.
PEOPLE = [
    ("ops", Authority.SYSTEM, None, "operator, every NAAN"),
    ("naan-admin", Authority.NAAN, None, "NAAN administrator, under 99999"),
    ("org-admin", Authority.MANAGER, "Example University", "organisation administrator"),
]

INSTITUTIONS = [
    ("99999", "Example University", "/x9", 12),
    ("99999", "Example Research Institute", "/y2", 7),
    ("99999", "Example Institute of Technology", "/w4", 3),
    ("12345", "Example Medical University", "/b7", 21),
    ("12345", "Example College", "/k5", 5),
]


def main() -> None:
    root = Principal(client_id="seed", naan="", authority=Authority.SYSTEM)
    factory = session_factory()
    with factory() as s:
        if s.scalar(select(Naan).limit(1)) is not None:
            print("the ledger is already there; nothing to do")
            return

        ops.create_naan(
            s, root, naan="99999", name="Example RA (99999, reserved for testing)",
            na_policy="NP | NR, OP, CC | 2026 | https://arkhe.example.org/policy",
        )
        ops.create_naan(s, root, naan="12345", name="Another example RA")
        ops.create_naan(
            s, root, naan="54321", name="A legacy system, delegated",
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
                    title=f"Dataset {i + 1} of {inst}",
                )
            # Mix in one reserved ARK. How an ARK that does not resolve yet looks on
            # the screen cannot be checked without a real one.
            minting.mint(
                s, shoulder=shd, created_by="seed", reserve=True,
                url=f"https://repo.example.ac.jp/records/draft-{len(managers)}",
                title=f"Unpublished dataset of {inst}",
            )

        # One shoulder in each of the four states, so the screens show the difference
        d = ops.add_shoulder(s, root, naan="99999", shoulder="/z1")
        s.flush()
        ops.set_shoulder_status(
            s, root, shoulder_id=d.id, status="delegated",
            minter="https://mint.partner.example.org", note="delegated to an outside minter",
        )
        r = ops.add_shoulder(s, root, naan="12345", shoulder="/r0")
        s.flush()
        ops.set_shoulder_status(
            s, root, shoulder_id=r.id, status="retired", note="migration finished"
        )
        ops.add_shoulder(
            s, root, naan="99999", shoulder="/q0", status="reserved", note="held for later"
        )

        # Machine principals, which mint through the API
        for cid, naan, inst, scopes, label in [
            ("example-invenio", "99999", "Example University",
             "ark:mint ark:update", "InvenioRDM"),
            ("example-weko", "12345", "Example Medical University",
             "ark:mint ark:update", "WEKO"),
        ]:
            c = ops.register_client(
                s, root, client_id=cid, naan=naan, manager_id=managers[inst],
                scopes=scopes, label=label,
            )
            s.flush()
            ops.issue_credential(s, root, client_pk=c.id)

        # People, matching the users in Keycloak
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
        print("the demonstration ledger is ready")
        print("  Keycloak users:", ", ".join(u for u, *_ in PEOPLE))


def _far_future():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(days=3650)


if __name__ == "__main__":  # pragma: no cover
    if os.environ.get("ARKHE_SKIP_SEED"):
        print("skipping the seed (ARKHE_SKIP_SEED)")
    else:
        main()
