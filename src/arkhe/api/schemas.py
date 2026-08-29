"""API の入出力。OpenAPI はここから自動生成される（drf-spectacular が不要になる）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ArkFields(BaseModel):
    """ERC / Dublin Core の受け皿。すべて任意。"""

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
                "ブラウザに解釈させると危ないスキームは行き先にできません"
                f"（{'/'.join(sorted(DANGEROUS_SCHEMES))}）"
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

    shoulder: str = ""
    #: F4: **再送しても二重に採番しないための鍵。** 呼び出し側が付ける。
    request_id: str = Field(
        default="",
        max_length=200,
        description="冪等鍵。同じ値で再送すると、前回採番した ARK をそのまま返す",
    )


class RegisterIn(ArkFields):
    """B4: 修飾子付き ARK の登録。

    **`ark` は既存の base、`qualifier` はその後ろに付ける部分参照。**
    採番ではないので NOID もチェックディジットも生成しない。
    """

    ark: str = Field(description="既存の base ARK（`ark:/99999/xyz`）")
    qualifier: str = Field(description="`/`（包含）か `.`（変種）で始める")


class UpdateIn(ArkFields):
    ark: str


class TombstoneIn(BaseModel):
    """**対象が失われたと宣言する。** ARK は削除しない。"""

    ark: str
    #: 空なら、リゾルバが記述そのものを返す（D6 と同じ経路）。
    url: str = ""
    commitment: str = ""


class BulkMintIn(BaseModel):
    data: list[MintIn]


class BulkUpdateIn(BaseModel):
    data: list[UpdateIn]


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

    @classmethod
    def of(cls, ark) -> ArkOut:
        return cls(
            ark=f"ark:/{ark.ark}",
            **{f: getattr(ark, "metadata_" if f == "metadata" else f) for f in WRITABLE},
            created_at=ark.created_at,
            updated_at=ark.updated_at,
        )


class BulkMintOut(BaseModel):
    minted: list[ArkOut]
    created: int
    replayed: int


class BulkUpdateOut(BaseModel):
    updated: int


class BulkQueryOut(BaseModel):
    data: list[ArkOut]
