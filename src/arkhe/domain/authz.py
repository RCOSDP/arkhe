"""認可の中核。**shoulder はリクエストで受け取らず主体から引く。**

これ 1 点で、越境（R1）と多数組織の振り分けが同時に片づく。arklet は
`{naan, shoulder}` を本文で受けて NAAN 単位でしか認可していなかったため、
**設定ミスでも詐称でも他組織の名前空間に採番できた**。

認証機構（apikey / oauth2 / oidc）が何であっても、判断はここ 1 か所に集まる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from arkhe import errors
from arkhe.auth.errors import Forbidden, InsufficientScope
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    ArkChange,
    AuditEvent,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
    UnknownSubject,
)
from arkhe.errors import ApiError


class NotFound(ApiError):
    status = 404


class Invalid(ApiError):
    status = 400


class Throttled(ApiError):
    status = 429


class ShoulderDelegated(Forbidden):
    """**採番はここではなく外部 minter で行う。** 行き先を添えて返す。

    プロキシしない——プロキシすると (1) 名前空間を誰が消費したか二重管理になり、
    (2) 応答が失われたとき**誰も指していない ARK** が両側に残りうる。ARK は
    NR を宣言する識別子なので、それは取り返しがつかない。
    """

    def __init__(self, shoulder: Shoulder):
        self.minter = shoulder.minter
        if shoulder.minter:
            # **機械が叩ける口がある。** 307 で案内し、代理では呼ばない。
            super().__init__(
                errors.SHOULDER_DELEGATED,
                shoulder=shoulder.shoulder,
                minter=shoulder.minter,
                note=shoulder.note,
            )
        else:
            # **叩ける口が無い**（閉域など）。307 で人向けのページへ送ると、
            # クライアントはそこへ POST しにいく——**403 で止め、案内は本文に置く**。
            super().__init__(
                errors.SHOULDER_DELEGATED_UNREACHABLE,
                shoulder=shoulder.shoulder,
                about=shoulder.about,
                note=shoulder.note,
            )


#: arkhe が実際に検査する scope。**ここが語彙の全体。**
#: 画面の選択肢も認可サーバに登録する client scope も、これに揃える——
#: 散らばると「登録できるのに検査されない scope」が生まれる。
SCOPES = ("ark:mint", "ark:update", "ark:read", "ark:tombstone", "ark:hold", "ark:import")


def require_scope(principal: Principal, scope: str) -> None:
    if not principal.has(scope):
        raise InsufficientScope(scope)


def shoulder_for(session: Session, principal: Principal, requested: str | None) -> Shoulder:
    """この主体が採番に使える shoulder を決める。

    **リクエストの `shoulder` は任意。** 省略時は manager の `default_shoulder`。
    指定された場合は**その主体の到達範囲に含まれるかを検証する**だけで、範囲を
    広げる手段にはしない。
    """
    if principal.is_naan_wide:
        # NAAN 配下（system は全 NAAN）ならどれでも使えるが、**明示が必須**
        # ——既定を持たないので、誤って他組織の shoulder に打つ事故を防ぐ。
        if not requested:
            raise Invalid(errors.SHOULDER_REQUIRED, authority=principal.authority)
        stmt = select(Shoulder).where(Shoulder.shoulder == requested)
        if not principal.is_system:
            stmt = stmt.where(Shoulder.naan == principal.naan)
        found = session.scalars(stmt).all()
        if not found:
            raise Invalid(errors.SHOULDER_UNKNOWN, shoulder=requested)
        if len(found) > 1:
            # system は全 NAAN に届くので、同じ shoulder 文字列が複数 NAAN に
            # ありうる。**どれか 1 つを勝手に選ばない。**
            raise Invalid(
                errors.SHOULDER_AMBIGUOUS,
                shoulder=requested,
                naans=sorted(x.naan for x in found),
            )
        return found[0]

    if principal.manager_id is None:
        raise Forbidden(errors.NO_ORGANISATION)
    manager = session.get(Manager, principal.manager_id)
    if manager is None or not manager.active:
        raise Forbidden(errors.NO_ORGANISATION)

    # **主体が shoulder に固定されている場合はそれだけ。**
    # 同じ shoulder を複数の主体が使うのは正常（鍵は共有しない）。
    if principal.shoulder_id is not None:
        fixed = session.get(Shoulder, principal.shoulder_id)
        if fixed is None:
            raise Forbidden(errors.NO_ORGANISATION, shoulder_id=principal.shoulder_id)
        if requested and requested != fixed.shoulder:
            raise Forbidden(errors.OUT_OF_REACH, target=requested)
        return fixed

    if not requested:
        if manager.default_shoulder_id is None:
            raise Invalid(errors.NO_DEFAULT_SHOULDER)
        return session.get(Shoulder, manager.default_shoulder_id)

    found = session.scalar(
        select(Shoulder).where(
            Shoulder.naan == principal.naan,
            Shoulder.shoulder == requested,
            Shoulder.manager_id == manager.id,
        )
    )
    if found is None:
        # **他組織の shoulder を指定しても、存在の有無を漏らさず一律に拒む。**
        raise Forbidden(errors.OUT_OF_REACH, target=requested)
    return found


def assert_reaches_shoulder(session: Session, principal: Principal, shoulder: Shoulder) -> None:
    """**既に特定できている shoulder**に、この主体が手を入れてよいか。

    `shoulder_for` は「名前から shoulder を選ぶ」口で、こちらは「選ばれた
    shoulder を認可する」口。**判定の中身は同じ**——上位の権威は下位を覆う:

      system  … 全 NAAN・全 shoulder
      naan    … その NAAN の下の全 shoulder
      manager … 自組織の shoulder だけ
      shoulder に固定された主体 … その 1 つだけ

    分けてあるのは、取り込み（`import_minted`）が**名前から shoulder を決める**
    ため。`shoulder_for` の探し方（shoulder 文字列で全 NAAN を検索）だと、
    同じ綴りの shoulder が複数 NAAN にあるときに曖昧になる——取り込みは ARK が
    NAAN を持っているので、**曖昧になりようがない引き方**をしてから認可する。
    """
    if not principal.reaches_naan(shoulder.naan):
        raise Forbidden(errors.OUT_OF_REACH, target=shoulder.naan)
    if principal.is_naan_wide:
        return
    if principal.shoulder_id is not None:
        if principal.shoulder_id != shoulder.id:
            raise Forbidden(errors.OUT_OF_REACH, target=shoulder.shoulder)
        return
    if principal.manager_id is None or shoulder.manager_id != principal.manager_id:
        # **存在の有無を漏らさず一律に拒む**（`shoulder_for` と同じ扱い）。
        raise Forbidden(errors.OUT_OF_REACH, target=shoulder.shoulder)


def assert_naan_is_ours(session: Session, naan: str) -> None:
    """**この台帳が権威を持つ NAAN か。**

    取り込みは「この名前の記録を引き受ける」と宣言する操作なので、
    **取り次いでいるだけの NAAN に対して行ってはいけない**——他所の名前空間の
    保管者を名乗ることになる。主体の到達範囲とは別の話で、両方要る。
    """
    row = session.get(Naan, naan)
    if row is None or not row.is_authoritative:
        raise Forbidden(errors.IMPORT_NAAN_NOT_AUTHORITATIVE, naan=naan)


def assert_shoulder_mintable(shoulder: Shoulder) -> None:
    """**リザーブ枠・委譲・引退した shoulder では採番しない。**"""
    if shoulder.status == ShoulderStatus.ACTIVE:
        return
    if shoulder.status == ShoulderStatus.DELEGATED:
        raise ShoulderDelegated(shoulder)
    raise Forbidden(
        errors.SHOULDER_NOT_MINTABLE,
        shoulder=shoulder.shoulder,
        status=shoulder.status,
        note=shoulder.note,
    )


def assert_may_touch(session: Session, principal: Principal, ark: Ark) -> None:
    """既存 ARK に触れてよいか。

    M3: **arklet の `update` は shoulder を参照すらしていなかった**ため、同一 NAAN
    内の任意の ARK の解決先を書き換えられた。採番より重い——**永続識別子の乗っ取り**。
    """
    if not principal.reaches_naan(ark.naan):
        raise Forbidden(errors.OUT_OF_REACH, target=ark.ark, reason="another NAAN")
    if principal.is_naan_wide:
        return
    shoulder = ark.shoulder or session.get(Shoulder, ark.shoulder_id)
    if principal.manager_id is None or shoulder.manager_id != principal.manager_id:
        raise Forbidden(errors.OUT_OF_REACH, target=ark.ark)


def visible_arks(session: Session, principal: Principal, keys: list[str]):
    """M4: 読み取りも到達範囲に絞る。"""
    stmt = select(Ark).where(Ark.ark.in_(keys)).options(selectinload(Ark.shoulder))
    if not principal.is_system:
        stmt = stmt.where(Ark.naan == principal.naan)
    if not principal.is_naan_wide:
        stmt = stmt.join(Shoulder, Ark.shoulder_id == Shoulder.id).where(
            Shoulder.manager_id == principal.manager_id
        )
    return session.scalars(stmt).all()


def fetch_for_update(session: Session, principal: Principal, keys: list[str]) -> dict[str, Ark]:
    """M5: **ARK をキーにした辞書で引き当てる。**

    arklet は順序不定の queryset を入力と `zip` しており、**別の ARK に他レコードの
    値を書き込みうる**データ破壊バグがあった。件数が一致しない場合も黙って
    切り詰められていた。

    **1 件でも欠けるか範囲外なら全体を失敗させる**（部分適用しない）。
    """
    found = {a.ark: a for a in visible_arks(session, principal, keys)}
    missing = [k for k in keys if k not in found]
    if missing:
        raise NotFound(errors.ARK_NOT_FOUND, missing=missing[:20], count=len(missing))
    return found


def assert_within_quota(session: Session, principal: Principal, count: int = 1) -> None:
    """R3: 組織単位の 1 日あたり採番上限。**一組織の暴走を止める。**

    `Manager.quota_per_day` が null なら無制限。break-glass は manager を持たない
    ので対象外——障害対応で止まっては困る。
    """
    if principal.manager_id is None:
        return
    manager = session.get(Manager, principal.manager_id)
    if manager is None or manager.quota_per_day is None:
        return
    since = datetime.now(UTC) - timedelta(days=1)
    used = session.scalar(
        select(func.count())
        .select_from(Ark)
        .join(Shoulder, Ark.shoulder_id == Shoulder.id)
        .where(Shoulder.manager_id == manager.id, Ark.created_at >= since)
    )
    if used + count > manager.quota_per_day:
        raise Throttled(
            errors.QUOTA_EXCEEDED, quota=manager.quota_per_day, used=used, requested=count
        )


def record_sign_in(
    session: Session,
    *,
    action: str,
    client_id: str,
    authority: str = "",
    ip: str = "",
    mechanism: str = "",
    ok: bool = True,
    **detail,
) -> None:
    """入退室を残す。**到達範囲で間引かない。**

    `audit()` は NAAN 単位以上の操作だけを残すが、**入退室は誰のものでも残す**。
    「誰がいつ入ったか」は、その人が何をしたかと同じくらい後から要る——
    とくに**失敗したログイン**は、成功したものより先に見たい記録である。

    主体が特定できない失敗（無い ID、間違ったパスワード）も残す。ただし
    **打ち込まれた値をそのまま残さない**——ログが利用者名の一覧になるのは
    避けたいので、あるのは「その ID で失敗した」という事実だけにする。
    """
    session.add(
        AuditEvent(
            client_id=client_id,
            authority=authority,
            action=action,
            target="",
            ip=ip,
            detail={**detail, "mechanism": mechanism, "ok": ok},
        )
    )


def record_unknown_subject(
    session: Session, *, subject: str, issuer: str = "", ip: str = ""
) -> None:
    """認可サーバから来たが登録の無い主体を残す。**同じ主体で行を増やさない。**

    `client_id` の綴り違いは、認可サーバに寄せた構成でいちばん多い詰まりどころ
    である。**弾いた瞬間に正しい文字列は手元にある**（`azp` は署名検証を通って
    いる）ので、捨てずに残せば運用者は打ち直さずに登録できる。

    回数を数えるのは、**1 回きりなら打ち間違い、何度も来るなら設定が生きている**
    からで、直す優先度がそれで分かる。行が増え続けることはない——認可サーバに
    実在する client の数で頭打ちになる。

    登録が済んだ行を消す処理は要らない。一覧は**登録の無いものだけ**を毎回
    引き直すので、登録すればひとりでに消える。
    """
    row = session.scalar(
        select(UnknownSubject).where(
            UnknownSubject.subject == subject, UnknownSubject.issuer == issuer
        )
    )
    if row is None:
        session.add(UnknownSubject(subject=subject, issuer=issuer, ip=ip))
        return
    row.last_seen = datetime.now(UTC)
    row.seen += 1
    row.ip = ip or row.ip


def record_change(
    session: Session, principal: Principal, ark: Ark, *, action: str, before_url: str
) -> None:
    """ARK の行き先が変わったことを残す。**誰が行っても残す。**

    `audit()` と違って到達範囲で間引かない——採番も付け替えも組織が行うので、
    間引くと**肝心の変更が落ちる**。`NR` を宣言する体系で「この識別子は変わらない」
    と言うなら、変えたのは何でいつ誰がやったのかを示せなければならない。
    """
    if before_url == ark.url and action == "update":
        return  # 行き先が変わっていないなら、履歴に残すことは無い
    session.add(
        ArkChange(
            ark=ark.ark,
            action=action,
            before_url=before_url,
            after_url=ark.url,
            by=principal.client_id,
            ip=principal.ip,
        )
    )


def audit(session: Session, principal: Principal, action: str, target: str = "", **detail) -> None:
    """R2: **NAAN 以上に届く操作は全件記録する。**

    届く範囲が広いほど、後から「誰が何をしたか」を辿れる必要が高い。
    system は全 NAAN に届くので当然含める。
    """
    if not principal.is_naan_wide:
        return
    session.add(
        AuditEvent(
            client_id=principal.client_id,
            authority=principal.authority,
            action=action,
            target=target,
            ip=principal.ip,
            detail={**detail, "mechanism": principal.mechanism},
        )
    )
