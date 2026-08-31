"""ドメインモデル（SQLAlchemy 2.0）。

`Naan → Manager → Shoulder → Ark` の 1 本で全 NAAN を扱う。**個別 NAAN を持つ
組織でも shoulder を必ず使う**——使わないと NAAN ごとにモデルが分岐し、
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

    ARK は「中央の権威が保証する」体系ではなく、**名前空間を委譲し、各組織が
    自分の約束を自己申告する**体系。この 3 段はその委譲構造をそのまま写している。

      SYSTEM   RA の運用者。全 NAAN に届く。名前空間を配る側
      NAAN     1 つの NAAN の配下すべて。その NAAN を預かる組織の管理者
      MANAGER  1 組織ぶん。`shoulder_id` を併せて指定すれば 1 shoulder に固定できる

    **配られた側が、配った側より広く届くことはない。** 判定は `reaches()` 1 か所。
    """

    SYSTEM = "system"  # 全 NAAN（RA 運用者）
    NAAN = "naan"  # NAAN 配下の全 shoulder
    MANAGER = "manager"  # その組織の shoulder のみ


class HoldMixin:
    """**転送の一時停止。** 解決は止めない——止めるのは転送だけ。

    委譲先のリゾルバが落ちた、間違った行き先を配ってしまった、機密が漏れて
    取り下げを求められた、対象が移動中——**どれも急いで止めたいが、識別子を
    殺したくない**。`404` は嘘（その識別子は存在する）で、`503` は識別子が
    壊れて見える。だから `200` と記述を返す経路（D6・tombstone と同じ）に乗せる。

    tombstone との違いは意味と可逆性である:

      tombstone  **対象が失われた。** 恒久。元の行き先は捨てる
      hold       **対象は在るが、今は行き先を出せない。** 期限つき。元の行き先は残す

    **期限は必須。**「一時的」を人の記憶に頼ると恒久化する。そして**期限切れを
    バッチで戻さない**——解決のたびに時計で見るので、戻し忘れが起きない
    （`domain.resolution.hold_of`）。
    """

    #: **これを過ぎたら効かない。** null は保留していない。
    hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    #: 止めている理由。**公開の口（`?info` / `?json`）に出る**ので、機微を書かない。
    hold_reason: Mapped[str] = mapped_column(String(500), default="")
    hold_by: Mapped[str] = mapped_column(String(255), default="")


class Naan(Base, HoldMixin):
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

    #: **この名前空間の決まり。** 配下の組織すべてにかかる既定で、組織ごとの
    #: 設定はここから**狭めるだけ**（広げられない）。
    #:
    #: 既定を NAAN 側に持たせるのは、**組織が増えると 1 つずつ掛けるのが
    #: 現実的でなくなる**から。800 機関に同じ制限を入れて回る運用は成立しない。
    #: 組織ごとの設定は例外を刻むためのもので、原則はここにある。
    allowed_auth: Mapped[str] = mapped_column(String(100), default="")
    may_self_register: Mapped[bool] = mapped_column(Boolean, default=True)
    max_scopes: Mapped[str] = mapped_column(String(200), default="")

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
    """組織テナント。N2T の shoulder レコードが持つ `manager` を実体化したもの。

    **資格情報は shoulder ではなくここに紐づける**——部局別・分野別に shoulder を
    足しても鍵の再発行が要らない。
    """

    __tablename__ = "manager"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)

    #: **内部専用。公開しない。** shoulder の不透明性（N5）を壊さないため。
    name: Mapped[str] = mapped_column(String(200))

    #: mint 要求が shoulder を省略したときに使う。**全 Manager が必ず 1 つ持つ。**
    #:
    #: `manager → shoulder → manager` の**循環参照**になる。PostgreSQL は
    #: CREATE TABLE の時点で参照先を要求するので、そのままでは作成順が決まらない。
    #: `use_alter` で「両方できてから ALTER で足す」形にし、名前も付ける
    #: （名前が無いと落とせない）。**SQLite では見えない問題**なので、
    #: 移行の検証は Postgres で行うこと。
    default_shoulder_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "shoulder.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_manager_default_shoulder",
        ),
        nullable=True,
    )

    commitment_level: Mapped[str] = mapped_column(
        String(32), default=CommitmentLevel.PERMANENT_DYNAMIC.value
    )
    quota_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null は無制限

    #: **この組織に許す認証の機構。** 空白区切り。空なら構成の既定（`ARKHE_AUTH`）。
    #:
    #: 名前空間を配る側が、配られた側の**入り方まで決められる**ようにするもの。
    #: 「うちの NAAN では機関は認可サーバ経由でしか入れない」を、機関ごとの設定
    #: ではなく**配る側の宣言**として持てる。組織自身では変えられない
    #: （課された制限を課された側が外せては意味がない——`quota_per_day` と同じ）。
    #:
    #: **発行時だけでなく認証時にも効く。** 発行を止めるだけだと、制限を掛ける前に
    #: 出した鍵が生き残り、「制限した」と思っているのに通り続ける。
    allowed_auth: Mapped[str] = mapped_column(String(100), default="")

    #: **組織の管理者が自分で利用者を登録してよいか。**
    #:
    #: 名前空間を配る側が、配られた側にどこまで任せるかを決める。任せない運用では
    #: 「利用者を増やしたい」を配る側に依頼させる——小さな NAAN では現実的で、
    #: 誰が入れるかを一手に把握できる。
    may_self_register: Mapped[bool] = mapped_column(Boolean, default=True)

    #: **この組織の利用者に与えられる scope の上限。** 空白区切り。空なら制限なし。
    #:
    #: 上限であって既定ではない。`ark:tombstone` を配る側だけの操作にしておく、
    #: といった使い方をする。**組織自身では上げられない**（上げられる上限は上限
    #: ではない）。誰が作った利用者かによらず効く——例外を作るなら上限のほうを
    #: 動かす。宣言と実態がずれないようにするため。
    max_scopes: Mapped[str] = mapped_column(String(200), default="")
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


