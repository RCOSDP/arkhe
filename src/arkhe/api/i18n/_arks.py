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
    "ak.act.tombstone": "失われたと宣言",
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
    "ak.act.tombstone": "declared lost",
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
}
