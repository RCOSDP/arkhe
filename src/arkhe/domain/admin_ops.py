"""管理操作。**画面も CLI も、ここを呼ぶ。**

管理画面をテーブルの行編集にしない理由がここにある。arkhe で意味を持つのは
「機関をオンボードする」「shoulder を retire する」「委譲先を設定する」といった
**操作**で、行の項目を書き換えることではない。行編集を許すと、

  - `Shoulder.status` を `retired` から `active` に戻す（引退した名前空間の再開＝NR 違反の芽）
  - `Ark.ark` を書き換える（別の識別子に化ける）
  - `Naan.is_authoritative` を落として redirect を空のままにする（解決不能）

といったことが、画面の都合だけで起きる。**操作として定義すれば、そもそも表現できない。**

各操作は「誰が呼べるか」を `require` で明示する。判定は `Principal` の 3 段
（system / naan / manager）で、画面はこの結果を見てボタンを出し分ける。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from arkhe.auth import apikey, oauth2
from arkhe.auth.errors import Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    Authority,
    Client,
    Credential,
    CredentialKind,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
)
from arkhe.domain.authz import Invalid, NotFound, audit


def _require_system(p: Principal) -> None:
    if not p.is_system:
        raise Forbidden("この操作はシステム管理者のみ")


def _require_naan(p: Principal, naan: str) -> None:
    """その NAAN に届くか。system は全 NAAN。"""
    if not p.reaches_naan(naan):
        raise Forbidden(f"NAAN {naan} はこの主体の範囲外")


def _require_manager(session: Session, p: Principal, manager: Manager) -> None:
    """その機関に届くか。NAAN 単位以上なら配下すべて、manager 単位なら自機関のみ。"""
    _require_naan(p, manager.naan)
    if p.is_naan_wide:
        return
    if p.manager_id != manager.id:
        raise Forbidden("この機関はこの主体の範囲外")


# --------------------------------------------------------------------- NAAN


def create_naan(session: Session, p: Principal, *, naan: str, name: str, **fields) -> Naan:
    """**NAAN を登録できるのはシステム管理者だけ。** 名前空間を配る側の操作。"""
    _require_system(p)
    if session.get(Naan, naan) is not None:
        raise Invalid({"naan": f"NAAN {naan} は登録済み"})
    obj = Naan(naan=naan, name=name, **fields)
    session.add(obj)
    audit(session, p, "create_naan", naan)
    return obj


def set_na_policy(session: Session, p: Principal, *, naan: str, policy: str) -> Naan:
    """永続性宣言（NAA ポリシー）を設定する。

    **ARK は「永続性は約束であって性質ではない」という立場**を取る。だから
    保証を名乗るのではなく、**どの水準の約束をするかを自分で宣言する**。
    その宣言を書き換えられるのは、その NAAN を預かる主体。
    """
    obj = session.get(Naan, naan)
    if obj is None:
        raise NotFound({"naan": naan})
    _require_naan(p, naan)
    obj.na_policy = policy
    audit(session, p, "set_na_policy", naan, policy=policy)
    return obj


# ------------------------------------------------------------------ Manager


def onboard_manager(
    session: Session,
    p: Principal,
    *,
    naan: str,
    name: str,
    shoulder: str,
    commitment_level: str = "",
    quota_per_day: int | None = None,
) -> tuple[Manager, Shoulder]:
    """機関を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。**

    機関だけ作って shoulder が無い状態は、採番できない機関を生むだけで意味がない。
    `default_shoulder` もここで結ぶ（無いと shoulder 省略の採番が落ちる）。
    """
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("機関のオンボードは NAAN 単位以上の権限が要る")
    if session.get(Naan, naan) is None:
        raise NotFound({"naan": naan})
    if session.scalar(select(Manager).where(Manager.naan == naan, Manager.name == name)):
        raise Invalid({"name": f"{naan} に機関 {name} は登録済み"})

    manager = Manager(naan=naan, name=name)
    if commitment_level:
        manager.commitment_level = commitment_level
    manager.quota_per_day = quota_per_day
    session.add(manager)
    session.flush()

    sh = _add_shoulder(session, naan=naan, shoulder=shoulder, manager=manager)
    manager.default_shoulder_id = sh.id
    audit(session, p, "onboard_manager", f"{naan}{shoulder}", manager=name)
    return manager, sh


def set_succession(
    session: Session, p: Principal, *, manager_id: int, successor_id: int | None
) -> Manager:
    """統廃合の承継先を設定する。

    **識別子は壊さない。** 管理主体が変わっても `NR` を宣言している以上、解決は
    続ける。系譜を辿れるように、旧機関の行は残したまま承継先を指す。
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_manager(session, p, manager)
    if successor_id is not None:
        succ = session.get(Manager, successor_id)
        if succ is None:
            raise NotFound({"successor": successor_id})
        if succ.id == manager.id:
            raise Invalid({"successor": "自分自身は承継先にできない"})
        _require_naan(p, succ.naan)
    manager.succeeded_by_id = successor_id
    audit(session, p, "set_succession", str(manager_id), successor=successor_id)
    return manager


