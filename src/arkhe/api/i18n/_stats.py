"""Wording for the statistics: what counting the ledger produced.

The prefix is stat. st. is already used by the shoulder states (mintable, reserved,
delegated, retired). A duplicate key fails at startup, but confusion that does not fail
is what costs later.

Both languages live in one file, so that adding to only one shows up in the diff. The
check at startup is the last line of defence, not the first.
"""

from __future__ import annotations

JA: dict[str, str] = {
    "stat.title": "統計",
    "stat.lede": "<b>見えている範囲を数えたものです。</b>"
               "届かないものは 1 件も入っていません——<b>合計もまた、在ることを"
               "漏らす</b>からです（ある組織がいくつ識別子を持っているかは、その組織の"
               "事情です）。",
    "stat.scope": "数えた範囲",
    "stat.scope.system": "全 NAAN",
    "stat.scope.naan": "この NAAN の配下すべて",
    "stat.scope.organisation": "この組織",
    "stat.ledger": "台帳",
    "stat.arks": "ARK",
    "stat.public": "公開",
    "stat.reserved": "公開前",
    "stat.naans": "NAAN",
    "stat.withdrawn": "取り下げた名前",
    "stat.withdrawn_lede": "<b>公開後に消したものは分けて数えています。</b>"
                         "予約を引っ込めたのと、世に出した名前を消したのとでは"
                         "意味がまるで違い、<b>後者はこの体系が守ると言っているものを"
                         "破った回数</b>だからです。",
    "stat.withdrawn_reserved": "公開前に取り下げ",
    "stat.withdrawn_published": "公開後に破棄",
    "stat.shoulders": "shoulder",
    "stat.organisations": "組織",
    "stat.clients": "主体",
    "stat.active": "有効",
    "stat.holds": "保留中の転送",
    "stat.minting": "採番の勢い",
    "stat.minted_24h": "直近 24 時間",
    "stat.minted_7d": "直近 7 日",
    "stat.minted_30d": "直近 30 日",
    "stat.minting_note": "窓は重なっています——24 時間のぶんは 7 日にも 30 日にも"
                       "入っており、<b>別々の母数ではありません</b>。",
    "stat.first_mint": "最初の採番",
    "stat.last_mint": "最後の採番",
    "stat.per_shoulder": "shoulder ごと",
    "stat.per_shoulder_lede": "<b>台帳が組織されている単位です。</b>"
                            "ここでの偏りが、採番の重さがどこに寄っているかを表します。",
    "stat.shoulder": "shoulder",
    "stat.status": "状態",
    "stat.organisation": "組織",
    "stat.total": "合計",
    "stat.none": "まだ 1 件もありません",
    "stat.cost": "<b>数えるのは行数に比例して重い操作です。</b>"
               "一覧が件数を数えずに済ませているのと違って、ここは数そのものが"
               "目的なので避けようがありません——開いたままにする画面ではありません。",
}

EN: dict[str, str] = {
    "stat.title": "Statistics",
    "stat.lede": "<b>Counts for what you can see.</b> Nothing outside your reach is "
               "included — <b>a total is itself a disclosure</b>, since how many "
               "identifiers an organisation holds is that organisation's business.",
    "stat.scope": "Counted over",
    "stat.scope.system": "every NAAN",
    "stat.scope.naan": "this NAAN and everything under it",
    "stat.scope.organisation": "this organisation",
    "stat.ledger": "Ledger",
    "stat.arks": "ARKs",
    "stat.public": "public",
    "stat.reserved": "reserved",
    "stat.naans": "NAANs",
    "stat.withdrawn": "Withdrawn names",
    "stat.withdrawn_lede": "<b>Those removed after publication are counted separately.</b> "
                         "Retracting a reservation nobody saw and removing a name that "
                         "was out in the world are different acts, and <b>the second is "
                         "the number of times the promise was broken</b>.",
    "stat.withdrawn_reserved": "withdrawn before publication",
    "stat.withdrawn_published": "purged after publication",
    "stat.shoulders": "Shoulders",
    "stat.organisations": "Organisations",
    "stat.clients": "Clients",
    "stat.active": "active",
    "stat.holds": "Held redirects",
    "stat.minting": "Minting",
    "stat.minted_24h": "last 24 hours",
    "stat.minted_7d": "last 7 days",
    "stat.minted_30d": "last 30 days",
    "stat.minting_note": "The windows overlap — what was minted in the last 24 hours is "
                       "also in the 7- and 30-day figures. <b>They are not separate "
                       "populations.</b>",
    "stat.first_mint": "First mint",
    "stat.last_mint": "Last mint",
    "stat.per_shoulder": "Per shoulder",
    "stat.per_shoulder_lede": "<b>The shoulder is the unit the ledger is organised by.</b> "
                            "How it leans here is where the minting weight actually sits.",
    "stat.shoulder": "Shoulder",
    "stat.status": "Status",
    "stat.organisation": "Organisation",
    "stat.total": "total",
    "stat.none": "Nothing here yet",
    "stat.cost": "<b>Counting costs time proportional to the number of rows.</b> The "
               "listing avoids it because it only needs to know whether there is more; "
               "here the number is the answer. <b>This is not a page to leave open.</b>",
}