class Shoulder(Base, HoldMixin):
    """NAAN の下位名前空間。組織への名前空間の委譲を担う。"""

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


class Ark(Base, HoldMixin):
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


class Subject(StrEnum):
    """主体の種別。**人と機械を分ける。**

    分けないと、前段の認証プロキシが立てるヘッダ（`X-Forwarded-User`）で
    **機械用のクライアントを名乗れてしまう**。プロキシを正しく置けば防げるが、
    設定 1 つの誤りが「一括投入バッチとして全件書き換え」に化けるのは脆い。

      machine  資格情報（API キー / client_secret）で名乗る。**外部ログインでは名乗れない**
      person   外部の認可サーバやプロキシが身元を保証する。**資格情報を持てない**
    """

    MACHINE = "machine"
    PERSON = "person"


class Client(Base):
    """主体。**API キー・自前トークン・OIDC のどれで認証しても、行き着く先はここ。**

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

    #: 人か機械か。**この 1 列が、名乗れる経路を分ける**（`Subject` を見よ）。
    subject_type: Mapped[str] = mapped_column(String(16), default=Subject.MACHINE.value)

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
        #
        # **空のラベルは制約の外。** 空は「名前を付けていない」であって、名前が
        # 衝突しているのではない。含めると、1 組織にラベル無しの主体を 2 つ置け
        # なくなる（web-api / web-ui / worker のように役割で分ける普通の構成が
        # 通らない）。
        Index(
            "uniq_active_label_per_manager",
            "manager_id",
            "label",
            unique=True,
            postgresql_where=active.is_(True) & (label != ""),
            sqlite_where=active.is_(True) & (label != ""),
        ),
    )


class CredentialKind(StrEnum):
    """資格情報の種別。**人が持てるのはパスワードだけ。**

    API キーと client_secret は機械のもの——人に配ると、その人が組織を離れても
    鍵が生き残る。逆にパスワードは機械に持たせない（覚える主体がいない）。
    """

    API_KEY = "api_key"  # arklet 方式。平文は発行時に一度だけ返す
    CLIENT_SECRET = "client_secret"  # OAuth2 client_credentials 用
    PASSWORD = "password"  # 管理画面へのローカルログイン（人のみ）


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

    #: **総当たりを止める。** ログイン画面を出す以上、これが無いと辞書攻撃に
    #: 素で晒される。API キーは 256 bit の乱数なので対象外だが、人が決める
    #: パスワードは推測されうる。
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    client: Mapped[Client] = relationship(back_populates="credentials")


class MintReceipt(Base):
    """F4: **採番の控え。** 同じ `request_id` の再送に、前回と同じ ARK を返す。

    採番は再試行できない——ARK は `NR`（再割当てしない）を宣言する識別子で、応答が
    失われたときに再送すると**誰も指していない ARK が増える**（＝死んだ番号）。

    だが**万オーダーの投入では、途中でネットワークが切れるほうが普通**。
    **控えを持てば、再送を安全にできる。** 呼び出し側が `request_id` を付け、
    サーバは (client, request_id) で 1 行に固定する。

    **client ごとに独立。** 他組織の `request_id` と衝突しないし、鍵の推測で
    他組織の ARK を引くこともできない。
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