# ----------------------------------------------------------------- Shoulder


def _add_shoulder(
    session: Session,
    *,
    naan: str,
    shoulder: str,
    manager: Manager | None,
    status: str = ShoulderStatus.ACTIVE.value,
) -> Shoulder:
    if not shoulder.startswith("/"):
        shoulder = "/" + shoulder
    if session.scalar(
        select(Shoulder).where(Shoulder.naan == naan, Shoulder.shoulder == shoulder)
    ):
        raise Invalid({"shoulder": f"{naan}{shoulder} は既に在る"})
    sh = Shoulder(
        shoulder=shoulder,
        naan=naan,
        manager_id=manager.id if manager else None,
        status=status,
    )
    session.add(sh)
    session.flush()
    return sh


def add_shoulder(
    session: Session,
    p: Principal,
    *,
    naan: str,
    shoulder: str,
    manager_id: int | None = None,
    status: str = ShoulderStatus.ACTIVE.value,
    note: str = "",
) -> Shoulder:
    """名前空間を切り出す。**NAAN 単位以上の権限が要る**（配る側の操作）。

    `status=reserved` で「押さえてあるが使わせない」状態で作れる。**予約は作成時に
    しか指定できない**——active から reserved へ戻す遷移は許していないため
    （一度採番できる状態にした名前空間を、後から「未使用扱い」にはできない）。
    """
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("shoulder の追加は NAAN 単位以上の権限が要る")
    manager = session.get(Manager, manager_id) if manager_id else None
    if manager_id and manager is None:
        raise NotFound({"manager": manager_id})
    if status not in (ShoulderStatus.ACTIVE, ShoulderStatus.RESERVED):
        raise Invalid({"status": "作成時に指定できるのは active か reserved のみ"})
    sh = _add_shoulder(
        session, naan=naan, shoulder=shoulder, manager=manager, status=status
    )
    if note:
        sh.note = note
    audit(session, p, "add_shoulder", f"{naan}{shoulder}", status=status)
    return sh


#: **戻れる遷移と戻れない遷移がある。**
#: retired から active に戻すのは「引退した名前空間の再開」で、その間に外部が
#: 同じ名前を使っている可能性を否定できない（NR 違反の芽）。だから許さない。
ALLOWED_TRANSITIONS = {
    ShoulderStatus.RESERVED: {ShoulderStatus.ACTIVE, ShoulderStatus.DELEGATED},
    ShoulderStatus.ACTIVE: {ShoulderStatus.DELEGATED, ShoulderStatus.RETIRED},
    ShoulderStatus.DELEGATED: {ShoulderStatus.ACTIVE, ShoulderStatus.RETIRED},
    ShoulderStatus.RETIRED: set(),  # **引き返せない**
}


def set_shoulder_status(
    session: Session,
    p: Principal,
    *,
    shoulder_id: int,
    status: str,
    minter: str = "",
    note: str = "",
) -> Shoulder:
    """shoulder の状態を変える。**遷移は表で縛る。**"""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise NotFound({"shoulder": shoulder_id})
    _require_naan(p, sh.naan)
    if not p.is_naan_wide:
        raise Forbidden("shoulder の状態変更は NAAN 単位以上の権限が要る")

    cur, new = ShoulderStatus(sh.status), ShoulderStatus(status)
    if new != cur and new not in ALLOWED_TRANSITIONS[cur]:
        raise Invalid(
            {
                "status": f"{cur} → {new} は許されない遷移",
                "reason": (
                    "retired からは戻せない（引退した名前空間の再開は NR 違反の芽）"
                    if cur is ShoulderStatus.RETIRED
                    else "許される遷移は " + ", ".join(sorted(ALLOWED_TRANSITIONS[cur]))
                ),
            }
        )
    if new is ShoulderStatus.DELEGATED and not (minter or sh.minter):
        raise Invalid({"minter": "委譲するなら採番の行き先が要る"})
    sh.status = new.value
    if minter:
        sh.minter = minter
    if note:
        sh.note = note
    audit(session, p, "set_shoulder_status", f"{sh.naan}{sh.shoulder}", status=new.value)
    return sh


