"""ARKの文言。採番と、発行した ARK の一覧・詳細。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
    # 採番
    "mint.title": "ARK を採番",
    "mint.lede": "通常の採番は組織のシステムが API から行います。この画面は"
                 "<b>手作業で 1 本必要なとき</b>——移行時の個別対応、物理オブジェクト、"
                 "動作確認——のためのものです。",
    "mint.done": "採番しました",
    "mint.irreversible": "この識別子は<b>取り消せません</b>。ARK は再割当てしないと"
                         "宣言しているため、不要になっても削除ではなく tombstone にします。",
    "mint.target": "解決先",
    "mint.form": "新規採番",
    "mint.shoulder": "採番する名前空間",
    "mint.shoulder_opt": "省略すると組織の既定",
    "mint.shoulder_default": "（組織の既定）",
    "mint.shoulder_required": "NAAN 単位以上の権限では<b>明示が必須</b>です"
                              "（誤って他組織の名前空間に打つのを防ぐため）。",
    "mint.url": "解決先 URL",
    "mint.url_opt": "空なら記述を返す",
    "mint.url_hint": "空のままでも採番できます。物理オブジェクトなど、"
                     "行き先が無い対象はこれが正しい形です。",
    "mint.title_field": "タイトル",
    "mint.type": "種別",
    "mint.type_hint": "一覧から選べます。<b>ここにないものは直接入力してかまいません</b>"
                      "——ERC の <code>what</code> は語彙を縛らないので、"
                      "画面が縛ってはいけません。",
    "mint.submit": "採番する",
    "mint.flash": "を採番しました",
    "mint.reserve": "公開前として採る",
    "mint.reserve_hint": "<b>まだ世に出さない採番です。</b>解決せず、要らなくなれば"
                         "取り下げられます。対象を公開するときに、この画面の詳細から"
                         "公開してください。",
    "mint.reserved_note": "これは<b>公開前</b>の ARK です。まだ解決しません——"
                          "対象を公開するときに、あわせて公開してください。",
    # 発行した ARK
    "nav.arks": "発行した ARK",
    "ak.title": "発行した ARK",
    "ak.lede": "この画面に出るのは<b>あなたに届く範囲のもの</b>だけです"
               "——システム管理者は全件、組織管理者は自組織のものを見ます。",
    "ak.search": "検索",
    "ak.search_ph": "ARK・行き先・題名（x9abc / example.org / 観測データ）",
    "ak.ark": "ARK",
    "ak.target": "行き先",
    "ak.title_col": "題名",
    "ak.when": "採番",
    "ak.by": "採番した主体",
    "ak.none_target": "（行き先なし）",
    "ak.empty": "該当する ARK がありません。",
    "ak.prev": "前",
    "ak.next": "次",
    "ak.page": "{n} ページ目",
    "ak.detail": "この ARK",
    "ak.history": "行き先が変わった記録",
    "ak.hist_lede": "<b>以前どこを指していたかを残します。</b>"
                    "<code>NR</code> を宣言している以上、識別子そのものは変わりません"
                    "——変わるのは行き先だけなので、それを辿れる必要があります。",
    "ak.hist_when": "いつ",
    "ak.hist_what": "何を",
    "ak.hist_from": "変更前",
    "ak.hist_to": "変更後",
    "ak.hist_by": "誰が",
    "ak.hist_ip": "接続元",
    "ak.hist_none": "行き先が変わったことはありません。",
    "ak.act.update": "付け替え",
    "ak.act.publish": "公開した",
    "ak.act.tombstone": "失われたと宣言",
    "ak.act.hold": "転送を止めた",
    "ak.act.release_hold": "保留を外した",
    "ak.hold": "転送の保留",
    "ak.hold_lede": "行き先が確かめられないとき、<b>転送だけ</b>を止めます。"
    "識別子は生き続け、記述は答え続けます（失われた宣言とは別のものです）。",
    "ak.hold_on": "保留中",
    "ak.hold_until": "この日時まで",
    "ak.hold_reason": "理由",
    "ak.hold_reason_hint": "<b>公開の口に出ます。</b>機微は書かないこと。",
    "ak.hold_days": "日数",
    "ak.hold_days_hint": "過ぎれば自動的に戻ります。上限は",
    "ak.hold_do": "転送を止める",
    "ak.hold_off": "保留を外す",
    "ak.open": "見る",
    "ak.gone": "（なし）",
    "ak.org": "組織",
    "ak.org_all": "すべての組織",
    "ak.filter": "絞り込む",
    "ak.meta": "記述（ERC / Dublin Core）",
    "ak.meta_lede": "<b><code>?</code> と <code>??</code> で公開されるのはこの内容です。</b>"
                    "空の項目は出しません——ERC は「無い」ことを書かない書式です。",
    "ak.meta_empty": "記述が入っていません。",
    "ak.f.title": "題名（what）",
    "ak.f.who": "who",
    "ak.f.when": "when",
    "ak.f.type": "種別",
    "ak.f.identifier": "他の識別子",
    "ak.f.format": "形式",
    "ak.f.relation": "関係",
    "ak.f.source": "出典",
    "ak.f.commitment": "この対象への約束",
    "ak.f.metadata": "メタデータの所在",
    "ak.shoulder": "名前空間",
    "ak.updated": "最終更新",
    "ak.resolve": "解決してみる",
    # 公開と取り下げ
    "ak.state": "状態",
    "ak.state_all": "公開前も公開済みも",
    "ak.public": "公開済み",
    "ak.reserved": "公開前",
    "ak.published_at": "公開",
    "ak.publication": "グローバルへの公開",
    "ak.pub_lede": "<b>公開するまで、この ARK は解決しません。</b>まだ外に出していない"
                   "名前なので、要らなくなれば消せます。",
    "ak.pub_done_lede": "<b>この ARK は公開済みです。</b>対象が失われただけなら、消さずに"
                        "tombstone にするか行き先を空にします——<b>そちらなら識別子は"
                        "解決し続けます</b>。",
    "ak.publish": "公開する",
    "ak.publish_warn": "公開すると解決を始めます。あとで引っ込めることはできますが、"
                       "<b>引っ込めても「一度出した」事実は消えません</b>——"
                       "その後の削除には理由と打ち直しが要ります。",
    "ak.republish_note": "<b>この ARK は一度公開されていました。</b>出し直せますが、"
                         "解決しなかった期間は埋められません——その間に引いた人には"
                         "404 が返っています。",
    "ak.unpublish": "公開を取り下げる",
    "ak.unpub_lede": "<b>引っ込めても行は残るので、出し直せます。</b>取り下げている"
                     "あいだ、この ARK は解決しません。<b>名前が別のものを指すことは"
                     "ありません</b>——残っている参照は 404 になるだけです。",
    "ak.unpub_reason": "取り下げる理由",
    "ak.unpub_reason_hint": "<b>必須です。</b>その間に誰かが引用しているかもしれず、"
                            "こちらからは知りようがありません。",
    "ak.unpub_confirm": "確認のため ARK を打ち直す",
    "ak.unpub_confirm_hint": "一覧を回す操作が、意図せず全件に効くことのないように。",
    "ak.withdraw": "取り下げて削除する",
    "ak.withdraw_lede": "<b>まだ公開していないので消せます。</b>行は消えますが、"
                        "その名前は二度と採られません——予約した文字列は既に"
                        "誰かの手にあるかもしれないからです。",
    "ak.withdraw_exposed_lede": "<b>この ARK は一度公開されています。</b>今は取り下げて"
                                "いるので消せますが、<b>消すと戻せません</b>——出し直す"
                                "なら先に「公開する」を押してください。名前は二度と"
                                "採られません。",
    "ak.withdraw_reason": "取り下げる理由",
    "ak.withdraw_reason_hint": "消えた行について残る唯一の説明になります"
                               "（公開の口には出ません）。",
    "ak.withdrawn_flash": "を取り下げました",
    # 破棄（RA の運用者だけ）
    "ak.purge": "破棄する",
    "ak.purge_title": "公開した ARK の破棄",
    "ak.purge_lede": "<b>これは約束を破る操作です。</b>公開した ARK は解決し続ける"
                     "はずのもので、消せば残っている参照はすべて切れます——"
                     "削除命令や、公開してはならなかったものへの逃げ道としてだけ"
                     "使ってください。<b>迷うなら、上の「公開を取り下げる」を"
                     "使ってください</b>——あちらは戻せます。",
    "ak.purge_keeps": "<b>名前は解放されません。</b>二度と採番されないので、"
                      "消した後にその名前が別のものを指すことはありません"
                      "（残った参照は 404 になるだけです）。理由と監査は残ります。",
    "ak.purge_reason": "破棄する理由",
    "ak.purge_reason_hint": "<b>必須です。</b>消えた識別子について残る唯一の説明に"
                            "なります。",
    "ak.purge_confirm": "確認のため ARK を打ち直す",
    "ak.purge_confirm_hint": "一覧を回す操作が、意図せず消してしまわないように。",
}

EN: dict[str, str] = {
    "mint.title": "Mint an ARK",
    "mint.lede": "Organisations normally mint through the API. This page is for the times "
                 "you need <b>one by hand</b> — a migration edge case, a physical object, "
                 "a smoke test.",
    "mint.done": "Minted",
    "mint.irreversible": "This identifier <b>cannot be taken back</b>. ARK declares that "
                         "names are never re-assigned, so an unwanted one is tombstoned, "
                         "not deleted.",
    "mint.target": "Resolves to",
    "mint.form": "New ARK",
    "mint.shoulder": "Namespace to mint in",
    "mint.shoulder_opt": "omit to use the organisation's default",
    "mint.shoulder_default": "(the organisation's default)",
    "mint.shoulder_required": "At NAAN level and above the shoulder <b>must be explicit</b>, "
                              "so you cannot mint into another organisation's namespace "
                              "by mistake.",
    "mint.url": "Target URL",
    "mint.url_opt": "leave empty to return a description",
    "mint.url_hint": "An empty target is valid. For a physical object, with nowhere to "
                     "redirect to, this is the correct shape.",
    "mint.title_field": "Title",
    "mint.type": "Type",
    "mint.type_hint": "Pick from the list, or <b>type anything that is not in it</b> — "
                      "ERC's <code>what</code> constrains no vocabulary, so the "
                      "interface must not either.",
    "mint.submit": "Mint",
    "mint.flash": "minted",
    "mint.reserve": "Reserve it, do not publish yet",
    "mint.reserve_hint": "<b>The name is not put out into the world.</b> It does not "
                         "resolve, and it can still be withdrawn. Publish it from this "
                         "ARK's page when the object goes public.",
    "mint.reserved_note": "This ARK is <b>not published</b>. It does not resolve yet — "
                          "publish it when the object itself goes public.",
    "nav.arks": "ARKs issued",
    "ak.title": "ARKs issued",
    "ak.lede": "This page shows <b>only what is within your reach</b> — a system "
               "administrator sees them all, an organisation's administrator sees its own.",
    "ak.search": "Search",
    "ak.search_ph": "ARK, target or title (x9abc / example.org / a dataset name)",
    "ak.ark": "ARK",
    "ak.target": "Points to",
    "ak.title_col": "Title",
    "ak.when": "Minted",
    "ak.by": "Minted by",
    "ak.none_target": "(no target)",
    "ak.empty": "No ARK matches.",
    "ak.prev": "Previous",
    "ak.next": "Next",
    "ak.page": "page {n}",
    "ak.detail": "This ARK",
    "ak.history": "Where it used to point",
    "ak.hist_lede": "<b>The previous targets are kept.</b> Having declared "
                    "<code>NR</code>, the identifier itself does not change — only "
                    "where it points does, so that has to be traceable.",
    "ak.hist_when": "When",
    "ak.hist_what": "What",
    "ak.hist_from": "From",
    "ak.hist_to": "To",
    "ak.hist_by": "By",
    "ak.hist_ip": "From address",
    "ak.hist_none": "It has never been repointed.",
    "ak.act.update": "repointed",
    "ak.act.publish": "published",
    "ak.act.tombstone": "declared lost",
    "ak.act.hold": "redirection held",
    "ak.act.release_hold": "hold lifted",
    "ak.hold": "Hold on redirection",
    "ak.hold_lede": "When the target cannot be trusted, stop <b>the redirect only</b>. "
    "The identifier stays alive and the description keeps answering "
    "(this is not the same as declaring it lost).",
    "ak.hold_on": "On hold",
    "ak.hold_until": "Until",
    "ak.hold_reason": "Reason",
    "ak.hold_reason_hint": "<b>This is published.</b> Keep it non-sensitive.",
    "ak.hold_days": "Days",
    "ak.hold_days_hint": "It lifts itself when this passes. The maximum is",
    "ak.hold_do": "Hold redirection",
    "ak.hold_off": "Lift the hold",
    "ak.open": "Open",
    "ak.gone": "(none)",
    "ak.org": "Organisation",
    "ak.org_all": "All organisations",
    "ak.filter": "Filter",
    "ak.meta": "Description (ERC / Dublin Core)",
    "ak.meta_lede": "<b>This is what <code>?</code> and <code>??</code> publish.</b> "
                    "Empty fields are not shown — ERC is a format that does not write "
                    "down absence.",
    "ak.meta_empty": "No description recorded.",
    "ak.f.title": "Title (what)",
    "ak.f.who": "who",
    "ak.f.when": "when",
    "ak.f.type": "Type",
    "ak.f.identifier": "Other identifier",
    "ak.f.format": "Format",
    "ak.f.relation": "Relation",
    "ak.f.source": "Source",
    "ak.f.commitment": "Commitment for this object",
    "ak.f.metadata": "Where the metadata lives",
    "ak.shoulder": "Namespace",
    "ak.updated": "Last changed",
    "ak.resolve": "Try resolving it",
    "ak.state": "State",
    "ak.state_all": "Published and reserved",
    "ak.public": "Public",
    "ak.reserved": "Reserved",
    "ak.published_at": "Published",
    "ak.publication": "Publication",
    "ak.pub_lede": "<b>Until it is published this ARK does not resolve.</b> The name has "
                   "not gone out yet, so it can still be deleted outright.",
    "ak.pub_done_lede": "<b>This ARK is public.</b> If the object is merely gone, "
                        "tombstone it or clear its target instead of removing it — "
                        "<b>that way the identifier keeps resolving</b>.",
    "ak.publish": "Publish",
    "ak.publish_warn": "Publishing starts resolution. It can be withdrawn later, but "
                       "<b>withdrawing does not unmake the fact that it went out</b> — "
                       "deleting it afterwards needs a reason and a retyped ARK.",
    "ak.republish_note": "<b>This ARK was published once before.</b> You can publish it "
                         "again, but the gap cannot be filled — whoever resolved it in "
                         "the meantime got a 404.",
    "ak.unpublish": "Withdraw from publication",
    "ak.unpub_lede": "<b>The row stays, so it can be published again.</b> While it is "
                     "withdrawn this ARK does not resolve. <b>The name never comes to "
                     "mean something else</b> — a stale reference simply gets a 404.",
    "ak.unpub_reason": "Why it is withdrawn",
    "ak.unpub_reason_hint": "<b>Required.</b> Someone may be citing it already, and "
                            "there is no way to know that from here.",
    "ak.unpub_confirm": "Retype the ARK to confirm",
    "ak.unpub_confirm_hint": "So that walking a list cannot act on everything by accident.",
    "ak.withdraw": "Withdraw and delete",
    "ak.withdraw_lede": "<b>It can be deleted because it was never published.</b> The row "
                        "goes, but the name is never assigned again — a reserved "
                        "identifier may already be in someone's hands.",
    "ak.withdraw_exposed_lede": "<b>This ARK has been published.</b> It is withdrawn now, "
                                "so it can be deleted — but <b>deleting does not come "
                                "back</b>. To put it back, press Publish instead. The "
                                "name is never assigned again.",
    "ak.withdraw_reason": "Why it is withdrawn",
    "ak.withdraw_reason_hint": "The only account left of a row that is gone "
                               "(it is not published anywhere).",
    "ak.withdrawn_flash": "withdrawn",
    "ak.purge": "Purge",
    "ak.purge_title": "Purging a published ARK",
    "ak.purge_lede": "<b>This breaks the promise.</b> A published ARK is meant to keep "
                     "resolving, and purging it breaks every reference still out there "
                     "— use it only as a way out for a removal order, or for what "
                     "should never have been published. <b>If you are unsure, withdraw "
                     "it from publication above</b> — that one comes back.",
    "ak.purge_keeps": "<b>The name is not freed.</b> It is never minted again, so it "
                      "cannot come to mean something else afterwards (a stale reference "
                      "simply gets a 404). The reason and the audit entry remain.",
    "ak.purge_reason": "Why it is purged",
    "ak.purge_reason_hint": "<b>Required.</b> It will be the only account left of the "
                            "identifier.",
    "ak.purge_confirm": "Type the ARK again to confirm",
    "ak.purge_confirm_hint": "So that walking a list cannot delete by accident.",
}