class ArkChange(Base):
    """ARK の**行き先が変わった記録**。

    ここが無いと、**以前どこを指していたかを復元できない。** `NR`（振り直さない）
    を宣言する体系で「この識別子は変わらない」と言うなら、変えたのは何であって
    いつ誰が変えたのかを示せなければならない——さもないと、**約束を検証する手段が
    利用者の側に無い。**

    監査ログとは別に持つ理由が 2 つある:

      監査は NAAN 単位以上の操作だけを残す。**採番も付け替えも組織が行う**ので、
      監査だけでは肝心の変更が落ちる（`authz.audit` の R2）。

      監査は運用者のためのもので、これは**識別子そのものの履歴**。保存期間も
      切り出し方も違う（監査は間引けるが、こちらは間引けない）。

    行は**足すだけ**。消さない——消せる履歴は履歴ではない。
    """

    __tablename__ = "ark_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ark: Mapped[str] = mapped_column(ForeignKey("ark.ark"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    #: `update` か `tombstone`。**意味が違うので分けて残す**
    #: （転送先の付け替えと「対象が失われた」の宣言は別のこと）。
    action: Mapped[str] = mapped_column(String(16))

    #: 変える前の行き先。**これが復元したいもの。**
    before_url: Mapped[str] = mapped_column(String(2000), default="")
    after_url: Mapped[str] = mapped_column(String(2000), default="")

    by: Mapped[str] = mapped_column(String(255), default="", index=True)
    ip: Mapped[str] = mapped_column(String(45), default="")


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

    #: 接続元のアドレス。**前段を信じた結果**であって、証拠ではない
    #: （`ARKHE_TRUSTED_PROXIES` を 0 にしていれば、直接の接続元そのもの）。
    ip: Mapped[str] = mapped_column(String(45), default="", index=True)

    __table_args__ = (Index("ix_audit_authority_at", "authority", "at"),)


class UnknownSubject(Base):
    """認可サーバから来たが、台帳に登録の無い主体。

    **綴りが 1 文字違うと黙って 401 になる。** その 1 文字を、arkhe は弾いた
    瞬間に手に持っている——`azp` はもう署名検証を通っている。捨てずに残せば、
    運用者は打ち直さずに登録できる。

    残すのは**認可サーバが署名した値だけ**である。ログイン欄に打たれた文字列は
    残さない（`record_sign_in` の方針）が、ここは事情が違う——攻撃者が仕込める
    値ではないし、これを見せないと typo の切り分け手段が運用者の側に無い。

    **どの組織のものかは分からない。** トークンにその情報は無く、推測もしない。
    だから見えるのは NAAN 以上に届く主体だけにしてある——組織単位の管理者に
    見せると、他組織の client_id が混ざって出る。
    """

    __tablename__ = "unknown_subject"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: `azp` → `client_id` → `sub` の順で採った、認可サーバ側の識別子。
    subject: Mapped[str] = mapped_column(String(255), index=True)
    issuer: Mapped[str] = mapped_column(String(500), default="")

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    #: 何回来たか。**1 回なら間違い、何度も来るなら設定が生きている**——
    #: 直す優先度がこれで分かる。
    seen: Mapped[int] = mapped_column(Integer, default=1)
    ip: Mapped[str] = mapped_column(String(45), default="")

    #: **同じ主体で行を増やさない。** 認可サーバの client 数で頭打ちになる。
    __table_args__ = (UniqueConstraint("subject", "issuer", name="uq_unknown_subject"),)


# --------------------------------------------------------------------- 削除の禁止
#
# **ARK も shoulder も消さない。**
#   ARK を消す      → 解決が止まる＝識別子が壊れる。`NR` を宣言している以上許されない。
#                     対象が失われたときは tombstone に付け替えるか、url を空にして
#                     記述を返す（FAIR A2）。
#   shoulder を消す → 乱数割当が同じ文字列を再び当てうる＝**NR 違反の芽**。組織が
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
