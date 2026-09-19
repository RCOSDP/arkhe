"""The operator commands. They call the same domain.admin_ops as the screens.

Nothing can be done only from the CLI, and nothing only from a screen. Either entrance
goes through the same invariants and leaves the same record in the audit log.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import select

from arkhe.arkspec.naming import compact_ark
from arkhe.auth.principal import Principal
from arkhe.cli_i18n import t
from arkhe.db.models import (
    Ark,
    Authority,
    Client,
    CommitmentLevel,
    CredentialKind,
    Manager,
    Naan,
    Shoulder,
)
from arkhe.db.session import session_factory
from arkhe.domain import admin_ops as ops
from arkhe.domain import stats as stats_mod
from arkhe.domain.queries import ark_key_from_input, narrow_arks, visible_arks
from arkhe.settings import get_settings

app = typer.Typer(help=t("app.help"), no_args_is_help=True)
naan_app = typer.Typer(help=t("naan.help"), no_args_is_help=True)
shoulder_app = typer.Typer(help=t("shoulder.help"), no_args_is_help=True)
manager_app = typer.Typer(help=t("manager.help"), no_args_is_help=True)
client_app = typer.Typer(help=t("client.help"), no_args_is_help=True)
ark_app = typer.Typer(help=t("ark.help"), no_args_is_help=True)
hold_app = typer.Typer(help=t("hold.help"), no_args_is_help=True)
app.add_typer(naan_app, name="naan")
app.add_typer(shoulder_app, name="shoulder")
app.add_typer(manager_app, name="manager")
app.add_typer(client_app, name="client")
app.add_typer(ark_app, name="ark")
app.add_typer(hold_app, name="hold")


def _root() -> Principal:
    """The CLI runs as the system administrator.

    Anyone with a shell on the server can reach the database anyway, so narrowing
    permissions here would not be a real guard. Instead, every operation is recorded in
    the audit log.
    """
    return Principal(client_id="cli", naan="", authority=Authority.SYSTEM, mechanism="cli")


def _session():
    return session_factory(settings=get_settings())()


@naan_app.command("add", help=t("naan.add.help"))
def naan_add(
    naan: str,
    name: str,
    policy: str = typer.Option("", help=t("naan.add.policy")),
    authoritative: bool = typer.Option(True, help=t("naan.add.authoritative")),
    redirect: str = typer.Option("", help=t("naan.add.redirect")),
):
    with _session() as s:
        obj = ops.create_naan(
            s, _root(), naan=naan, name=name, na_policy=policy,
            is_authoritative=authoritative, redirect=redirect,
        )
        s.commit()
        typer.echo(t("naan.add.done", naan=obj.naan, name=obj.name))


@naan_app.command("list", help=t("naan.list.help"))
def naan_list():
    with _session() as s:
        for n in s.scalars(select(Naan).order_by(Naan.naan)):
            flag = (
                t("word.authoritative") if n.is_authoritative
                else t("word.delegated_to", target=n.redirect)
            )
            typer.echo(f"{n.naan}  {n.name}  [{flag}]")


@app.command("onboard", help=t("onboard.help"))
def onboard(
    naan: str,
    name: str = typer.Argument(..., help=t("onboard.name")),
    shoulder: str = typer.Option(..., "--shoulder", "-s", help=t("onboard.shoulder")),
    quota: int = typer.Option(None, help=t("onboard.quota")),
    commitment: str = typer.Option("", help=t("onboard.commitment")),
):
    with _session() as s:
        m, sh = ops.onboard_manager(
            s, _root(), naan=naan, name=name, shoulder=shoulder, quota_per_day=quota,
            commitment_level=commitment,
        )
        s.commit()
        # Print the id. shoulder status, redirect and hold all take one as input, and
        # without it here the next step is a list command.
        typer.echo(t("onboard.done", name=m.name, naan=sh.naan, shoulder=sh.shoulder, id=sh.id))
        typer.echo(t("onboard.level", level=m.commitment_level))
        if not commitment:
            typer.echo(t("onboard.default_warning"), err=True)


@shoulder_app.command("add", help=t("shoulder.add.help"))
def shoulder_add(
    naan: str,
    shoulder: str,
    manager: int = typer.Option(None, help=t("opt.manager_id")),
    reserve: bool = typer.Option(False, help=t("shoulder.add.reserve")),
    note: str = typer.Option("", help=t("opt.note")),
):
    with _session() as s:
        sh = ops.add_shoulder(
            s, _root(), naan=naan, shoulder=shoulder, manager_id=manager,
            status="reserved" if reserve else "active", note=note,
        )
        s.commit()
        # Print the id: whoever just created it should not have to look it up.
        typer.echo(t("shoulder.add.done", naan=sh.naan, shoulder=sh.shoulder, id=sh.id))


@shoulder_app.command("status", help=t("shoulder.status.help"))
def shoulder_status(
    shoulder_id: int,
    status: str = typer.Argument(..., help=t("shoulder.status.arg")),
    minter: str = typer.Option("", help=t("shoulder.status.minter")),
    about: str = typer.Option("", help=t("shoulder.status.about")),
    note: str = typer.Option("", help=t("opt.note")),
):
    with _session() as s:
        sh = ops.set_shoulder_status(
            s, _root(), shoulder_id=shoulder_id, status=status,
            minter=minter, about=about, note=note,
        )
        s.commit()
        typer.echo(f"{sh.naan}{sh.shoulder} → {sh.status}")


@shoulder_app.command("redirect", help=t("shoulder.redirect.help"))
def shoulder_redirect(
    shoulder_id: int,
    redirect: str = typer.Argument("", help=t("shoulder.redirect.arg")),
):
    """An operation that used to exist only on a screen.

    Setting up delegation is the first thing anyone automates when building a federated
    setup, and making that one step go through a screen went against the screens and the
    CLI behaving alike. An empty string removes the delegation.
    """
    with _session() as s:
        sh = ops.set_shoulder_redirect(
            s, _root(), shoulder_id=shoulder_id, redirect=redirect.strip()
        )
        s.commit()
        key = "shoulder.redirect.done" if sh.redirect else "shoulder.redirect.cleared"
        typer.echo(t(key, naan=sh.naan, shoulder=sh.shoulder, redirect=sh.redirect))


@shoulder_app.command("list", help=t("shoulder.list.help"))
def shoulder_list(naan: str = typer.Option("", help=t("opt.only_naan"))):
    with _session() as s:
        stmt = select(Shoulder).order_by(Shoulder.naan, Shoulder.shoulder)
        if naan:
            stmt = stmt.where(Shoulder.naan == naan)
        for sh in s.scalars(stmt):
            m = s.get(Manager, sh.manager_id) if sh.manager_id else None
            typer.echo(
                f"{sh.id:>4}  {sh.naan}{sh.shoulder:<8} {sh.status:<10} "
                f"{m.name if m else t('word.unassigned')}"
            )


@manager_app.command("list", help=t("manager.list.help"))
def manager_list(naan: str = typer.Option("", help=t("opt.only_naan"))):
    with _session() as s:
        stmt = select(Manager).order_by(Manager.naan, Manager.id)
        if naan:
            stmt = stmt.where(Manager.naan == naan)
        for m in s.scalars(stmt):
            sh = s.get(Shoulder, m.default_shoulder_id) if m.default_shoulder_id else None
            state = "active" if m.active else "inactive"
            typer.echo(
                f"{m.id:>4}  {m.naan}{(sh.shoulder if sh else t('word.no_default')):<8} "
                f"{state:<9} {m.commitment_level:<22} {m.name}"
            )


@manager_app.command("commitment", help=t("manager.commitment.help"))
def manager_commitment(
    manager_id: int = typer.Argument(None, help=t("opt.manager_id")),
    level: str = typer.Argument(None, help=t("manager.commitment.level")),
    list_levels: bool = typer.Option(False, "--list", help=t("manager.commitment.list")),
):
    if list_levels:
        for c in CommitmentLevel:
            typer.echo(c.value)
        return
    if manager_id is None or not level:
        typer.echo(t("manager.commitment.need_args"), err=True)
        raise typer.Exit(1)
    with _session() as s:
        m = ops.set_commitment(s, _root(), manager_id=manager_id, level=level)
        s.commit()
        typer.echo(f"{m.name}: {m.commitment_level}")


@manager_app.command("policy", help=t("manager.policy.help"))
def manager_policy(
    manager_id: int,
    auth: str = typer.Option(None, help=t("manager.policy.auth")),
    self_register: bool = typer.Option(None, help=t("manager.policy.self_register")),
    max_scopes: str = typer.Option(None, help=t("manager.policy.max_scopes")),
):
    with _session() as s:
        m = ops.set_org_policy(
            s, _root(), manager_id=manager_id,
            mechanisms=auth.split() if auth is not None else None,
            may_self_register=self_register,
            max_scopes=max_scopes.split() if max_scopes is not None else None,
        )
        s.commit()
        typer.echo(t("manager.policy.auth_now", v=m.allowed_auth or t("word.unrestricted")))
        typer.echo(t("manager.policy.self_now",
                     v=t("word.yes" if m.may_self_register else "word.no")))
        typer.echo(t("manager.policy.scopes_now", v=m.max_scopes or t("word.unrestricted")))


@client_app.command("add", help=t("client.add.help"))
def client_add(
    client_id: str,
    naan: str,
    manager: int = typer.Option(None, help=t("opt.manager_id")),
    shoulder: int = typer.Option(None, help=t("client.add.shoulder")),
    scopes: str = typer.Option("ark:mint", help=t("client.add.scopes")),
    label: str = typer.Option(""),
    person: bool = typer.Option(False, help=t("client.add.person")),
    authority: str = typer.Option("manager", help=t("client.add.authority")),
):
    from datetime import UTC, datetime, timedelta

    with _session() as s:
        c = ops.register_client(
            s, _root(), client_id=client_id, naan=naan, manager_id=manager,
            shoulder_id=shoulder, scopes=scopes, label=label, authority=authority,
            subject_type="person" if person else "machine",
            expires_at=(datetime.now(UTC) + timedelta(days=365)) if authority == "naan" else None,
        )
        s.commit()
        kind = t("word.person") if person else t("word.machine")
        typer.echo(
            t("client.add.done", kind=kind, client_id=c.client_id, scopes=c.allowed_scopes)
        )
        if person:
            typer.echo(t("client.add.person_note"), err=True)


@client_app.command("key", help=t("client.key.help"))
def client_key(
    client_id: str,
    kind: str = typer.Option("api_key", help=t("client.key.kind")),
    label: str = typer.Option(""),
):
    with _session() as s:
        c = s.scalar(select(Client).where(Client.client_id == client_id))
        if c is None:
            typer.echo(t("client.not_found", client_id=client_id), err=True)
            raise typer.Exit(1)
        issued = ops.issue_credential(s, _root(), client_pk=c.id, kind=kind, label=label)
        s.commit()
        typer.echo(issued.secret)
        typer.echo(t("client.key.once"), err=True)


@client_app.command("breakglass", help=t("client.breakglass.help"))
def breakglass(
    naan: str,
    client_id: str = typer.Option("breakglass", help=t("client.breakglass.client_id")),
    days: int = typer.Option(7, help=t("client.breakglass.days")),
):
    with _session() as s:
        c = ops.register_client(
            s, _root(), client_id=client_id, naan=naan,
            authority=Authority.NAAN.value, scopes="ark:mint ark:update ark:read",
            expires_at=datetime.now(UTC) + timedelta(days=days),
        )
        issued = ops.issue_credential(s, _root(), client_pk=c.id, kind=CredentialKind.API_KEY.value)
        s.commit()
        typer.echo(issued.secret)
        typer.echo(t("client.breakglass.expires", days=days), err=True)


@client_app.command("passwd", help=t("client.passwd.help"))
def client_passwd(
    client_id: str,
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, confirmation_prompt=True,
        help=t("client.passwd.password"),
    ),
):
    with _session() as s:
        c = s.scalar(select(Client).where(Client.client_id == client_id))
        if c is None:
            typer.echo(t("client.not_found", client_id=client_id), err=True)
            raise typer.Exit(1)
        ops.set_password(s, _root(), client_pk=c.id, password=password)
        s.commit()
        typer.echo(t("client.passwd.done", client_id=client_id))


@client_app.command("disable", help=t("client.disable.help"))
def client_disable(client_id: str):
    _set_active(client_id, False)


@client_app.command("enable", help=t("client.enable.help"))
def client_enable(client_id: str):
    _set_active(client_id, True)


def _set_active(client_id: str, active: bool) -> None:
    with _session() as s:
        c = s.scalar(select(Client).where(Client.client_id == client_id))
        if c is None:
            typer.echo(t("client.not_found", client_id=client_id), err=True)
            raise typer.Exit(1)
        ops.set_client_active(s, _root(), client_pk=c.id, active=active)
        s.commit()
        typer.echo(t("client.enabled" if active else "client.disabled", client_id=client_id))


@client_app.command("revoke", help=t("client.revoke.help"))
def client_revoke(credential_id: int):
    with _session() as s:
        cred = ops.revoke_credential(s, _root(), credential_id=credential_id)
        s.commit()
        typer.echo(t("client.revoke.done", id=cred.id))


@ark_app.command("list", help=t("ark.list.help"))
def ark_list(
    naan: str = typer.Option("", help=t("opt.only_naan")),
    org: int = typer.Option(None, help=t("ark.list.org")),
    q: str = typer.Option("", "--search", "-q", help=t("ark.list.search")),
    state: str = typer.Option("", help=t("ark.list.state")),
    older_than: int = typer.Option(0, help=t("ark.list.older_than")),
    limit: int = typer.Option(50, help=t("ark.list.limit")),
    offset: int = typer.Option(0, help=t("ark.list.offset")),
):
    """List minted ARKs, filtered by the same queries as the screens
    (domain.queries).

    It truncates by default. ARKs are never deleted, so the ledger only grows, and
    printing everything would run away in a terminal. That it truncated is written to
    standard error; without that, the list reads as complete.

    The title is not printed. It has no length limit and would push the target URL off
    the line, and the target is the column people read off. To search by title, -q looks
    at it, as the screens do.
    """
    with _session() as s:
        stmt = narrow_arks(visible_arks(_root()), naan=naan, org=org or "", q=q, state=state,
                           older_than_days=older_than)
        # Fetch one extra to learn whether there is more, without counting. A count
        # gets heavier as the ledger grows, and all that is needed here is yes or no.
        rows = list(
            s.scalars(
                stmt.order_by(Ark.created_at.desc()).offset(max(0, offset)).limit(limit + 1)
            )
        )
        for a in rows[:limit]:
            # Only reserved rows are marked. The shape of a line does not change:
            # everything printed before was published, so scripts reading this see no
            # difference.
            mark = "" if a.published_at else f"  [{t('ark.mark.reserved')}]"
            typer.echo(
                f"{compact_ark(a.ark):<28}  {a.created_at:%Y-%m-%d}  "
                f"{a.created_by or '-':<14}  {a.url}{mark}"
            )
        if not rows:
            typer.echo(t("ark.list.empty"), err=True)
        elif len(rows) > limit:
            typer.echo(t("ark.list.more", next=max(0, offset) + limit), err=True)


@ark_app.command("publish", help=t("ark.publish.help"))
def ark_publish(ark: str):
    """Publish it to the world. Republishing something withdrawn uses the same
    command."""
    with _session() as s:
        key = ark_key_from_input(ark)
        before = s.get(Ark, key)
        already = before is not None and before.published_at is not None
        row = ops.publish_ark(s, _root(), ark=key)
        s.commit()
        key = "ark.publish.already" if already else "ark.publish.done"
        typer.echo(t(key, ark=compact_ark(row.ark)))


@ark_app.command("unpublish", help=t("ark.unpublish.help"))
def ark_unpublish(
    ark: str,
    reason: str = typer.Option(..., help=t("ark.unpublish.reason")),
    yes: bool = typer.Option(False, "--yes", "-y", help=t("ark.unpublish.yes")),
):
    """Withdraw the publication. The row stays, so ark publish puts it back.

    It asks first. A name that went out stops resolving, so without --yes it asks once,
    and the confirm that admin_ops requires is filled from that answer: the comparison
    lives in one place.
    """
    key = ark_key_from_input(ark)
    if not yes and not typer.confirm(t("ark.unpublish.confirm", ark=compact_ark(key))):
        typer.echo(t("ark.unpublish.aborted"))
        raise typer.Exit(1)
    with _session() as s:
        row = ops.unpublish_ark(s, _root(), ark=key, reason=reason, confirm=key)
        name = compact_ark(row.ark)
        s.commit()
        typer.echo(t("ark.unpublish.done", ark=name))


@ark_app.command("delete", help=t("ark.delete.help"))
def ark_delete(
    # Annotated rather than a default, because a list default that is a call is a
    # mutable-default shape even when Typer fills it in.
    arks: Annotated[list[str], typer.Argument(help=t("ark.delete.arks"))],
    reason: str = typer.Option("", help=t("ark.delete.reason")),
    yes: bool = typer.Option(False, "--yes", "-y", help=t("ark.delete.yes")),
):
    """Delete ARKs that are not published. While one is, admin_ops refuses.

    One ARK goes through withdraw_ark, which allows a name that was published once: it
    asks first, and the reason and confirmation admin_ops then requires are filled from
    that answer. A reservation that was never published is deleted without ceremony, so
    how much is asked matches what is being lost.

    Several go through withdraw_bulk, which refuses a name that has ever been public and
    fails the batch with it. Abandoning a batch of reservations has to be as cheap as
    minting it was, and the cheap path is only for names nobody has seen; a name that
    went out is deleted on its own.

    A single `-` reads the ARKs from standard input, one per line, so a list produced by
    `arkhe ark list` or a query can be piped straight in.
    """
    if arks == ["-"]:
        arks = [line.strip() for line in sys.stdin if line.strip()]
    keys = [ark_key_from_input(a) for a in arks]
    if not keys:
        typer.echo(t("ark.delete.nothing"))
        raise typer.Exit(1)

    with _session() as s:
        if len(keys) == 1:
            key = keys[0]
            row = s.get(Ark, key)
            exposed = row is not None and row.first_published_at is not None
            if exposed and not yes:
                if not typer.confirm(t("ark.delete.confirm", ark=compact_ark(key))):
                    typer.echo(t("ark.delete.aborted"))
                    raise typer.Exit(1)
            gone = ops.withdraw_ark(s, _root(), ark=key, reason=reason, confirm=key)
            name = compact_ark(gone.ark)
            s.commit()
            typer.echo(t("ark.delete.done", ark=name))
            return

        # One question for the batch. Asking per ARK would make a thousand
        # reservations unthrowable-away in practice, which is how they end up left in
        # the ledger.
        if not yes and not typer.confirm(t("ark.delete.confirm_bulk", count=len(keys))):
            typer.echo(t("ark.delete.aborted"))
            raise typer.Exit(1)
        gone_rows = ops.withdraw_bulk(s, _root(), arks=keys, reason=reason)
        count = len(gone_rows)
        s.commit()
        typer.echo(t("ark.delete.done_bulk", count=count))


@ark_app.command("purge", help=t("ark.purge.help"))
def ark_purge(
    ark: str,
    reason: str = typer.Option(..., help=t("ark.purge.reason")),
    yes: bool = typer.Option(False, "--yes", "-y", help=t("ark.purge.yes")),
):
    """Purge a published ARK, through the same admin_ops as the screens and the API.

    It asks first. The CLI runs as the system administrator, so a mistyped command here
    would simply go through; without --yes it asks once, and the confirm admin_ops
    requires is filled from that answer, keeping the comparison in one place.
    """
    key = ark_key_from_input(ark)
    if not yes and not typer.confirm(t("ark.purge.confirm", ark=compact_ark(key))):
        typer.echo(t("ark.purge.aborted"))
        raise typer.Exit(1)
    with _session() as s:
        gone = ops.purge_ark(s, _root(), ark=key, reason=reason, confirm=key)
        name = compact_ark(gone.ark)
        s.commit()
        typer.echo(t("ark.purge.done", ark=name))


# ---------------------------------------------------------- Holding redirection


def _hold_key(kind: str, key: str):
    """Turn what was typed into the key used in the ledger.

    An ARK goes through the same normalisation as the API: ark:, ark:/ or neither, with
    or without hyphens, all reach the same row. Skipping it here would mean an ARK that
    the screens and the API accept answering 404 in the CLI.
    """
    if kind == "ark":
        return ark_key_from_input(key)
    if kind == "shoulder":
        return int(key)
    return key


@hold_app.command("add", help=t("hold.add.help"))
def hold_add(
    kind: str = typer.Argument(..., help=t("hold.add.kind")),
    key: str = typer.Argument(..., help=t("hold.add.key")),
    days: int = typer.Option(..., help=t("hold.add.days")),
    reason: str = typer.Option(..., help=t("hold.add.reason")),
):
    with _session() as s:
        row = ops.set_hold(
            s, _root(), kind=kind, key=_hold_key(kind, key),
            until=datetime.now(UTC) + timedelta(days=days),
            reason=reason, max_days=get_settings().hold_max_days,
        )
        s.commit()
        typer.echo(
            t("hold.add.done", kind=kind, target=key, until=row.hold_until.isoformat())
        )


@hold_app.command("release", help=t("hold.release.help"))
def hold_release(
    kind: str = typer.Argument(..., help=t("hold.add.kind")),
    key: str = typer.Argument(..., help=t("hold.add.key")),
):
    with _session() as s:
        ops.release_hold(s, _root(), kind=kind, key=_hold_key(kind, key))
        s.commit()
        typer.echo(t("hold.release.done", kind=kind, target=key))


@hold_app.command("list", help=t("hold.list.help"))
def hold_list():
    with _session() as s:
        rows = ops.held(s, _root())
        if not rows:
            typer.echo(t("hold.list.empty"))
            return
        for h in rows:
            typer.echo(
                f"{h['kind']:<9} {h['target']:<28} {h['until'].isoformat()}  {h['reason']}"
            )


@app.command("succeed", help=t("succeed.help"))
def succeed_cmd(
    predecessor: int = typer.Argument(..., help=t("succeed.predecessor")),
    successor: int = typer.Argument(..., help=t("succeed.successor")),
    retire: bool = typer.Option(True, help=t("succeed.retire")),
):
    with _session() as s:
        r = ops.succeed(
            s, _root(), predecessor_id=predecessor, successor_id=successor, retire=retire
        )
        s.commit()
        typer.echo(t("succeed.done", successor=r["successor"], moved=", ".join(r["moved"])))
        if r["revoked"]:
            typer.echo(t("succeed.revoked", revoked=", ".join(r["revoked"])))


@app.command("depart", help=t("depart.help"))
def depart_cmd(
    manager: int = typer.Argument(..., help=t("depart.manager")),
    resolver: str = typer.Option("", help=t("depart.resolver")),
    keep_update: str = typer.Option("", help=t("depart.keep_update")),
):
    with _session() as s:
        r = ops.depart(
            s, _root(), manager_id=manager, resolver_template=resolver,
            keep_update_label=keep_update,
        )
        s.commit()
        typer.echo(t("depart.shoulders", shoulders=", ".join(r["shoulders"])))
        typer.echo(t("depart.rewritten", count=r["rewritten"]))
        if r["update_secret"]:
            typer.echo(r["update_secret"])
            typer.echo(t("depart.update_note"), err=True)


def _width(text: str) -> int:
    """How wide a string is in a terminal. Some characters take two columns.

    f"{label:<22}" pads by character count, so a label made of wide characters breaks
    the alignment, and this is a table meant to be read as a column of numbers.
    """
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


@app.command("stat", help=t("stat.help"))
def stat(
    naan: str = typer.Option("", help=t("opt.only_naan")),
    org: int = typer.Option(None, help=t("ark.list.org")),
    as_json: bool = typer.Option(False, "--json", help=t("stat.json")),
    by_shoulder: bool = typer.Option(True, help=t("stat.by_shoulder")),
):
    """Count the ledger, through the same domain.stats as the screens and the API.

    Counting costs time in proportion to the number of rows. The list screens avoid it,
    but here the count is the point, so it cannot be avoided: expect a few hundred
    milliseconds over a million rows. It is not made for polling.
    """
    import json as _json

    with _session() as s:
        st = stats_mod.ledger_stats(s, _root(), naan=naan, org=str(org or ""))

    if as_json:
        from dataclasses import asdict

        def _enc(o):
            return o.isoformat() if hasattr(o, "isoformat") else o

        typer.echo(_json.dumps(asdict(st), default=_enc, ensure_ascii=False, indent=2))
        return

    def row(label: str, value, note: str = "") -> None:
        typer.echo(f"{_pad(label, 26)}{value:>12}  {note}".rstrip())

    typer.echo(t("stat.head", scope=t(f"stat.scope.{st.scope}")))
    row(t("stat.naans"), st.naans)
    row(t("stat.arks"), f"{st.arks:,}",
        t("stat.arks_note", public=f"{st.public:,}", reserved=f"{st.reserved:,}"))
    row(t("stat.withdrawn"), f"{st.withdrawn:,}",
        t("stat.withdrawn_note", n=f"{st.withdrawn_after_publication:,}"))
    row(t("stat.shoulders"), sum(st.shoulders.values()),
        " / ".join(f"{k} {v}" for k, v in st.shoulders.items()))
    row(t("stat.orgs"), st.organisations, t("stat.active_note", n=st.organisations_active))
    row(t("stat.clients"), st.clients, t("stat.active_note", n=st.clients_active))
    row(t("stat.holds"), sum(st.holds.values()),
        " / ".join(f"{k} {v}" for k, v in st.holds.items()))
    row(t("stat.minted"), "",
        " / ".join(f"{k} {v:,}" for k, v in st.minted.items()))
    if st.first_mint:
        row(t("stat.first"), st.first_mint.strftime("%Y-%m-%d"))
        row(t("stat.last"), st.last_mint.strftime("%Y-%m-%d"))
    if st.reserved_oldest:
        # Printed as a date rather than beside a count. A backlog shows in age, not
        # in number: ten reserved yesterday is ordinary, one reserved three years ago
        # is forgotten.
        age = (datetime.now(UTC) - st.reserved_oldest).days
        row(t("stat.reserved_oldest"), st.reserved_oldest.strftime("%Y-%m-%d"),
            t("stat.days_ago", n=age))

    if by_shoulder and st.by_shoulder:
        typer.echo("")
        typer.echo(t("stat.per_shoulder"))
        for sh in st.by_shoulder:
            name = f"{sh.naan}{sh.shoulder}"
            note = t("stat.arks_note", public=f"{sh.public:,}", reserved=f"{sh.reserved:,}")
            typer.echo(
                f"  {name:<18}{sh.arks:>10,}  {_pad(note, 26)}"
                f"{sh.status:<10}{sh.organisation}"
            )


@app.command("fingerprint", help=t("fp.help"))
def fingerprint(as_json: bool = typer.Option(False, "--json", help=t("stat.json"))):
    """Confirm a restore by its contents rather than by its row count.

    Run it on the restored ledger and compare with the value taken before. The counts
    can agree while every target has moved, in which case all the identifiers are
    broken.

    The output is two lines. Collapsed into one, it would no longer say where the
    difference is, and losing the withdrawn names in particular is silent, because
    minting keeps working without them.
    """
    import json as _json
    from dataclasses import asdict

    with _session() as s:
        fp = stats_mod.ledger_fingerprint(s)
    if as_json:
        typer.echo(_json.dumps(asdict(fp), ensure_ascii=False))
        return
    for line in fp.lines():
        typer.echo(line)


@app.command("check", help=t("check.help"))
def check():
    s = get_settings()
    s.check()
    typer.echo(t("check.auth", auth=", ".join(s.auth)))
    typer.echo(t("check.role", role="resolver" if s.resolver else "minter + admin"))
    typer.echo(t("check.db", url=s.database_url))
    if s.read_url != s.database_url:
        typer.echo(t("check.read_db", url=s.read_url))
    typer.echo(t("check.ok"))


if __name__ == "__main__":  # pragma: no cover
    app()