def set_shoulder_redirect(
    session: Session, p: Principal, *, shoulder_id: int, redirect: str
) -> Shoulder:
    """shoulder 単位の解決委譲（N2T のデータモデル）。`$id` / `${blade}` / `303 ` に対応。"""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise NotFound({"shoulder": shoulder_id})
    _require_naan(p, sh.naan)
    if not p.is_naan_wide:
        raise Forbidden("解決の委譲は NAAN 単位以上の権限が要る")
    sh.redirect = redirect
    audit(session, p, "set_shoulder_redirect", f"{sh.naan}{sh.shoulder}", redirect=redirect)
    return sh


# ------------------------------------------------------------- 資格情報


@dataclass
class IssuedCredential:
    """**平文はここでしか手に入らない。** 保存せず、その場で一度だけ見せる。"""

    credential: Credential
    secret: str


def register_client(
    session: Session,
    p: Principal,
    *,
    client_id: str,
    naan: str,
    manager_id: int | None = None,
    authority: str = Authority.MANAGER.value,
    shoulder_id: int | None = None,
    scopes: str = "ark:mint",
    label: str = "",
    expires_at: datetime | None = None,
) -> Client:
    """採番する主体を登録する。**自分より広い到達範囲は与えられない。**"""
    _require_naan(p, naan)
    target = Authority(authority)
    if target is Authority.SYSTEM:
        _require_system(p)
    elif target is Authority.NAAN and not p.is_naan_wide:
        raise Forbidden("authority=naan の主体を作るには NAAN 単位以上の権限が要る")
    if not p.is_naan_wide and manager_id != p.manager_id:
        raise Forbidden("自機関以外の主体は作れない")
    if session.scalar(select(Client).where(Client.client_id == client_id)):
        raise Invalid({"client_id": f"{client_id} は登録済み"})
    if target is Authority.NAAN and expires_at is None:
        # break-glass は**期限を必須**にする。恒久的な万能鍵を作らせない。
        raise Invalid({"expires_at": "authority=naan の主体には期限が要る"})

    client = Client(
        client_id=client_id,
        naan=naan,
        manager_id=manager_id,
        authority=target.value,
        shoulder_id=shoulder_id,
        allowed_scopes=scopes,
        label=label,
        expires_at=expires_at,
    )
    session.add(client)
    session.flush()
    audit(session, p, "register_client", client_id, authority=target.value)
    return client


def issue_credential(
    session: Session,
    p: Principal,
    *,
    client_pk: int,
    kind: str = CredentialKind.API_KEY.value,
    label: str = "",
    expires_at: datetime | None = None,
) -> IssuedCredential:
    """資格情報を発行する。**旧いものは自動で失効させない**——並行させて切り替える。"""
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("この主体はこの管理者の範囲外")

    gen = apikey.generate_key if kind == CredentialKind.API_KEY else oauth2.generate_secret
    raw, prefix, hashed = gen()
    cred = Credential(
        client_pk=client.id,
        kind=kind,
        prefix=prefix,
        hashed=hashed,
        label=label,
        expires_at=expires_at,
    )
    session.add(cred)
    session.flush()
    audit(session, p, "issue_credential", client.client_id, kind=kind)
    return IssuedCredential(credential=cred, secret=raw)


def revoke_credential(session: Session, p: Principal, *, credential_id: int) -> Credential:
    """失効させる。**行は消さない**（いつ失効したかを残す）。"""
    cred = session.get(Credential, credential_id)
    if cred is None:
        raise NotFound({"credential": credential_id})
    client = cred.client
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("この資格情報はこの管理者の範囲外")
    cred.active = False
    cred.expires_at = cred.expires_at or datetime.now(UTC)
    audit(session, p, "revoke_credential", client.client_id, credential=credential_id)
    return cred


# ------------------------------------------------------------- 承継と離脱
#
# ここが ARK の思想がいちばん出るところ。**管理主体がどう変わっても、識別子は
# 壊さない。** `NR`（再割当てしない）を宣言している以上、`ark:/<NAAN>/…` という
# 形で配ってしまった名前は振り直せない——振り直すことは元の識別子を殺すこと。
# だから解決は続け、変えるのは「誰が新規に採番するか」と「どこへ転送するか」だけ。


