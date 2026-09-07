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

    # 断りの文面。**画面の言語で返す。** 直書きしていたので、英語で使っていても
    # 日本語が返っていた——画面が切り替わるのに断りだけ切り替わらないのは、
    # いちばん困るところで母語から落ちるということ。
    "e.naan_system_only": "NAAN の登録はシステム管理者のみ",
    "e.minter_system_only": "採番の案内先の変更はシステム管理者のみ",
    "e.manager_naan_wide": "組織のオンボードは NAAN 単位以上の権限が要る",
    "e.shoulder_naan_wide": "shoulder の切り出しは NAAN 単位以上の権限が要る",
    "e.audit_naan_wide": "監査ログの閲覧は NAAN 単位以上の権限が要る",
    "e.out_of_reach_naan": "この NAAN はこの主体の範囲外",
    "e.out_of_reach_manager": "この組織はこの主体の範囲外",
    "e.out_of_reach_shoulder": "この shoulder はこの主体の範囲外",
    "e.out_of_reach_ark": "この ARK はこの主体の範囲外",
    "e.out_of_reach_client": "この利用者はこの主体の範囲外",
    "e.cannot_add_client": "この主体は利用者を登録できない",
    "e.mechanism_off": "この構成はこの資格情報を受け付けない（ARKHE_AUTH を確認すること）",
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

    # Refusals. **Answered in the language of the screen.**
    "e.naan_system_only": "Only a system administrator registers a NAAN.",
    "e.minter_system_only": "Only a system administrator changes where minting happens.",
    "e.manager_naan_wide": "Onboarding an organisation needs NAAN-wide authority.",
    "e.shoulder_naan_wide": "Carving out a shoulder needs NAAN-wide authority.",
    "e.audit_naan_wide": "Reading the audit log needs NAAN-wide authority.",
    "e.out_of_reach_naan": "This NAAN is outside your reach.",
    "e.out_of_reach_manager": "This organisation is outside your reach.",
    "e.out_of_reach_shoulder": "This shoulder is outside your reach.",
    "e.out_of_reach_ark": "This ARK is outside your reach.",
    "e.out_of_reach_client": "This user is outside your reach.",
    "e.cannot_add_client": "This principal cannot register users.",
    "e.mechanism_off": "This deployment does not accept that credential (check ARKHE_AUTH).",
}
