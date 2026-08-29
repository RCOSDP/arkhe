"""認証の結果。**どの機構で認証しても、認可はこの 1 つの型の上で判断する。**

api キー・自前トークン・外部 OIDC は「誰であるかをどう確かめたか」が違うだけで、
確かめた後の問い「この主体はこの shoulder を触れるか」は同一。ここを分けないと、
機構を足すたびに認可の分岐が増えて、**どこかに抜けができる**。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arkhe.db.models import Authority


@dataclass(frozen=True)
class Principal:
    """認証済みの主体。

    到達範囲（naan / manager / shoulder / scopes）は**クライアント登録の属性**で、
    トークン要求やリクエスト本文からは決して来ない。権限昇格を防ぐため。
    """

    client_id: str
    naan: str
    authority: str = Authority.MANAGER.value
    manager_id: int | None = None
    #: **この主体が使える shoulder を 1 つに固定する**場合の id。None なら
    #: manager が持つ shoulder のどれでも使える。
    shoulder_id: int | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    #: どの機構で認証したか。監査に残す。
    mechanism: str = ""

    #: 接続元のアドレス。**要求の層でだけ入る**（ドメインは知らなくてよい）。
    #: 監査に残すためだけに運ぶので、認可の判断には使わない
    #: ——IP は詐称できるし、経路が変われば変わるため。
    ip: str = ""

    @property
    def is_system(self) -> bool:
        """RA の運用者。**全 NAAN に届く。**"""
        return self.authority == Authority.SYSTEM

    @property
    def is_naan_wide(self) -> bool:
        """NAAN 配下すべてに届く（system を含む）。"""
        return self.authority in (Authority.SYSTEM, Authority.NAAN)

    #: 後方互換。`authority=naan` は break-glass としても使われる。
    @property
    def is_break_glass(self) -> bool:
        return self.is_naan_wide

    def reaches_naan(self, naan: str) -> bool:
        """その NAAN に届くか。**判定はここ 1 か所**（機構によらない）。"""
        return self.is_system or self.naan == naan

    def has(self, scope: str) -> bool:
        return scope in self.scopes
