"""管理画面。**テーブルの行編集ではなく、操作の画面。**

画面が呼ぶのは `domain.admin_ops` と `domain.minting` で、DB を直接は触らない。
CLI と同じ関数を通るので、画面から不変条件を破る道が生まれない。

見せる範囲は `Principal` の 3 段（system / naan / manager）でそのまま絞る。
**画面の出し分けと実際の認可は同じ判定**を使う——別々にすると、ボタンは出ないが
URL を直接叩けば通る、という穴ができる。

画面ごとに分けてある。**取り込む順に意味は無い**（どれも `_common` の同じ
ルータに登録するだけ）が、`arks` は `/arks/{ark:path}` を持つので、より具体的な
経路を先に登録しておく必要がある。
"""

# 取り込むことでルータに登録される。順序については上の注記を参照。
from arkhe.api.admin import arks, audit, clients, ledger, minting, signin  # noqa: E402,F401
from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    NeedsLogin,
    admin_principal,
    router,
)

__all__ = ["PAGE", "AdminPrincipal", "NeedsLogin", "admin_principal", "router"]
