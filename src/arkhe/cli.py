"""運用コマンド。**画面と同じ `domain.admin_ops` を呼ぶ。**

CLI にしかできないこと・画面にしかできないことを作らない。どちらから入っても
同じ不変条件を通る。監査にも同じ形で残る。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import typer
from sqlalchemy import select

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
    """**CLI はシステム管理者として動く。**

    サーバのシェルに入れる時点で DB に届くので、ここで権限を絞っても意味の
    ある防御にはならない。**代わりに、操作は必ず監査に残る。**
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
        typer.echo(t("onboard.done", name=m.name, naan=sh.naan, shoulder=sh.shoulder))
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
        typer.echo(t("shoulder.add.done", naan=sh.naan, shoulder=sh.shoulder))


@shoulder_app.command("status", help=t("shoulder.status.help"))
def shoulder_status(
    shoulder_id: int,
    status: str = typer.Argument(..., help=t("shoulder.status.arg")),
    minter: str = typer.Option("", help=t("shoulder.status.minter")),
    note: str = typer.Option("", help=t("opt.note")),
):
    with _session() as s:
        sh = ops.set_shoulder_status(
            s, _root(), shoulder_id=shoulder_id, status=status, minter=minter, note=note
        )
        s.commit()
        typer.echo(f"{sh.naan}{sh.shoulder} → {sh.status}")


@shoulder_app.command("redirect", help=t("shoulder.redirect.help"))
def shoulder_redirect(
    shoulder_id: int,
    redirect: str = typer.Argument("", help=t("shoulder.redirect.arg")),
):
    """**画面にしかなかった操作を CLI にも置く。**

    委譲の設定は分散構成を組むときにいちばん自動化したいところで、そこだけ
    画面を開かせるのは「画面と CLI に差を作らない」に反していた。
    空文字を渡せば委譲を外す。
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
    limit: int = typer.Option(50, help=t("ark.list.limit")),
    offset: int = typer.Option(0, help=t("ark.list.offset")),
):
    """発行した ARK を並べる。**絞り込みは画面と同じ式を通る**（`domain.queries`）。

    **既定で打ち切る。** ARK は消えないので台帳は増える一方で、全件を黙って
    流すと運用の端末で止まらなくなる。打ち切ったことは標準エラーに出す
    ——出さなければ「これで全部」と読まれる。

    題名は出さない。長さに上限が無く、行き先の URL を押し出してしまうため
    ——**行き先は目で追って写す列**なので、そこを崩さない。題名で引きたい
    ときは `-q` が見ている（画面と同じ 3 項目）。
    """
    with _session() as s:
        stmt = narrow_arks(visible_arks(_root()), naan=naan, org=org or "", q=q)
        # 1 件多く取って、続きがあるかを**数えずに**知る。件数の COUNT は
        # 台帳が大きくなるほど重く、ここで欲しいのは有無だけ。
        rows = list(
            s.scalars(
                stmt.order_by(Ark.created_at.desc()).offset(max(0, offset)).limit(limit + 1)
            )
        )
        for a in rows[:limit]:
            typer.echo(
                f"ark:/{a.ark:<24}  {a.created_at:%Y-%m-%d}  "
                f"{a.created_by or '-':<14}  {a.url}"
            )
        if not rows:
            typer.echo(t("ark.list.empty"), err=True)
        elif len(rows) > limit:
            typer.echo(t("ark.list.more", next=max(0, offset) + limit), err=True)


# ------------------------------------------------------------------ 転送の保留


def _hold_key(kind: str, key: str):
    """CLI の入力を台帳の鍵に直す。

    **ARK は API と同じ正規化を通す**（`ark:/` を付けても付けなくても、
    ハイフン入りでも同じ行に当たる）。ここだけ素通しにすると、画面や API で
    止められる ARK が CLI では 404 になる。
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
