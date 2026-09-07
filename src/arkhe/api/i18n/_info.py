"""`?info` — 解決結果を人に見せるページの語彙。

**管理画面ではなく、公開の口である。** 誰でも認証なしに開けるし、ARK は世界中の
どこからでも引かれる。ここが日本語しか話さないと、**識別子は届いたのに説明が
読めない**という形で落ちる。

言語の決め方は管理画面と同じ（`?lang=` → cookie → `Accept-Language` → 既定）。
ただし `?info` は**クエリ文字列そのものが inflection** なので、切り替えるときは
`?info&lang=en` と書く。

`ci.*` は永続性の水準の表示名。`Manager.commitment_level` に入る値と 1 対 1 で、
**`?info` の画面と `?json` の `commitment_label` の両方**がここから採る。
"""

from __future__ import annotations

JA: dict[str, str] = {
    "in.kicker": "ARK",
    "in.held.h": "この識別子は今、転送を止めています。",
    "in.held.until": "{} までの一時的な措置です。識別子は有効で、記述はこのとおり答え続けます。",
    "in.inherited": "この記述は {} から継承しています（要求された名前は登録されていませんが、"
                    "最も近い祖先の記述を返しています）。",
    "in.redirect": "今の行き先",
    "in.redirect.held": "今は転送していません（保留中）",
    "in.redirect.unopenable": "（このスキームは開けません）",
    "in.redirect.none": "この ARK に転送先はありません（記述のみ）",
    "in.persistence": "永続性について",
    "in.commitment": "この対象への約束",
    "in.na_policy": "名前空間の方針",
    "in.fine": "ARK では、永続性は識別子の性質ではなく<b>提供者が続けるサービス</b>です。"
               "ここに書かれているのは、その提供者が自ら宣言した約束の水準です。",
    # 永続性の水準。**`CommitmentLevel` の値と 1 対 1。**
    "ci.not-guaranteed": "保証なし（検証・開発系）",
    "ci.permanent-dynamic": "恒久・内容は更新されうる",
    "ci.permanent-stable": "恒久・内容は実質不変",
    "ci.permanent-unchanging": "恒久・内容は一切不変",
    "ci.descriptive-only": "記述のみ（所在は変わりうる）",
}

EN: dict[str, str] = {
    "in.kicker": "ARK",
    "in.held.h": "This identifier is not being redirected right now.",
    "in.held.until": "A dated measure, until {}. The identifier is valid and the "
                     "description goes on answering, as it does here.",
    "in.inherited": "This description is inherited from {} — the name you asked for is not "
                    "registered, so the nearest registered ancestor answered.",
    "in.redirect": "current target",
    "in.redirect.held": "not being redirected (on hold)",
    "in.redirect.unopenable": "(a scheme a browser cannot open)",
    "in.redirect.none": "this ARK has no target — the description is the answer",
    "in.persistence": "On persistence",
    "in.commitment": "the promise for this object",
    "in.na_policy": "namespace policy",
    "in.fine": "In ARK, persistence is not a property of the identifier but "
               "<b>a service the provider keeps up</b>. What is stated here is the level "
               "of commitment that provider has declared for itself.",
    "ci.not-guaranteed": "not guaranteed (test and development)",
    "ci.permanent-dynamic": "permanent; the content may be revised",
    "ci.permanent-stable": "permanent; the content is substantially fixed",
    "ci.permanent-unchanging": "permanent; the content will not change",
    "ci.descriptive-only": "description only; the location may change",
}
