"""ドメインモデル（SQLAlchemy 2.0）。

`Naan → Manager → Shoulder → Ark` の 1 本で全 NAAN を扱う。**個別 NAAN を持つ
機関でも shoulder を必ず使う**——使わないと NAAN ごとにモデルが分岐し、
first-digit 規約が NAAN によって成立したりしなかったりする。

Django 版が「構造で」守っていた不変条件は、ここでも構造で守る:

  E1  既存 ARK を黙って上書きしない
      → 採番は INSERT のみ。ORM の merge/upsert 経路を使わない（`mint()` を見よ）
  I5  条件つき unique 制約でローテーションを型として表現する
      → 部分インデックス（`postgresql_where`）
  NR  名前空間も ARK も削除しない
      → `Shoulder` / `Ark` に削除を禁じるガードを置く
  R2  監査証跡
  D3  自 NAAN の未知名は 404（`Naan.is_authoritative` で判定する）
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from arkhe.arkspec.naming import MAX_NAAN_LENGTH

#: JSONB は Postgres だけ。テストの SQLite では JSON に落とす。
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CommitmentLevel(StrEnum):
    """NMA コミットメント（対象へのサービスの約束）。

    NLM の permanence ratings を採る（自前定義しない）。`descriptive-only` だけは
    NLM の軸に無い追加で、**物理オブジェクト**に使う。
    """

    NOT_GUARANTEED = "not-guaranteed"
    PERMANENT_DYNAMIC = "permanent-dynamic"
    PERMANENT_STABLE = "permanent-stable"
    PERMANENT_UNCHANGING = "permanent-unchanging"
    DESCRIPTIVE_ONLY = "descriptive-only"


class ShoulderStatus(StrEnum):
    """shoulder の管理状態。

    **名前空間は一度配ったら取り戻せない**（NR を宣言する以上、既存 ARK は解決し
    続ける）。だから「押さえてあるが使わせない」「もう新規は採らない」を状態として
    持てるようにする。
    """

    ACTIVE = "active"
    RESERVED = "reserved"
    DELEGATED = "delegated"
    RETIRED = "retired"


class Authority(StrEnum):
    """到達範囲。**上の段は下の段を含む。**

    ARK は「中央の権威が保証する」体系ではなく、**名前空間を委譲し、各機関が
    自分の約束を自己申告する**体系。この 3 段はその委譲構造をそのまま写している。

      SYSTEM   RA の運用者。全 NAAN に届く。名前空間を配る側
      NAAN     1 つの NAAN の配下すべて。その NAAN を預かる機関の管理者
      MANAGER  1 機関ぶん。`shoulder_id` を併せて指定すれば 1 shoulder に固定できる

    **配られた側が、配った側より広く届くことはない。** 判定は `reaches()` 1 か所。
    """

    SYSTEM = "system"  # 全 NAAN（RA 運用者）
    NAAN = "naan"  # NAAN 配下の全 shoulder
    MANAGER = "manager"  # その機関の shoulder のみ


class Naan(Base):
    """Name Assigning Authority Number。

    N2: **naan は文字列**。`099999` と `99999` は別の NAAN であり、整数化してはならない。
    """

    __tablename__ = "naan"

    naan: Mapped[str] = mapped_column(String(MAX_NAAN_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    #: D3: **自分が権威を持つ NAAN の未知名は 404**（「無い」と言える）。
    #: ホスト名との文字列比較ではなくこの属性で判定する——9 NAAN 構成では権威を持つ
    #: NAAN と委譲先を持つ NAAN が同居するため、文字列では区別できない。
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=True)

    #: 権威を持たない NAAN の委譲先。`is_authoritative=False` のときだけ意味を持つ。
    redirect: Mapped[str] = mapped_column(String(500), default="")

    #: NAA ポリシー。`NP | NR, OP, CC | 2026 | <URL>`。
    na_policy: Mapped[str] = mapped_column(String(500), default="")

    #: **この NAAN の採番を外で行う場合の案内先。** 解決はここが続けることがありうる。
    #: `/.well-known/ark` で公開し、クライアントがどこへ行けばよいか分かるようにする。
    minter: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    managers: Mapped[list[Manager]] = relationship(back_populates="naan_obj")
    shoulders: Mapped[list[Shoulder]] = relationship(back_populates="naan_obj")

    __table_args__ = (
        # 権威を持たないなら転送先が要る。持つなら転送してはならない（D3）。
        CheckConstraint(
            "(is_authoritative AND redirect = '') OR (NOT is_authoritative AND redirect <> '')",
            name="naan_redirect_only_when_not_authoritative",
        ),
    )


class Manager(Base):
    """機関テナント。N2T の shoulder レコードが持つ `manager` を実体化したもの。

    **資格情報は shoulder ではなくここに紐づける**——部局別・分野別に shoulder を
    足しても鍵の再発行が要らない。
    """

    __tablename__ = "manager"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)

    #: **内部専用。公開しない。** shoulder の不透明性（N5）を壊さないため。
    name: Mapped[str] = mapped_column(String(200))

    #: mint 要求が shoulder を省略したときに使う。**全 Manager が必ず 1 つ持つ。**
    default_shoulder_id: Mapped[int | None] = mapped_column(
        ForeignKey("shoulder.id", ondelete="SET NULL"), nullable=True
    )

    commitment_level: Mapped[str] = mapped_column(
        String(32), default=CommitmentLevel.PERMANENT_DYNAMIC.value
    )
    quota_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null は無制限
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    #: **統廃合の承継先。** 管理主体が変わっても**識別子は壊さない**（`NR` を宣言して
    #: いる以上、解決は続ける）。系譜を辿れるように残す。
    succeeded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    naan_obj: Mapped[Naan] = relationship(back_populates="managers")
    default_shoulder: Mapped[Shoulder | None] = relationship(
        foreign_keys=[default_shoulder_id], post_update=True
    )
    shoulders: Mapped[list[Shoulder]] = relationship(
        back_populates="manager", foreign_keys="Shoulder.manager_id"
    )

    __table_args__ = (UniqueConstraint("naan", "name", name="uniq_manager_name_per_naan"),)


class Shoulder(Base):
    """NAAN の下位名前空間。機関への名前空間の委譲を担う。"""

    __tablename__ = "shoulder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shoulder: Mapped[str] = mapped_column(String(50))
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="CASCADE"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    #: N2T の `redirect`。**shoulder 単位の解決委譲。** `$id` / `${blade}` /
    #: 先頭の `303 ` に対応する（展開は `domain.resolution.expand_redirect`）。
    redirect: Mapped[str] = mapped_column(String(500), default="")

    #: N2T の `minter`。**採番の委譲先。** `status=delegated` のとき、mint 要求は
    #: ここへ案内する（**プロキシしない**）。
    minter: Mapped[str] = mapped_column(String(500), default="")

    status: Mapped[str] = mapped_column(
        String(16), default=ShoulderStatus.ACTIVE.value, index=True
    )
    note: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    naan_obj: Mapped[Naan] = relationship(back_populates="shoulders")
    manager: Mapped[Manager | None] = relationship(
        back_populates="shoulders", foreign_keys=[manager_id]
    )

    __table_args__ = (
        UniqueConstraint("shoulder", "naan", name="uniq_shoulder_per_naan"),
        # 委譲するなら行き先が要る。無いと mint 要求を案内できない。
        CheckConstraint(
            "status <> 'delegated' OR minter <> ''",
            name="delegated_shoulder_needs_a_minter",
        ),
    )

    @property
    def can_mint_here(self) -> bool:
        return self.status == ShoulderStatus.ACTIVE.value


class Ark(Base):
    """採番済みの ARK。

    **子リソースは採番しない。** suffix passthrough が任意の深さを賄うので、
    1 レコード 1 採番で済む。容量設計上これがいちばん効いている。
    """

    __tablename__ = "ark"

    #: `<naan>/<name>`。N2 のため naan は文字列のまま連結する。
    ark: Mapped[str] = mapped_column(String(200), primary_key=True)
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    shoulder_id: Mapped[int] = mapped_column(ForeignKey("shoulder.id"), index=True)
    assigned_name: Mapped[str] = mapped_column(String(100))

    url: Mapped[str] = mapped_column(String(2000), default="")
    commitment: Mapped[str] = mapped_column(Text, default="")
    metadata_: Mapped[str] = mapped_column("metadata", Text, default="")

    # ERC / Dublin Core（分野標準の受け皿）
    title: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(Text, default="")
    identifier: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(Text, default="")
    relation: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    who: Mapped[str] = mapped_column(Text, default="")
    when: Mapped[str] = mapped_column(Text, default="")

    # R2: 監査証跡
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(255), default="", index=True)
    updated_by: Mapped[str] = mapped_column(String(255), default="")

    shoulder: Mapped[Shoulder] = relationship()

    __table_args__ = (Index("ix_ark_shoulder_created", "shoulder_id", "created_at"),)


class Client(Base):
    """採番する主体。**API キー・自前トークン・OIDC のどれで認証しても、行き着く先はここ。**

    到達範囲（NAAN / manager / shoulder / scope）を**クライアント登録の属性として**
    持つのが要点で、トークン要求やリクエスト本文で指定させない（権限昇格を防ぐ）。
    """

    __tablename__ = "client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: 外部に見せる識別子。OAuth2 の client_id、OIDC の sub / azp に対応させる。
    client_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="CASCADE"), nullable=True, index=True
    )

    #: **到達範囲はクライアント登録の属性。トークン要求で指定させない。**
    authority: Mapped[str] = mapped_column(String(16), default=Authority.MANAGER.value)

    #: **この Client が使える shoulder を 1 つに固定する**（任意）。
    #: 同一 shoulder に複数のクライアントが採番するのは正常——web-api / worker /
    #: 一括投入バッチのように同じ名前空間を使う主体が複数いるのが普通で、
    #: **それぞれに別の資格情報を発行し、鍵を共有させない。**
    shoulder_id: Mapped[int | None] = mapped_column(
        ForeignKey("shoulder.id"), nullable=True
    )

    #: 付与する操作。登録に無い scope をトークン要求で取れてはならない。
    allowed_scopes: Mapped[str] = mapped_column(String(200), default="ark:mint")

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # `authority=naan` では必須
    label: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    manager: Mapped[Manager | None] = relationship()
    shoulder: Mapped[Shoulder | None] = relationship()
    credentials: Mapped[list[Credential]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # I5: **有効なものだけ (manager, label) で一意。** 旧を無効化して同名で
        # 新規発行できる＝ローテーションが型として表現される。
        Index(
            "uniq_active_label_per_manager",
            "manager_id",
            "label",
            unique=True,
            postgresql_where=active.is_(True),
            sqlite_where=active.is_(True),
        ),
    )


class CredentialKind(StrEnum):
    API_KEY = "api_key"  # arklet 方式。平文は発行時に一度だけ返す
    CLIENT_SECRET = "client_secret"  # OAuth2 client_credentials 用


class Credential(Base):
    """クライアントの資格情報。**平文は保存しない。**

    API キーと client_secret を 1 つの表で扱う。どちらも「発行時に一度だけ平文を
    返し、以後はハッシュ照合するだけ」で扱いが同じだから。ローテーションのために
    **1 クライアントが複数の有効な資格情報を持てる**（新旧を並行させて切り替える）。
    """

    __tablename__ = "credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_pk: Mapped[int] = mapped_column(
        ForeignKey("client.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default=CredentialKind.API_KEY.value)

    #: 照合を O(1) にするための前置き。**秘密ではない**（平文の先頭 8 文字）。
    #: これが無いと、全レコードのハッシュを総当たりすることになる（arklet はそうしていた）。
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hashed: Mapped[str] = mapped_column(String(255))

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(back_populates="credentials")


class MintReceipt(Base):
    """F4: **採番の控え。** 同じ `request_id` の再送に、前回と同じ ARK を返す。

    採番は再試行できない——ARK は `NR`（再割当てしない）を宣言する識別子で、応答が
    失われたときに再送すると**誰も指していない ARK が増える**（＝死んだ番号）。

    だが**万オーダーの投入では、途中でネットワークが切れるほうが普通**。
    **控えを持てば、再送を安全にできる。** 呼び出し側が `request_id` を付け、
    サーバは (client, request_id) で 1 行に固定する。

    **client ごとに独立。** 他機関の `request_id` と衝突しないし、鍵の推測で
    他機関の ARK を引くこともできない。
    """

    __tablename__ = "mint_receipt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), index=True)
    request_id: Mapped[str] = mapped_column(String(200))
    ark: Mapped[str] = mapped_column(ForeignKey("ark.ark"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "request_id", name="one_ark_per_request_id"),
    )


class AuditEvent(Base):
    """R2: 誰がいつ何をしたか。**`authority=naan` の操作は全件記録する。**"""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    client_id: Mapped[str] = mapped_column(String(255), index=True)
    authority: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)

    __table_args__ = (Index("ix_audit_authority_at", "authority", "at"),)


# --------------------------------------------------------------------- 削除の禁止
#
# **ARK も shoulder も消さない。**
#   ARK を消す      → 解決が止まる＝識別子が壊れる。`NR` を宣言している以上許されない。
#                     対象が失われたときは tombstone に付け替えるか、url を空にして
#                     記述を返す（FAIR A2）。
#   shoulder を消す → 乱数割当が同じ文字列を再び当てうる＝**NR 違反の芽**。機関が
#                     消えても行は残し、status=retired にする。とくに delegated
#                     だった shoulder は、外部 minter が我々の知らない識別子を作って
#                     いる可能性があるので絶対に消せない。
#
# 規約を人に守らせるのではなく、ORM 側で不可能にする。


class NotDeletable(RuntimeError):
    pass


@event.listens_for(Ark, "before_delete")
def _no_ark_delete(mapper, connection, target):  # noqa: ARG001
    raise NotDeletable(
        "ARK は削除しない（解決が止まる＝識別子が壊れる）。"
        "tombstone に付け替えるか url を空にすること。"
    )


@event.listens_for(Shoulder, "before_delete")
def _no_shoulder_delete(mapper, connection, target):  # noqa: ARG001
    raise NotDeletable(
        "shoulder は削除しない（名前空間の再利用は NR 違反）。status=retired にすること。"
    )
