"""骨格・状態・書式の文言。どの画面にも出る語。見出し、状態の名前、フォームの共通語。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
    # 骨格
    "app.subtitle": "ARK 識別子基盤",
    "nav.ledger": "台帳",
    "nav.actions": "操作",
    "nav.overview": "組織管理",
    "nav.clients": "利用者と鍵",
    "nav.mint": "ARK を採番",
    "nav.audit": "監査ログ",
    "nav.holds": "保留中の転送",
    "lang.label": "言語",
    # 状態
    "st.active": "採番可",
    "st.reserved": "予約",
    "st.delegated": "委譲",
    "st.retired": "引退",
    "au.system": "システム管理者",
    "au.naan": "NAAN 管理者",
    "au.manager": "組織管理者",
    # ログイン
    # 台帳を組む操作
    # 用語を括弧で添えるときの括弧。**言語で形が違う**（全角と半角＋前スペース）。
    "f.paren_open": "（",
    "f.paren_close": "）",
    "f.save": "保存",
    "f.create": "登録",
    "f.cancel": "やめる",
    "f.saved": "保存しました。",
    "f.optional": "任意",
    "f.readonly_here": "この画面からは変えられません",
}

EN: dict[str, str] = {
    "app.subtitle": "ARK identifier infrastructure",
    "nav.ledger": "Ledger",
    "nav.actions": "Actions",
    "nav.overview": "Organisations",
    "nav.clients": "Users & keys",
    "nav.mint": "Mint an ARK",
    "nav.audit": "Audit log",
    "nav.holds": "Held redirects",
    "lang.label": "Language",
    "st.active": "mintable",
    "st.reserved": "reserved",
    "st.delegated": "delegated",
    "st.retired": "retired",
    "au.system": "System administrator",
    "au.naan": "NAAN administrator",
    "au.manager": "Organisation administrator",
    "f.paren_open": " (",
    "f.paren_close": ")",
    "f.save": "Save",
    "f.create": "Create",
    "f.cancel": "Cancel",
    "f.saved": "Saved.",
    "f.optional": "optional",
    "f.readonly_here": "cannot be changed here",
}
