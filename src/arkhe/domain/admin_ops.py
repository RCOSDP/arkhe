"""管理操作。**画面も CLI も、ここを呼ぶ。**

管理画面をテーブルの行編集にしない理由がここにある。arkhe で意味を持つのは
「組織をオンボードする」「shoulder を retire する」「委譲先を設定する」といった
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
from arkhe.auth import password as pw
from arkhe.auth.errors import Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    Authority,
    Client,
    CommitmentLevel,
    Credential,
    CredentialKind,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
    Subject,
)
from arkhe.domain.authz import Invalid, NotFound, audit


def _require_system(p: Principal) -> None:
    if not p.is_system:
        raise Forbidden("この操作はシステム管理者のみ")


def _require_naan(p: Principal, naan: str) -> None:
    """その NAAN に届くか。system は全 NAAN。"""
    if not p.reaches_naan(naan):
        raise Forbidden(f"NAAN {naan} はこの主体の範囲外")


def require_manager(session: Session, p: Principal, manager: Manager) -> None:
    """その組織に届くか。NAAN 単位以上なら配下すべて、manager 単位なら自組織のみ。

    **画面からも呼ぶので公開名にしてある。** 画面が独自に判定を書くと、
    ボタンは出ないが POST は通る、という穴になる。
    """
    _require_naan(p, manager.naan)
    if p.is_naan_wide:
        return
    if p.manager_id != manager.id:
        raise Forbidden("この組織はこの主体の範囲外")


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

    書き換えられるのは **NAAN を預かる主体だけ**。これは NAAN 配下の全組織に
    かかる宣言なので、1 組織の管理者が他組織の分まで書き換えられてはならない。
    組織が自分について述べるのは [`set_commitment`][] のほう——**NAA ポリシーは
    名前空間を配る側の宣言、コミットメントは配られた側の宣言**であり、ARK の
    委譲の構造がそのままここに出ている。
    """
    obj = session.get(Naan, naan)
    if obj is None:
        raise NotFound({"naan": naan})
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("NAA ポリシーの宣言は NAAN 単位以上の権限が要る")
    obj.na_policy = policy
    audit(session, p, "set_na_policy", naan, policy=policy)
    return obj


# ------------------------------------------------------------------ Manager


def _commitment(level: str) -> str:
    """コミットメントの語彙を検査する。

    **知らない語を通さない。** ここは `??` でそのまま公開される値なので、綴りを
    間違えたまま通ると、組織が約束していない水準を組織の名前で名乗ることになる。
    """
    try:
        return CommitmentLevel(level).value
    except ValueError:
        raise Invalid(
            {
                "commitment_level": f"{level!r} は未知の水準",
                "choices": [c.value for c in CommitmentLevel],
            }
        ) from None


