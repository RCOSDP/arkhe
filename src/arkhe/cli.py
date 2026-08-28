"""運用コマンド。**画面と同じ `domain.admin_ops` を呼ぶ。**

CLI にしかできないこと・画面にしかできないことを作らない。どちらから入っても
同じ不変条件を通る。監査にも同じ形で残る。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import typer
from sqlalchemy import select

from arkhe.auth.principal import Principal
from arkhe.db.models import Authority, Client, CredentialKind, Manager, Naan, Shoulder
from arkhe.db.session import session_factory
from arkhe.domain import admin_ops as ops
from arkhe.settings import get_settings

app = typer.Typer(help="arkhe — ARK 識別子基盤の運用コマンド", no_args_is_help=True)
naan_app = typer.Typer(help="NAAN", no_args_is_help=True)
shoulder_app = typer.Typer(help="shoulder", no_args_is_help=True)
client_app = typer.Typer(help="主体と資格情報", no_args_is_help=True)
app.add_typer(naan_app, name="naan")
app.add_typer(shoulder_app, name="shoulder")
app.add_typer(client_app, name="client")


def _root() -> Principal:
    """**CLI はシステム管理者として動く。**

    サーバのシェルに入れる時点で DB に届くので、ここで権限を絞っても意味の
    ある防御にはならない。**代わりに、操作は必ず監査に残る。**
    """
    return Principal(client_id="cli", naan="", authority=Authority.SYSTEM, mechanism="cli")


def _session():
    return session_factory(settings=get_settings())()


@naan_app.command("add")
def naan_add(
    naan: str,
    name: str,
    policy: str = typer.Option("", help="NAA ポリシー（`NP | NR, OP, CC | 2026 | <URL>`）"),
    authoritative: bool = typer.Option(True, help="この NAAN の権威を持つか"),
    redirect: str = typer.Option("", help="権威を持たない場合の委譲先"),
):
    """NAAN を登録する。"""
    with _session() as s:
        obj = ops.create_naan(
            s, _root(), naan=naan, name=name, na_policy=policy,
            is_authoritative=authoritative, redirect=redirect,
        )
        s.commit()
        typer.echo(f"NAAN {obj.naan} ({obj.name}) を登録しました")


@naan_app.command("list")
def naan_list():
    with _session() as s:
        for n in s.scalars(select(Naan).order_by(Naan.naan)):
            flag = "権威あり" if n.is_authoritative else f"委譲 → {n.redirect}"
            typer.echo(f"{n.naan}  {n.name}  [{flag}]")


@app.command("onboard")
def onboard(
    naan: str,
    name: str = typer.Argument(..., help="機関名（内部専用。公開しない）"),
    shoulder: str = typer.Option(..., "--shoulder", "-s", help="委譲する名前空間（例 /x9）"),
    quota: int = typer.Option(None, help="1 日あたりの採番上限。省略で無制限"),
):
    """機関を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。**"""
    with _session() as s:
        m, sh = ops.onboard_manager(
            s, _root(), naan=naan, name=name, shoulder=shoulder, quota_per_day=quota
        )
        s.commit()
        typer.echo(f"機関 {m.name} を迎え、{sh.naan}{sh.shoulder} を委譲しました")


@shoulder_app.command("add")
def shoulder_add(naan: str, shoulder: str, manager: int = typer.Option(None, help="機関 id")):
    with _session() as s:
        sh = ops.add_shoulder(s, _root(), naan=naan, shoulder=shoulder, manager_id=manager)
        s.commit()
        typer.echo(f"{sh.naan}{sh.shoulder} を切り出しました")


@shoulder_app.command("status")
def shoulder_status(
    shoulder_id: int,
    status: str = typer.Argument(..., help="active / reserved / delegated / retired"),
    minter: str = typer.Option("", help="delegated のときの採番の行き先"),
    note: str = typer.Option("", help="運用の記録"),
):
    """状態を変える。**retired からは戻せない**（引退した名前空間の再開は NR 違反の芽）。"""
    with _session() as s:
        sh = ops.set_shoulder_status(
            s, _root(), shoulder_id=shoulder_id, status=status, minter=minter, note=note
        )
        s.commit()
        typer.echo(f"{sh.naan}{sh.shoulder} → {sh.status}")


@shoulder_app.command("list")
def shoulder_list(naan: str = typer.Option("", help="この NAAN のものだけ")):
    with _session() as s:
        stmt = select(Shoulder).order_by(Shoulder.naan, Shoulder.shoulder)
        if naan:
            stmt = stmt.where(Shoulder.naan == naan)
        for sh in s.scalars(stmt):
            m = s.get(Manager, sh.manager_id) if sh.manager_id else None
            typer.echo(
                f"{sh.id:>4}  {sh.naan}{sh.shoulder:<8} {sh.status:<10} "
                f"{m.name if m else '(機関未割当)'}"
            )


@client_app.command("add")
def client_add(
    client_id: str,
    naan: str,
    manager: int = typer.Option(None, help="機関 id"),
    shoulder: int = typer.Option(None, help="この shoulder に固定する"),
    scopes: str = typer.Option("ark:mint", help="空白区切り"),
    label: str = typer.Option(""),
):
    with _session() as s:
        c = ops.register_client(
            s, _root(), client_id=client_id, naan=naan, manager_id=manager,
            shoulder_id=shoulder, scopes=scopes, label=label,
        )
        s.commit()
        typer.echo(f"主体 {c.client_id} を登録しました（scope: {c.allowed_scopes}）")


@client_app.command("key")
def client_key(
    client_id: str,
    kind: str = typer.Option("api_key", help="api_key / client_secret"),
    label: str = typer.Option(""),
):
    """資格情報を発行する。**平文はこの一度しか表示されない。**"""
    with _session() as s:
        c = s.scalar(select(Client).where(Client.client_id == client_id))
        if c is None:
            typer.echo(f"主体 {client_id} が見つかりません", err=True)
            raise typer.Exit(1)
        issued = ops.issue_credential(s, _root(), client_pk=c.id, kind=kind, label=label)
        s.commit()
        typer.echo(issued.secret)
        typer.echo(
            "↑ この値はもう二度と表示されません。保存しているのはハッシュだけです。", err=True
        )


@client_app.command("breakglass")
def breakglass(
    naan: str,
    client_id: str = typer.Option("breakglass", help="登録する client_id"),
    days: int = typer.Option(7, help="有効期限（日）"),
):
    """NAAN 配下すべてに届く一時的な主体を作る。**期限つき。**

    障害対応のための逃げ道。恒久的な万能鍵にしないよう期限を必須にしてある。
    この主体の操作は**全件が監査に残る**。
    """
    with _session() as s:
        c = ops.register_client(
            s, _root(), client_id=client_id, naan=naan,
            authority=Authority.NAAN.value, scopes="ark:mint ark:update ark:read",
            expires_at=datetime.now(UTC) + timedelta(days=days),
        )
        issued = ops.issue_credential(s, _root(), client_pk=c.id, kind=CredentialKind.API_KEY.value)
        s.commit()
        typer.echo(issued.secret)
        typer.echo(f"↑ {days} 日で失効します。操作は全件監査に残ります。", err=True)


@client_app.command("revoke")
def client_revoke(credential_id: int):
    """失効させる。**行は消さない**（いつ失効したかを残す）。"""
    with _session() as s:
        cred = ops.revoke_credential(s, _root(), credential_id=credential_id)
        s.commit()
        typer.echo(f"資格情報 {cred.id} を失効させました")


@app.command("succeed")
def succeed_cmd(
    predecessor: int = typer.Argument(..., help="承継元の機関 id"),
    successor: int = typer.Argument(..., help="承継先の機関 id"),
    retire: bool = typer.Option(True, help="移した shoulder の新規採番を止める"),
):
    """統廃合。**識別子は壊さない**（名前空間ごと承継先に移す）。"""
    with _session() as s:
        r = ops.succeed(
            s, _root(), predecessor_id=predecessor, successor_id=successor, retire=retire
        )
        s.commit()
        typer.echo(f"{r['successor']} が承継しました: {', '.join(r['moved'])}")
        if r["revoked"]:
            typer.echo(f"停止した資格情報: {', '.join(r['revoked'])}")


@app.command("depart")
def depart_cmd(
    manager: int = typer.Argument(..., help="離脱する機関 id"),
    resolver: str = typer.Option(
        "", help="転送先を機関のリゾルバに一括で向け直す。例 'https://repo.example.ac.jp/ark/${blade}'"
    ),
    keep_update: str = typer.Option("", help="更新権限だけの主体を残す（ラベル）"),
):
    """機関の離脱。**新規採番は止め、解決は続ける。**"""
    with _session() as s:
        r = ops.depart(
            s, _root(), manager_id=manager, resolver_template=resolver,
            keep_update_label=keep_update,
        )
        s.commit()
        typer.echo(f"停止した shoulder: {', '.join(r['shoulders'])}")
        typer.echo(f"転送先を書き換えた ARK: {r['rewritten']} 件")
        if r["update_secret"]:
            typer.echo(r["update_secret"])
            typer.echo("↑ 更新権限だけの鍵。この一度しか表示されません。", err=True)


@app.command("check")
def check():
    """設定を検証する。**起動前に落としたいものをここで落とす。**"""
    s = get_settings()
    s.check()
    typer.echo(f"認証機構: {', '.join(s.auth)}")
    typer.echo(f"役割    : {'resolver' if s.resolver else 'minter + admin'}")
    typer.echo(f"DB      : {s.database_url}")
    if s.read_url != s.database_url:
        typer.echo(f"  読取専用: {s.read_url}")
    typer.echo("設定は妥当です")


if __name__ == "__main__":  # pragma: no cover
    app()
