"""ドメインモデル。

`Naan → Manager → Shoulder → Ark` の 1 本で全 NAAN を扱う。**個別 NAAN を持つ
機関（岡崎3研究所）でも shoulder を必ず使う**（`design_ark_multitenant_authz.md`
§2.1.1）——使わないと NAAN ごとにモデルが分岐し、first-digit 規約が NAAN に
よって成立したりしなかったりする。

受け入れ条件:
  E1  既存 ARK を黙って上書きしない（`Ark.save()` が構造的に防ぐ）
  I5  条件つき unique 制約でローテーションを型として表現する
  I6  `Manager.create()` を使い `save()` を直接呼ばない
  R2  監査証跡
  D3  自 NAAN の未知名は 404（`Naan.is_authoritative` で判定する）
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.db.models import Q, UniqueConstraint
from oauth2_provider.models import AbstractApplication

from jc2ark.arkspec.betanumeric import check_digit_base, generate_noid, noid_check_digit
from jc2ark.arkspec.naming import (
    MAX_NAAN_LENGTH,
    ark_key,
    normalize_structural,
    strip_hyphens,
)
from jc2ark.arkspec.shoulder import InvalidShoulder, validate_shoulder

MINT_COLLISION_RETRIES = 10
NOID_LENGTH = 8


def _validate_shoulder(value: str) -> None:
    try:
        validate_shoulder(value)
    except InvalidShoulder as exc:  # Django のバリデーション例外に載せ替える
        raise ValidationError(str(exc)) from exc


class CommitmentLevel(models.TextChoices):
    """NMA コミットメント（対象へのサービスの約束）。

    NLM の permanence ratings を採る（自前定義しない）。`descriptive-only` だけは
    NLM の軸に無い JC2 の追加で、**物理オブジェクト**に使う。
    """

    NOT_GUARANTEED = "not-guaranteed", "保証なし（検証・開発系）"
    PERMANENT_DYNAMIC = "permanent-dynamic", "恒久・内容は更新されうる（既定）"
    PERMANENT_STABLE = "permanent-stable", "恒久・内容は実質不変"
    PERMANENT_UNCHANGING = "permanent-unchanging", "恒久・内容は一切不変"
    DESCRIPTIVE_ONLY = "descriptive-only", "記述のみ（所在は変わりうる）"


class Naan(models.Model):
    """Name Assigning Authority Number。

    N2: **naan は文字列**。`099999` と `99999` は別の NAAN であり、整数化して
    はならない。
    """

    naan = models.CharField(primary_key=True, max_length=MAX_NAAN_LENGTH)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    #: D3: **自分が権威を持つ NAAN の未知名は 404**（「無い」と言える）。
    #: `ARKLET_HOST` との文字列比較ではなくこの属性で判定する——9 NAAN 構成では
    #: 権威を持つ NAAN と委譲先を持つ NAAN が同居するため、文字列では区別できない。
    is_authoritative = models.BooleanField(default=True)

    #: 権威を持たない NAAN の委譲先。`is_authoritative=False` のときだけ意味を持つ。
    redirect = models.CharField(max_length=500, blank=True, default="")

    #: NAA ポリシー。`NP | NR, OP, CC | 2026 | <URL>`（`ark_design_policy.md` §5）。
    na_policy = models.CharField(max_length=500, blank=True, default="")

    #: **この NAAN の採番を外で行う場合の案内先。** 解決はここが続けることが
    #: ありうる（`is_authoritative=True` のまま minter だけ外）。`/.well-known/ark`
    #: で公開し、クライアントがどこへ行けばよいか分かるようにする。
    minter = models.URLField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # 権威を持たないなら転送先が要る。持つなら転送してはならない（D3）。
            models.CheckConstraint(
                condition=Q(is_authoritative=True, redirect="")
                | Q(is_authoritative=False) & ~Q(redirect=""),
                name="naan_redirect_only_when_not_authoritative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.naan} ({self.name})"


class Manager(models.Model):
    """機関テナント。N2T の shoulder レコードが持つ `manager` を実体化したもの。

    **資格情報は shoulder ではなくここに紐づける**——部局別・分野別に shoulder を
    足しても鍵の再発行が要らない。

    （Django の `models.Manager` とは無関係。N2T の語彙に合わせている。）
    """

    naan = models.ForeignKey(Naan, on_delete=models.PROTECT, related_name="managers")

    #: **内部専用。公開しない。** shoulder の不透明性（N5）を壊さないため。
    name = models.CharField(max_length=200)

    #: mint 要求が shoulder を省略したときに使う。**全 Manager が必ず 1 つ持つ。**
    default_shoulder = models.ForeignKey(
        "Shoulder", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    commitment_level = models.CharField(
        max_length=32, choices=CommitmentLevel.choices, default=CommitmentLevel.PERMANENT_DYNAMIC
    )
    quota_per_day = models.PositiveIntegerField(null=True, blank=True)  # R3。null は無制限
    active = models.BooleanField(default=True)

    #: **統廃合の承継先。** 大学の統合・吸収・閉学で管理主体が変わっても、
    #: **識別子は壊さない**（`NR` を宣言している以上、解決は続ける）。系譜を
    #: 辿れるように残す。`ark_succession.md` §2.1。
    succeeded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="predecessors"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["naan", "name"], name="uniq_manager_name_per_naan")]

    def __str__(self) -> str:
        return f"{self.name} @ {self.naan_id}"


class ShoulderStatus(models.TextChoices):
    """shoulder の管理状態。

    **名前空間は一度配ったら取り戻せない**（NR を宣言する以上、既存 ARK は解決し
    続ける）。だから「押さえてあるが使わせない」「もう新規は採らない」を状態として
    持てるようにする。
    """

    ACTIVE = "active", "採番できる"
    RESERVED = "reserved", "リザーブ枠（採番できない）"
    DELEGATED = "delegated", "採番は外部 minter（案内する）"
    RETIRED = "retired", "新規採番なし（既存は解決し続ける）"


class Shoulder(models.Model):
    """NAAN の下位名前空間。機関への名前空間の委譲を担う。"""

    shoulder = models.CharField(max_length=50, validators=[_validate_shoulder])
    naan = models.ForeignKey(Naan, on_delete=models.PROTECT, related_name="shoulders")
    manager = models.ForeignKey(
        Manager, null=True, blank=True, on_delete=models.CASCADE, related_name="shoulders"
    )

    name = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField(blank=True, default="")

    #: N2T の `redirect`。**shoulder 単位の解決委譲。** `$id` / `${blade}` /
    #: 先頭の `303 ` に対応する（実装は解決フロー側）。
    redirect = models.CharField(max_length=500, blank=True, default="")

    #: N2T の `minter`。**採番の委譲先。** `status=delegated` のとき、mint 要求は
    #: ここへ案内する（**プロキシしない**。理由は `views_api.MintView` を参照）。
    minter = models.URLField(blank=True, default="")

    status = models.CharField(
        max_length=16, choices=ShoulderStatus.choices, default=ShoulderStatus.ACTIVE, db_index=True
    )
    #: リザーブや委譲の理由。運用の記録。
    note = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["shoulder", "naan"], name="uniq_shoulder_per_naan"),
            # 委譲するなら行き先が要る。無いと mint 要求を案内できない。
            models.CheckConstraint(
                condition=~Q(status="delegated") | ~Q(minter=""),
                name="delegated_shoulder_needs_a_minter",
            ),
        ]

    @property
    def can_mint_here(self) -> bool:
        return self.status == ShoulderStatus.ACTIVE

    def delete(self, *args, **kwargs):
        """**shoulder は消さない。**

        削除すると乱数割当が同じ文字列を再び当てうる＝**`NR`（No Re-assignment）
        違反の芽**になる。機関が消えても行は残し、`status=retired` にする
        （`ark_succession.md` S2）。

        とくに `delegated` だった shoulder は、**外部 minter が我々の知らない
        識別子を作っている可能性**があるので絶対に消せない。
        """
        raise RuntimeError(
            "shoulder は削除しない（名前空間の再利用は NR 違反）。status=retired にすること。"
        )

    def __str__(self) -> str:
        return f"{self.naan_id}{self.shoulder}"


class Client(AbstractApplication):
    """OAuth2 クライアント（DOT の swappable `Application`）。

    S1-1 で確認済み: `AbstractApplication` に**有効フラグが無い**ので `active` は
    自前で持つ。
    """

    class Authority(models.TextChoices):
        MANAGER = "manager", "その機関の shoulder のみ"
        NAAN = "naan", "NAAN 配下の全 shoulder（break-glass）"

    manager = models.ForeignKey(
        Manager, null=True, blank=True, on_delete=models.CASCADE, related_name="clients"
    )
    naan = models.ForeignKey(Naan, on_delete=models.PROTECT, related_name="clients")

    #: **到達範囲はクライアント登録の属性。トークン要求で指定させない**（権限昇格を防ぐ）。
    authority = models.CharField(
        max_length=16, choices=Authority.choices, default=Authority.MANAGER
    )

    #: **この Client が使える shoulder を 1 つに固定する**（任意）。
    #:
    #: **同一 shoulder に対して複数のクライアントが採番しうる**——InvenioRDM の
    #: web-api / worker / 一括投入バッチのように、同じ名前空間を使う主体が複数
    #: いるのが普通。**それぞれに別の資格情報を発行し、鍵を共有させない。**
    #: null なら manager が持つ shoulder のどれでも使える。
    shoulder = models.ForeignKey(
        "Shoulder", null=True, blank=True, on_delete=models.PROTECT, related_name="clients"
    )

    #: 付与する操作。**S1-2: `SCOPES_BACKEND_CLASS` でこれを強制しないと、
    #: 登録に無い scope をトークン要求で取れてしまう。**
    allowed_scopes = models.CharField(max_length=200, default="ark:mint")

    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # `authority=naan` では必須
    label = models.CharField(max_length=200, blank=True, default="")

    class Meta(AbstractApplication.Meta):
        constraints = [
            # I5: **有効なものだけ (manager, label) で一意。** 旧を無効化して同名で
            # 新規発行できる＝ローテーションが型として表現される。
            UniqueConstraint(
                fields=["manager", "label"],
                condition=Q(active=True),
                name="uniq_active_label_per_manager",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label or self.name} [{self.authority}]"


class AlreadyRegistered(Exception):
    """B4: 修飾子付き ARK が既に在る。**上書きせず呼び出し側に返す。**"""


class ArkMinter(models.Manager):
    """`Ark` の採番。**`create()` を使い `save()` を直接呼ばない**（I6）。"""

    def mint(self, *, shoulder: Shoulder, created_by: str = "", **fields) -> tuple[Ark, int]:
        """衝突をリトライしながら 1 本採番する。

        E1: `create()` は内部で `save(force_insert=True)` を呼ぶので、**主キー衝突が
        UPDATE に化けず IntegrityError になる**。これが「既存 ARK を黙って上書き
        しない」という ARK の不変原則を構造的に守る仕掛け。
        """
        naan_id = shoulder.naan_id
        collisions = 0
        for _ in range(MINT_COLLISION_RETRIES):
            noid = generate_noid(NOID_LENGTH)
            stem = f"{shoulder.shoulder.lstrip('/')}{noid}"
            digit = noid_check_digit(check_digit_base(naan_id, stem))
            name = f"{stem}{digit}"
            try:
                ark = self.create(
                    ark=ark_key(naan_id, name),
                    naan_id=naan_id,
                    shoulder=shoulder,
                    assigned_name=name,
                    created_by=created_by,
                    updated_by=created_by,
                    **fields,
                )
            except IntegrityError:  # 衝突。**握りつぶさず数えて採り直す**
                collisions += 1
                continue
            return ark, collisions
        raise RuntimeError(f"gave up minting after {collisions} collision(s)")

    def register_qualified(self, *, base: Ark, qualifier: str, created_by: str = "", **fields):
        """B4: **既存 ARK に修飾子を付けた行を登録する。**

        「NOID を省略した採番」ではない。**修飾子は新しい名前ではなく、既存の名前に
        対する部分参照**なので、チェックディジットも付け直さない（N7: 検査桁は base
        compact name に対して計算され、修飾子を含まない）。

        用途は **suffix passthrough の上書き**——既定では祖先の URL に修飾子を
        continuation として足すが、「このサブツリーだけ別ストレージ」「この変換版だけ
        別の所在」を表したいときに、その 1 点だけ明示的に登録する。

        `shoulder` は base から継ぐ。**別の shoulder に生やせてはいけない**——
        修飾子は base の名前空間の内側にあるものだから。
        """
        if not qualifier.startswith(("/", ".")):
            raise ValueError("修飾子は '/'（包含）か '.'（変種）で始めること")
        name = strip_hyphens(normalize_structural(base.assigned_name + qualifier))
        if name == base.assigned_name or not name.startswith(base.assigned_name):
            raise ValueError(f"修飾子が base を指していない: {qualifier!r}")
        try:
            return self.create(
                ark=ark_key(base.naan_id, name),
                naan_id=base.naan_id,
                shoulder=base.shoulder,
                assigned_name=name,
                created_by=created_by,
                updated_by=created_by,
                **fields,
            )
        except IntegrityError as exc:
            # E1: 既に在るものを黙って上書きしない。更新は `update` の仕事。
            raise AlreadyRegistered(f"ark:/{ark_key(base.naan_id, name)} は既に登録済み") from exc


class Ark(models.Model):
    """採番済みの ARK。

    **子リソースは採番しない。** suffix passthrough が任意の深さを賄うので、
    1 レコード 1 採番で済む（`ark_domain_pid_design.md` §2.1）。容量設計上これが
    いちばん効いている。
    """

    #: `<naan>/<name>`。N2 のため naan は文字列のまま連結する。
    ark = models.CharField(primary_key=True, max_length=200, editable=False)
    naan = models.ForeignKey(Naan, on_delete=models.PROTECT, editable=False, related_name="arks")
    shoulder = models.ForeignKey(
        Shoulder, on_delete=models.PROTECT, editable=False, related_name="arks"
    )
    assigned_name = models.CharField(max_length=100, editable=False)

    url = models.URLField(blank=True, default="")
    commitment = models.TextField(blank=True, default="")
    metadata = models.TextField(blank=True, default="")

    # ERC / Dublin Core（分野標準の受け皿。`ark_domain_pid_design.md` §1）
    title = models.TextField(blank=True, default="")
    type = models.TextField(blank=True, default="")
    identifier = models.TextField(blank=True, default="")
    format = models.TextField(blank=True, default="")
    relation = models.TextField(blank=True, default="")
    source = models.TextField(blank=True, default="")
    who = models.TextField(blank=True, default="")  # C3
    when = models.TextField(blank=True, default="")  # C3

    # R2: 監査証跡
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=255, blank=True, default="", db_index=True)
    updated_by = models.CharField(max_length=255, blank=True, default="")

    objects = ArkMinter()

    class Meta:
        indexes = [models.Index(fields=["shoulder", "created_at"])]

    def save(self, *args, **kwargs):
        """**新規行の作成に素の `save()` を使わせない**（E1 を構造的に防ぐ）。

        arklet で最重大の欠陥だった「主キー衝突が UPDATE に化け、既存 ARK の
        向き先を黙って書き換える」は、`save()` を直接呼んだために起きた。IA 原典は
        `Manager.create()` を使っていたので同じ欠陥を持っていない（I6）。
        規約を人に守らせるのではなく、モデル側で不可能にする。
        """
        if self._state.adding and not kwargs.get("force_insert"):
            raise RuntimeError(
                "Ark を新規作成するときは Ark.objects.mint() か "
                "Ark.objects.create() を使うこと（force_insert が要る）。"
                "素の save() は主キー衝突を UPDATE に化けさせ、既存 ARK を"
                "黙って上書きする（E1）。"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """**ARK は消さない。**

        行を消すと解決が止まる＝**識別子が壊れる**。`NR` を宣言している以上、
        これは許されない。対象が失われたときは **tombstone に付け替える**か、
        `url` を空にして**記述を返す**（FAIR A2。`ark_succession.md` §2.4）。
        """
        raise RuntimeError(
            "ARK は削除しない（解決が止まる＝識別子が壊れる）。"
            "tombstone に付け替えるか url を空にすること。"
        )

    def __str__(self) -> str:
        return f"ark:/{self.ark}"


class MintReceipt(models.Model):
    """F4: **採番の控え。** 同じ `request_id` の再送に、前回と同じ ARK を返す。

    採番は再試行できない——ARK は `NR`（再割当てしない）を宣言する識別子で、応答が
    失われたときに再送すると**誰も指していない ARK が増える**（＝死んだ番号）。
    ark-client が `mint` を再試行しないのはこのため。

    だが**万オーダーの投入では、途中でネットワークが切れるほうが普通**
    （OME-NGFF の well、MIxS の試料）。「再試行できない」まま放置すると、
    運用側は「どこまで採番されたか」を自力で突き合わせる羽目になる。

    **控えを持てば、再送を安全にできる。** 呼び出し側が `request_id` を付け、
    サーバは (client, request_id) で 1 行に固定する。これが outbox パターンの
    受け側——分割は `BULK_LIMIT`、冪等はこの表、リトライは呼び出し側の自由。

    **client ごとに独立**。他機関の `request_id` と衝突しないし、鍵の推測で
    他機関の ARK を引くこともできない。
    """

    client_id = models.CharField(max_length=255, db_index=True)
    request_id = models.CharField(max_length=200)
    ark = models.ForeignKey("Ark", on_delete=models.PROTECT, related_name="receipts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["client_id", "request_id"], name="one_ark_per_request_id")
        ]

    def __str__(self) -> str:
        return f"{self.client_id}:{self.request_id} -> ark:/{self.ark_id}"


class AuditEvent(models.Model):
    """R2: 誰がいつ何をしたか。**`authority=naan` の操作は全件記録する。**"""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    client_id = models.CharField(max_length=255, db_index=True)
    authority = models.CharField(max_length=16)
    action = models.CharField(max_length=32)  # mint / update / bulk_update / …
    target = models.CharField(max_length=200, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["authority", "at"])]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.action} {self.target}"
