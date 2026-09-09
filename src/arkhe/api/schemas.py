"""API の入出力。OpenAPI はここから自動生成される（drf-spectacular が不要になる）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arkhe import errors
from arkhe.arkspec.naming import compact_ark
from arkhe.domain.resolution import DANGEROUS_SCHEMES, is_registrable

#: 呼び出し側が設定できる項目。**`shoulder` はここに無い**——主体から引く。
WRITABLE = (
    "url",
    "title",
    "type",
    "identifier",
    "format",
    "relation",
    "source",
    "commitment",
    "metadata",
    "who",
    "when",
)



def _spec(description: str) -> ConfigDict:
    """スキーマの説明を**英語で**上書きする。

    **公開する OpenAPI は英語**——読者はこの台帳の外にいる。Pydantic は
    クラスの docstring をスキーマの `description` に使うので、そのままだと
    日本語が仕様書に出る。docstring は**実装を読む人のために日本語で残し**、
    出す文面だけここで差し替える。
    """
    return ConfigDict(json_schema_extra={"description": description})


class ArkFields(BaseModel):
    """ERC / Dublin Core の受け皿。すべて任意。"""

    model_config = _spec("ERC / Dublin Core fields. All optional.")

    @field_validator("url")
    @classmethod
    def _safe_url(cls, v: str) -> str:
        """**ブラウザに解釈させると危ないものだけ拒む。**

        ARK は物理オブジェクトにも他の識別子にも付けられるので、`urn:` `doi:`
        `ark:` などを拒んではいけない。空も正当（行き先が無い対象）。

        拒むのは `javascript:` `data:` のたぐいだけ——`?info` は認証を要さない
        公開ページで、そこに載る文字列を決めるのは採番した側だから。
        """
        if not is_registrable(v):
            raise ValueError(
                errors.URL_SCHEME_REFUSED.say(schemes="/".join(sorted(DANGEROUS_SCHEMES)))
            )
        return v

    url: str = ""
    title: str = ""
    type: str = ""
    identifier: str = ""
    format: str = ""
    relation: str = ""
    source: str = ""
    commitment: str = ""
    metadata: str = ""
    who: str = ""
    when: str = ""

    def writable(self) -> dict:
        return self.model_dump(include=set(WRITABLE))


class MintIn(ArkFields):
    """採番の入力。

    **`shoulder` は任意。** 省略すると組織の `default_shoulder` が使われる。
    指定した場合も**範囲を広げる手段にはならない**（登録された到達範囲内かを
    検証するだけ）。`naan` は受け取らない——主体が決めるものだから。
    """

    model_config = _spec(
        "Input for minting. `shoulder` is optional: omitted, the organisation's "
        "default is used; named, it is only checked against the caller's registered "
        "reach, never widening it. `naan` is not accepted — it follows from the "
        "principal."
    )

    shoulder: str = ""
    #: F4: **再送しても二重に採番しないための鍵。** 呼び出し側が付ける。
    request_id: str = Field(
        default="",
        max_length=200,
        description=(
            "Idempotency key. Resending the same value returns the ARK minted the "
            "first time, instead of minting again."
        ),
    )


class RegisterIn(ArkFields):
    """B4: 修飾子付き ARK の登録。

    **`ark` は既存の base、`qualifier` はその後ろに付ける部分参照。**
    採番ではないので NOID もチェックディジットも生成しない。
    """

    model_config = _spec(
        "A qualified ARK: `ark` is an existing base name and `qualifier` the part "
        "reference appended to it. Nothing is minted, so no NOID and no check digit "
        "are generated."
    )

    ark: str = Field(description="An existing base ARK (`ark:99999/x9tn1qkq2g7`).")
    qualifier: str = Field(description="Begins with `/` (a part) or `.` (a variant).")


class ImportIn(ArkFields):
    """外で採番された ARK を取り込む。

    **`ark` は呼び出し側が持ってくる名前**——ここが `mint` との唯一にして
    決定的な違いで、`mint` が構造で守っていたものが検査に移る。詳しくは
    `domain.minting.import_minted`。
    """

    model_config = _spec(
        "An ARK minted elsewhere, to be recorded here. Unlike minting, **the caller "
        "brings the name**; it must fall inside a delegated shoulder of this ledger and "
        "its check digit must verify."
    )

    ark: str = Field(
        description="The ARK as it was minted elsewhere (`ark:99999/c7962c644f8`)."
    )


class HoldIn(BaseModel):
    """転送の一時停止。**解決は止めない**（記述は返り続ける）。

    `until` を必須にしてあるのは、「一時的」を人の記憶に頼ると恒久化するから。
    `reason` を必須にしてあるのは、**公開の口（`?info`）に出る**うえ、外す判断に
    要るから——理由の無い保留は、掛けた本人以外に外せない。
    """

    model_config = _spec(
        "A temporary stop on redirection. **Resolution is not stopped** — the "
        "description keeps being returned. `until` is required because a "
        "\"temporary\" left to memory becomes permanent; `reason` is required "
        "because it is published, and because lifting the hold needs it."
    )

    ark: str
    until: datetime = Field(
        description="No redirection until this moment. A time in the past is refused."
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
        description="Why redirection is stopped. **This is published.**",
    )


class HoldReleaseIn(BaseModel):
    """期限を待たずに保留を外す。"""

    model_config = _spec("Lift a hold before its expiry.")

    ark: str


class UpdateIn(ArkFields):
    """`PUT` の入力。**レコードの置き換え**なので、省いた項目は既定値で埋まる。"""

    model_config = _spec(
        "Input for a replacing update. **Every omitted field takes its default**, so "
        "send the whole record; to change one field and leave the rest alone, PATCH."
    )

    ark: str


class PatchIn(ArkFields):
    """`PATCH` の入力。**送られた項目だけ**を書き換える。

    `PUT` との違いは「省いた項目をどう読むか」だけ。あちらは「空にせよ」、
    こちらは「触るな」。`model_fields_set` に**実際に送られてきた鍵**が入るので、
    「空文字を送って消す」と「送らないから触らない」を区別できる
    ——これができないと、**記述を消す手段が無くなる**。
    """

    model_config = _spec(
        "Input for a merging update. **Only the fields actually sent are written**; "
        "everything else is left as it is. Sending a field as \"\" clears it, which is "
        "how a value is removed."
    )

    ark: str

    def sent(self) -> dict:
        """送られてきた書き込み可能項目だけを返す。"""
        return {k: v for k, v in self.model_dump(include=set(WRITABLE)).items()
                if k in self.model_fields_set}


class TombstoneIn(BaseModel):
    """**対象が失われたと宣言する。** ARK は削除しない。"""

    model_config = _spec(
        "Declare that the object is gone. **The ARK is not deleted** — the identifier "
        "and its metadata stay, only reachability goes."
    )

    ark: str
    #: 空なら、リゾルバが記述そのものを返す（D6 と同じ経路）。
    url: str = ""
    commitment: str = ""


class BulkMintIn(BaseModel):
    data: list[MintIn]


class BulkUpdateIn(BaseModel):
    data: list[UpdateIn]


class BulkImportIn(BaseModel):
    """まとめて取り込む。**1 件でも通らなければ何も作らない。**"""

    model_config = _spec(
        "Import in bulk. **One row that fails any check and nothing is created** — a "
        "half-imported namespace is worse than none, because the names that did land "
        "cannot be taken back."
    )

    data: list[ImportIn]


class BulkImportOut(BaseModel):
    imported: list[ArkOut]
    count: int


class BulkQueryIn(BaseModel):
    data: list[str]


class ArkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ark: str
    url: str = ""
    title: str = ""
    type: str = ""
    identifier: str = ""
    format: str = ""
    relation: str = ""
    source: str = ""
    commitment: str = ""
    metadata: str = ""
    who: str = ""
    when: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: 転送を止めているなら、その期限と理由。**止まっていることは隠さない。**
    hold_until: datetime | None = None
    hold_reason: str = ""

    @classmethod
    def of(cls, ark) -> ArkOut:
        return cls(
            ark=compact_ark(ark.ark),
            **{f: getattr(ark, "metadata_" if f == "metadata" else f) for f in WRITABLE},
            created_at=ark.created_at,
            updated_at=ark.updated_at,
            hold_until=ark.hold_until,
            hold_reason=ark.hold_reason,
        )


class BulkMintOut(BaseModel):
    minted: list[ArkOut]
    created: int
    replayed: int


class BulkUpdateOut(BaseModel):
    updated: int


class BulkQueryOut(BaseModel):
    data: list[ArkOut]
