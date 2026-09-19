#!/usr/bin/env python3
"""Build the ledger the end-to-end suite runs against, and that you can use by hand.

    uv run python scripts/seed_e2e.py                 # build it and print the keys
    uv run python scripts/seed_e2e.py --json          # the same, for a program to read
    uv run python scripts/seed_e2e.py --arks 500      # add ARKs in mixed states
    uv run python scripts/seed_e2e.py --migrate       # run alembic upgrade head first

tests/e2e/ calls this script. Writing the same setup inside the suite would leave one of
the two copies stale, and because the suite calls it, this script cannot rot either.
Checking by hand starts from the same ledger.

What it builds

  NAAN 99999      authoritative. Three organisations are onboarded under it
  NAAN 88888      resolution is delegated. No rows here; resolution is forwarded
  organisation a  namespace /e1, no quota. Seeded ARKs go here
  organisation b  namespace /b2, used to check that reach stops at the organisation
  organisation q  namespace /q1, one ARK a day, used to check the quota

Each principal has one purpose. Sharing one would let the check that disables a
principal break the checks that run after it.

  ops / mint_only / other / quota / stop   API keys (arkhe_...)
  secret                                   a client secret (arkhes_...)
  admin                                    a person, who signs in with a password

Seeded ARKs

--arks N adds N ARKs to organisation a, mixing published, reserved, held, tombstoned,
qualified and withdrawn names. Nothing is added to organisation q: it is capped at one
ARK a day, so seeding it would use up the quota the suite wants to test.

Notes

If the ledger already holds a NAAN, the script does nothing unless --force is given.
This is a tool for testing; a real ledger is built with `arkhe naan add` and
`arkhe onboard`.
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
#: A NAAN whose minting and resolution are delegated. No rows are held for it.
DELEGATED_NAAN = "88888"
DELEGATE = "https://delegate.example.org"

#: Organisations and namespaces share one key. "a" is the main one, "b" is there to
#: check that reach stops at the organisation, "q" only exists for the quota.
ORGS = {"a": "E2E org", "b": "E2E other org", "q": "E2E capped org"}
SHOULDERS = {"a": "/e1", "b": "/b2", "q": "/q1"}

ADMIN_USER = "e2e-person"
#: A password for testing. Do not use it anywhere real: it is in the repository.
ADMIN_PASSWORD = "correct horse battery staple"

ALL_SCOPES = (
    "ark:mint ark:update ark:read ark:tombstone ark:hold ark:import "
    "ark:delete ark:unpublish ark:purge"
)

#: (name of the key, client_id, organisation, scopes, kind of credential)
CLIENTS = [
    ("ops", "e2e-ops", "a", ALL_SCOPES, "api_key"),
    ("mint_only", "e2e-mint-only", "a", "ark:mint", "api_key"),
    ("other", "e2e-other", "b", "ark:mint ark:update ark:read", "api_key"),
    ("quota", "e2e-quota", "q", "ark:mint", "api_key"),
    ("stop", "e2e-stop", "a", "ark:mint ark:read", "api_key"),
    ("secret", "e2e-secret", "a", "ark:mint ark:read", "client_secret"),
]


def _sow(session, arks: int) -> dict[str, int]:
    """Add ARKs in mixed states to organisation a.

    The screens and the statistics can only be checked against a ledger where the states
    differ. If everything is published, there is no held row to look at, and no way to
    see that a reserved ARK stays out of ?info.
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
        # Every tenth ARK is reserved: it does not resolve and can still be deleted.
        reserve = i % 10 == 9
        ark, _ = minting.mint(
            session, shoulder=shoulder, created_by="seed-e2e", reserve=reserve,
            url=f"https://repo.example.ac.jp/records/{i}",
            title=f"Test dataset {i + 1}",
        )
        minted.append(ark)
        tally["reserved" if reserve else "published"] += 1
    session.flush()

    public = [a for a in minted if a.published_at is not None]
    if public:
        # A hold stops redirection only; a tombstone drops the target; a qualifier is
        # registered on its own.
        ops.set_hold(
            session, root, kind="ark", key=public[0].ark,
            until=datetime.now(UTC) + timedelta(days=7), reason="held for testing",
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
        # A name withdrawn before publication, so that "never assigned again" can be
        # checked against a real row.
        ops.withdraw_ark(session, root, ark=reserved[0].ark, reason="withdrawn for testing")
        tally["reserved"] -= 1
        tally["withdrawn"] = 1
    session.commit()
    return tally


def _cli(env: dict[str, str], *args: str) -> str:
    """Run an arkhe command.

    The setup goes through the CLI because that is the path operators use. Going through
    it is how ARKHE-1303 (a principal with no organisation cannot mint) was found.
    """
    p = subprocess.run(
        ["uv", "run", "arkhe", *args], cwd=ROOT, env={**os.environ, **env},
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise SystemExit(f"arkhe {' '.join(args)} failed\n{p.stdout}\n{p.stderr}")
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
            raise SystemExit(f"alembic upgrade head failed\n{p.stderr}")

    with session_factory()() as s:
        if s.scalar(select(Naan).limit(1)) is not None and not force:
            raise SystemExit(
                "the ledger already holds a NAAN, so nothing was done. "
                "Pass --force to add to it; a test ledger is cheaper to recreate."
            )
        # Allow topping up a half-built ledger. A suite that fails stops halfway, so
        # "the NAAN exists but no organisation does" is an ordinary state to be in.
        have_naans = set(s.scalars(select(Naan.naan)))
        have_orgs = set(s.scalars(select(Manager.name)))
        have_clients = set(s.scalars(select(Client.client_id)))

    if NAAN not in have_naans:
        _cli(env, "naan", "add", NAAN, "E2E RA", "--policy", "NP | NR, OP, CC | 2026")
    if DELEGATED_NAAN not in have_naans:
        _cli(env, "naan", "add", DELEGATED_NAAN, "E2E delegate",
             "--no-authoritative", "--redirect", DELEGATE)

    for tag, name in ORGS.items():
        if name in have_orgs:
            continue
        quota = ["--quota", "1"] if tag == "q" else []
        _cli(env, "onboard", NAAN, name, "-s", SHOULDERS[tag], *quota)

    # The id is the first column of `manager list`, as that command says.
    listing = _cli(env, "manager", "list")
    managers = {}
    for line in listing.splitlines():
        for tag, name in ORGS.items():
            if line.rstrip().endswith(name):
                managers[tag] = line.split()[0]
    if set(managers) != set(ORGS):
        raise SystemExit(f"could not read the organisation ids:\n{listing}")

    keys = {}
    for tag, client_id, org, scopes, kind in CLIENTS:
        if client_id not in have_clients:
            _cli(env, "client", "add", client_id, NAAN,
                 "--manager", managers[org], "--scopes", scopes)
        # A credential is shown once, on the first line. Issue a new one even when the
        # principal already exists; older credentials are not revoked.
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
    ap.add_argument("--arks", type=int, default=0,
                    help="how many ARKs to add, in mixed states")
    ap.add_argument("--migrate", action="store_true", help="run alembic upgrade head first")
    ap.add_argument("--force", action="store_true",
                    help="add to a ledger that already holds a NAAN")
    ap.add_argument("--json", action="store_true", help="print it for a program to read")
    args = ap.parse_args()

    out = build(arks=args.arks, migrate=args.migrate, force=args.force)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return

    print(f"NAAN {out['naan']} (delegate {out['delegated_naan']} -> {out['delegate']})")
    for tag, shoulder in out["shoulders"].items():
        print(f"  {out['naan']}{shoulder:<4} organisation id {out['managers'][tag]:<3} "
              f"{ORGS[tag]}")
    print("\nCredentials (shown once):")
    for tag, key in out["keys"].items():
        print(f"  {tag:<10} {out['clients'][tag]:<14} {key}")
    print(f"\nAdmin interface: {out['admin']['username']} / {out['admin']['password']}")
    print("  needs ARKHE_ADMIN_LOGIN=password and ARKHE_SESSION_SECRET")
    if out["arks"]:
        print("\nARKs added: " + ", ".join(f"{k} {v}" for k, v in out["arks"].items()))


if __name__ == "__main__":  # pragma: no cover
    main()