def succeed(
    session: Session,
    p: Principal,
    *,
    predecessor_id: int,
    successor_id: int,
    retire: bool = True,
) -> dict:
    """統廃合。**旧機関の名前空間を承継先に移す。**

    shoulder ごと移すので、既存 ARK の `shoulder_id` は変わらない＝**識別子も
    解決先も無傷**。変わるのは「その名前空間を今後誰が預かるか」だけ。

    `retire=True` なら移した shoulder の新規採番を止める（既存は解決し続ける）。
    承継先が自分の shoulder で採番を続け、旧名前空間は読み取り専用になる形。
    """
    pre = session.get(Manager, predecessor_id)
    suc = session.get(Manager, successor_id)
    if pre is None or suc is None:
        raise NotFound({"manager": [predecessor_id, successor_id]})
    _require_manager(session, p, pre)
    _require_naan(p, suc.naan)
    if pre.id == suc.id:
        raise Invalid({"successor": "自分自身は承継先にできない"})
    if pre.naan != suc.naan:
        # NAAN を跨ぐ承継は shoulder の移動では表せない（名前空間ごと別物）。
        raise Invalid({"successor": "NAAN を跨ぐ承継はできない（識別子の形が変わるため）"})

    moved = []
    for sh in list(pre.shoulders):
        sh.manager_id = suc.id
        if retire:
            sh.status = ShoulderStatus.RETIRED.value
            sh.note = (sh.note + " / ").lstrip(" /") + f"{pre.name} から承継"
        moved.append(f"{sh.naan}{sh.shoulder}")
    pre.succeeded_by_id = suc.id
    pre.active = False
    # 旧機関の資格情報は止める。**行は消さない**（誰の鍵だったかを残す）。
    revoked = [c.client_id for c in session.scalars(
        select(Client).where(Client.manager_id == pre.id, Client.active.is_(True))
    )]
    for c in session.scalars(select(Client).where(Client.manager_id == pre.id)):
        c.active = False

    audit(session, p, "succeed", pre.name, successor=suc.name, shoulders=moved, revoked=revoked)
    return {"moved": moved, "revoked": revoked, "successor": suc.name}


def depart(
    session: Session,
    p: Principal,
    *,
    manager_id: int,
    resolver_template: str = "",
    keep_update_label: str = "",
) -> dict:
    """**機関が離れる**（組織は存続する。統廃合とは別）。

    核心は 1 点——**新規採番は止めるが、解決は永久に続ける。**
    `ark:/<この NAAN>/…` という形で配った以上、振り直せないので、NAAN の保有者が
    302 を返し続けるしかない。

    **`resolver_template` を渡すのが推奨。** 既存 ARK の転送先を機関のリゾルバへ
    一括で向け直し、shoulder にも同じ委譲を設定する。**これで以後の運用が機関側に
    閉じる**——離れた機関に「移転のたびに我々へ更新を投げる」作業を強いない。
    継続作業を要求する形にすると、放置されて死んだリンクが残る。

    テンプレートは `Shoulder.redirect` と同じ記法（`$id` / `${blade}`）。
    例: ``https://repo.univ.ac.jp/ark/${blade}``
    """
    from arkhe.domain.resolution import expand_redirect

    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_manager(session, p, manager)

    shoulders = list(manager.shoulders)
    rewritten = 0
    if resolver_template:
        ids = [sh.id for sh in shoulders]
        for sh in shoulders:
            sh.redirect = resolver_template  # 未登録の名前も機関のリゾルバへ
        for ark in session.scalars(select(Ark).where(Ark.shoulder_id.in_(ids))):
            _, ark.url = expand_redirect(resolver_template, ark.naan, ark.assigned_name)
            rewritten += 1

    for sh in shoulders:
        sh.status = ShoulderStatus.RETIRED.value
        sh.note = (sh.note + " / ").lstrip(" /") + "離脱により新規採番を停止"

    revoked = [c.client_id for c in session.scalars(
        select(Client).where(Client.manager_id == manager.id, Client.active.is_(True))
    )]
    for c in session.scalars(select(Client).where(Client.manager_id == manager.id)):
        c.active = False

    issued = None
    if keep_update_label:
        # **更新権限だけ残す。** scope を分けてある設計がここで効く——
        # 新規採番はできないが、転送先の付け替えは自分でできる。
        client = register_client(
            session, p, client_id=f"{manager.name}-{keep_update_label}",
            naan=manager.naan, manager_id=manager.id, scopes="ark:update",
            label=keep_update_label,
        )
        issued = issue_credential(session, p, client_pk=client.id).secret

    manager.active = False
    audit(
        session, p, "depart", manager.name,
        shoulders=[f"{s.naan}{s.shoulder}" for s in shoulders],
        rewritten=rewritten, revoked=revoked,
    )
    return {
        "shoulders": [f"{s.naan}{s.shoulder}" for s in shoulders],
        "rewritten": rewritten,
        "revoked": revoked,
        "update_secret": issued,
    }