def set_commitment(session: Session, p: Principal, *, manager_id: int, level: str) -> Manager:
    """組織の約束の水準を変える。

    **既定のまま放置させないための口。** これが無いと、全組織が
    `permanent-dynamic` を名乗ったまま動き、`??` はソフトウェアの既定値を
    組織の宣言として公開してしまう。宣言していないものを宣言として出すのは、
    何も出さないより悪い。

    水準を**下げる**のも正当な操作である。守れない約束を掲げ続けるより、
    実態に合わせて言い直すほうが誠実で、`??` を尋ねる意味も保たれる。
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide and manager.id != p.manager_id:
        raise Forbidden("自組織以外の約束は変えられない")
    before = manager.commitment_level
    manager.commitment_level = _commitment(level)
    audit(
        session, p, "set_commitment", str(manager_id),
        before=before, after=manager.commitment_level,
    )
    return manager


#: 認証の機構。`settings.ARKHE_AUTH` と同じ語彙を使う（別に持つとずれる）。
MECHANISMS = ("apikey", "oauth2", "oidc")


def _narrow(outer: str, inner: str) -> str:
    """外側の決まりを内側が**狭める**。広げられない。

    どちらも空白区切り。空は「制限なし」なので、**空との積は相手をそのまま**
    返す（空を「何も許さない」と読むと、既定が全面禁止になってしまう）。
    """
    if not outer:
        return inner
    if not inner:
        return outer
    return " ".join(x for x in outer.split() if x in set(inner.split()))


@dataclass(frozen=True)
class OrgPolicy:
    """組織に実際にかかっている決まり。**NAAN の既定と組織の設定を重ねた結果。**"""

    allowed_auth: str
    may_self_register: bool
    max_scopes: str


def policy_for(naan: Naan | None, manager: Manager | None) -> OrgPolicy:
    """**原則は NAAN、例外は組織。** 組織は狭めるだけで、広げられない。

    既定を NAAN 側に持たせるのは、組織が増えると 1 つずつ掛けるのが現実的で
    なくなるから。`may_self_register` は **and**——NAAN が許していなければ、
    組織の設定によらず許されない。
    """
    n_auth = naan.allowed_auth if naan else ""
    n_self = naan.may_self_register if naan else True
    n_max = naan.max_scopes if naan else ""
    if manager is None:
        return OrgPolicy(n_auth, n_self, n_max)
    return OrgPolicy(
        _narrow(n_auth, manager.allowed_auth),
        n_self and manager.may_self_register,
        _narrow(n_max, manager.max_scopes),
    )


def allowed_auth_for(
    naan: Naan | None, manager: Manager | None, enabled: tuple[str, ...] | list[str]
) -> list[str]:
    """実際に使える機構。**決まりと、構成で有効なものとの積。**"""
    allowed = policy_for(naan, manager).allowed_auth
    if not allowed:
        return list(enabled)
    return [m for m in enabled if m in set(allowed.split())]


def set_naan_policy(
    session: Session,
    p: Principal,
    *,
    naan: str,
    mechanisms: list[str] | None = None,
    may_self_register: bool | None = None,
    max_scopes: list[str] | None = None,
) -> Naan:
    """**この名前空間の決まり。** 配下の組織すべてにかかる既定。

    組織ごとの設定はここから狭めるだけ。原則をここに置くのは、組織が増えると
    1 つずつ掛けるのが現実的でなくなるから。
    """
    from arkhe.domain.authz import SCOPES

    obj = session.get(Naan, naan)
    if obj is None:
        raise NotFound({"naan": naan})
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("名前空間の決まりは NAAN 単位以上の権限が要る")

    before = {"allowed_auth": obj.allowed_auth, "may_self_register": obj.may_self_register,
              "max_scopes": obj.max_scopes}
    if mechanisms is not None:
        unknown = [m for m in mechanisms if m not in MECHANISMS]
        if unknown:
            raise Invalid({"mechanisms": f"未知の機構: {', '.join(unknown)}"})
        obj.allowed_auth = " ".join(m for m in MECHANISMS if m in mechanisms)
    if may_self_register is not None:
        obj.may_self_register = may_self_register
    if max_scopes is not None:
        unknown = [x for x in max_scopes if x not in SCOPES]
        if unknown:
            raise Invalid({"max_scopes": f"未知の scope: {', '.join(unknown)}"})
        obj.max_scopes = " ".join(x for x in SCOPES if x in max_scopes)

    audit(session, p, "set_naan_policy", naan, before=before,
          after={"allowed_auth": obj.allowed_auth,
                 "may_self_register": obj.may_self_register,
                 "max_scopes": obj.max_scopes})
    return obj


def set_org_policy(
    session: Session,
    p: Principal,
    *,
    manager_id: int,
    mechanisms: list[str] | None = None,
    may_self_register: bool | None = None,
    max_scopes: list[str] | None = None,
) -> Manager:
    """組織に何を任せ、何を制限するかを決める。**組織自身では変えられない。**

    課された制限を課された側が外せては意味がない（`set_quota` と同じ理由）。
    `None` の項目は触らない。空リストを渡すと「制限なし」になる。

      mechanisms         入り方（apikey / oauth2 / oidc）
      may_self_register  組織の管理者が自分で利用者を登録してよいか
      max_scopes         その組織の利用者に与えられる scope の上限
    """
    from arkhe.domain.authz import SCOPES

    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide:
        raise Forbidden("組織の制限を変えるには NAAN 単位以上の権限が要る")

    before = {
        "allowed_auth": manager.allowed_auth,
        "may_self_register": manager.may_self_register,
        "max_scopes": manager.max_scopes,
    }
    if mechanisms is not None:
        unknown = [m for m in mechanisms if m not in MECHANISMS]
        if unknown:
            raise Invalid({"mechanisms": f"未知の機構: {', '.join(unknown)}",
                           "choices": list(MECHANISMS)})
        manager.allowed_auth = " ".join(m for m in MECHANISMS if m in mechanisms)
    if may_self_register is not None:
        manager.may_self_register = may_self_register
    if max_scopes is not None:
        unknown = [x for x in max_scopes if x not in SCOPES]
        if unknown:
            raise Invalid({"max_scopes": f"未知の scope: {', '.join(unknown)}",
                           "choices": list(SCOPES)})
        manager.max_scopes = " ".join(x for x in SCOPES if x in max_scopes)

    audit(session, p, "set_org_policy", str(manager_id), before=before,
          after={"allowed_auth": manager.allowed_auth,
                 "may_self_register": manager.may_self_register,
                 "max_scopes": manager.max_scopes})
    return manager


def set_quota(
    session: Session, p: Principal, *, manager_id: int, quota_per_day: int | None
) -> Manager:
    """1 日あたりの採番上限を変える。`None` で無制限。

    **自組織では変えられない**（`set_commitment` と違うところ）。上限は配った側が
    配られた側に課すものなので、課された側が自分で外せては意味がない。
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide:
        raise Forbidden("採番上限の変更は NAAN 単位以上の権限が要る")
    if quota_per_day is not None and quota_per_day < 0:
        raise Invalid({"quota_per_day": "負の上限は置けない（無制限にするなら空にする）"})
    before = manager.quota_per_day
    manager.quota_per_day = quota_per_day
    audit(session, p, "set_quota", str(manager_id), before=before, after=quota_per_day)
    return manager


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
    """組織を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。**

    組織だけ作って shoulder が無い状態は、採番できない組織を生むだけで意味がない。
    `default_shoulder` もここで結ぶ（無いと shoulder 省略の採番が落ちる）。
    """
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("組織のオンボードは NAAN 単位以上の権限が要る")
    if session.get(Naan, naan) is None:
        raise NotFound({"naan": naan})
    if session.scalar(select(Manager).where(Manager.naan == naan, Manager.name == name)):
        raise Invalid({"name": f"{naan} に組織 {name} は登録済み"})

    manager = Manager(naan=naan, name=name)
    if commitment_level:
        manager.commitment_level = _commitment(commitment_level)
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
    続ける。系譜を辿れるように、旧組織の行は残したまま承継先を指す。
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    require_manager(session, p, manager)
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
    subject_type: str = Subject.MACHINE.value,
) -> Client:
    """主体を登録する。**自分より広い到達範囲は与えられない。**

    `subject_type` で名乗れる経路が決まる:

      machine  資格情報（API キー / client_secret）で名乗る。外部ログインでは名乗れない
      person   外部の認可サーバやプロキシが身元を保証する。資格情報を持てない

    分けているのは、前段のヘッダで**機械用の主体を名乗られないようにする**ため。
    `client_id` には、person なら認可サーバが返す識別子（メールや eppn）を入れる。
    """
    _require_naan(p, naan)
    if shoulder_id is not None:
        # **shoulder は既に組織を決めている。** 別々に渡させると、片方だけ書いた
        # 主体ができて認可の入口（manager が active か）で必ず弾かれる——
        # しかも「shoulder は合っているのに通らない」という分かりにくい形で。
        sh = session.get(Shoulder, shoulder_id)
        if sh is None or sh.naan != naan:
            raise Invalid({"shoulder_id": f"shoulder {shoulder_id} は NAAN {naan} のものでない"})
        if manager_id is None:
            manager_id = sh.manager_id
        elif manager_id != sh.manager_id:
            raise Invalid({"shoulder_id": "shoulder の所属組織と manager が食い違う"})
    target = Authority(authority)
    if target is Authority.SYSTEM:
        _require_system(p)
    elif target is Authority.NAAN and not p.is_naan_wide:
        raise Forbidden("authority=naan の主体を作るには NAAN 単位以上の権限が要る")
    if not p.is_naan_wide and manager_id != p.manager_id:
        raise Forbidden("自組織以外の主体は作れない")
    org = session.get(Manager, manager_id) if manager_id else None
    policy = policy_for(session.get(Naan, naan), org)
    # **任せていなければ、配る側を通す。** 自分で増やせるかは配る側が決める。
    if not p.is_naan_wide and not policy.may_self_register:
        raise Forbidden("この組織では利用者の登録が許されていない（NAAN 管理者に依頼する）")
    # **上限は誰が作るかによらず効く。** 例外を作るなら上限のほうを動かす
    # ——さもないと、宣言した上限を超える主体が台帳に並ぶ。
    if policy.max_scopes:
        over = set(scopes.split()) - set(policy.max_scopes.split())
        if over:
            raise Invalid(
                {"scopes": f"上限を超えている: {' '.join(sorted(over))}",
                 "max_scopes": policy.max_scopes}
            )
    if session.scalar(select(Client).where(Client.client_id == client_id)):
        raise Invalid({"client_id": f"{client_id} は登録済み"})
    if target is Authority.NAAN and expires_at is None:
        # break-glass は**期限を必須**にする。恒久的な万能鍵を作らせない。
        raise Invalid({"expires_at": "authority=naan の主体には期限が要る"})

    client = Client(
        client_id=client_id,
        subject_type=Subject(subject_type).value,
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
    audit(
        session, p, "register_client", client_id,
        authority=target.value, subject_type=subject_type,
    )
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
    if client.subject_type != Subject.MACHINE:
        # 人の身元は外部が保証する。arkhe に鍵を持たせると、外部で失効させても
        # その鍵で入れてしまう。
        raise Invalid(
            {"subject_type": "人の主体には資格情報を発行しない（身元は外部が保証する）"}
        )
    # **許された機構の鍵しか出さない。** 出せてしまうと、制限が宣言だけになる。
    manager = session.get(Manager, client.manager_id) if client.manager_id else None
    policy = policy_for(session.get(Naan, client.naan), manager)
    if policy.allowed_auth:
        need = "apikey" if kind == CredentialKind.API_KEY else "oauth2"
        if need not in policy.allowed_auth.split():
            raise Invalid(
                {"kind": f"{need} は許されていない（許可: {policy.allowed_auth}）"}
            )

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


def set_password(session: Session, p: Principal, *, client_pk: int, password: str) -> Credential:
    """人の主体にパスワードを設定する（既にあれば置き換える）。

    **人にしか設定しない。** 機械はパスワードを覚えないし、覚えさせると
    「どこかに書き留められた鍵」が増えるだけになる。

    置き換えのときは**古い行を無効にして新しい行を足す**——いつ変えたかが残る。
    """
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("この主体はこの管理者の範囲外")
    if client.subject_type != Subject.PERSON:
        raise Invalid({"subject_type": "パスワードは人の主体にだけ設定できる"})

    try:
        hashed = pw.hash_password(password)
    except pw.WeakPassword as exc:
        raise Invalid({"password": str(exc)}) from exc

    for old in session.scalars(
        select(Credential).where(
            Credential.client_pk == client.id,
            Credential.kind == CredentialKind.PASSWORD,
            Credential.active.is_(True),
        )
    ):
        old.active = False

    cred = Credential(
        client_pk=client.id, kind=CredentialKind.PASSWORD.value,
        prefix="", hashed=hashed, label="password",
    )
    session.add(cred)
    session.flush()
    audit(session, p, "set_password", client.client_id)
    return cred


def set_client_active(
    session: Session, p: Principal, *, client_pk: int, active: bool
) -> Client:
    """主体を止める／戻す。**行は消さない。**

    **認可サーバに寄せた構成では、これが arkhe 側の唯一の止め方になる。**
    `oidc` では資格情報を arkhe が持たないので `revoke_credential` は効かず、
    ここを落とさない限り、認可サーバが出し続けるトークンで通ってしまう。

    止める側が 2 つあるのは弱点ではなく利点である:

      認可サーバ  トークンを出さなくする（他の資源にも一斉に効く）
      arkhe       この名前空間に入れなくする（他の資源には影響しない）

    **戻せるのは、その組織が生きている間だけ。** 離脱・統合で止まった主体を
    個別に戻せると、「新規採番は止める」という宣言が骨抜きになる。
    """
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("この主体はこの管理者の範囲外")
    if active and client.manager_id is not None:
        manager = session.get(Manager, client.manager_id)
        if manager is not None and not manager.active:
            raise Invalid(
                {"active": "去った組織の主体は戻せない（組織の承継・離脱を先に解く）"}
            )
    client.active = active
    audit(session, p, "enable_client" if active else "disable_client", client.client_id)
    return client


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
    """統廃合。**旧組織の名前空間を承継先に移す。**

    shoulder ごと移すので、既存 ARK の `shoulder_id` は変わらない＝**識別子も
    解決先も無傷**。変わるのは「その名前空間を今後誰が預かるか」だけ。

    `retire=True` なら移した shoulder の新規採番を止める（既存は解決し続ける）。
    承継先が自分の shoulder で採番を続け、旧名前空間は読み取り専用になる形。
    """
    pre = session.get(Manager, predecessor_id)
    suc = session.get(Manager, successor_id)
    if pre is None or suc is None:
        raise NotFound({"manager": [predecessor_id, successor_id]})
    require_manager(session, p, pre)
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
    # 旧組織の資格情報は止める。**行は消さない**（誰の鍵だったかを残す）。
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
    """**組織が離れる**（組織は存続する。統廃合とは別）。

    核心は 1 点——**新規採番は止めるが、解決は永久に続ける。**
    `ark:/<この NAAN>/…` という形で配った以上、振り直せないので、NAAN の保有者が
    302 を返し続けるしかない。

    **`resolver_template` を渡すのが推奨。** 既存 ARK の転送先を組織のリゾルバへ
    一括で向け直し、shoulder にも同じ委譲を設定する。**これで以後の運用が組織側に
    閉じる**——離れた組織に「移転のたびに我々へ更新を投げる」作業を強いない。
    継続作業を要求する形にすると、放置されて死んだリンクが残る。

    テンプレートは `Shoulder.redirect` と同じ記法（`$id` / `${blade}`）。
    例: ``https://repo.univ.ac.jp/ark/${blade}``
    """
    from arkhe.domain.resolution import expand_redirect

    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    require_manager(session, p, manager)

    shoulders = list(manager.shoulders)
    rewritten = 0
    if resolver_template:
        ids = [sh.id for sh in shoulders]
        for sh in shoulders:
            sh.redirect = resolver_template  # 未登録の名前も組織のリゾルバへ
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
