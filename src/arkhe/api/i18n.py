"""管理画面の国際化。日本語と英語を既定で持つ。

gettext ではなく辞書にしてある。理由は 2 つ:
  - `.mo` のコンパイルがイメージのビルド手順に増える（この規模では割に合わない）
  - 言語を足すのがモジュール 1 つで済み、翻訳の抜けが起動時に分かる

将来 translator に渡す必要が出たら、この辞書から `.po` を吐けばよい。

言語の決め方は **`?lang=` → cookie → `Accept-Language` → 既定(ja)** の順。
明示の選択を記憶するので、切り替えたら以降のページでも保たれる。
"""

from __future__ import annotations

from fastapi import Request

DEFAULT = "ja"
LANGS = {"ja": "日本語", "en": "English"}
COOKIE = "arkhe_lang"

JA: dict[str, str] = {
    # 骨格
    "app.subtitle": "ARK 識別子基盤",
    "nav.ledger": "台帳",
    "nav.actions": "操作",
    "nav.overview": "組織管理",
    "nav.clients": "利用者と鍵",
    "nav.mint": "ARK を採番",
    "nav.audit": "監査ログ",
    "lang.label": "言語",
    # 状態
    "st.active": "採番可",
    "st.reserved": "予約",
    "st.delegated": "委譲",
    "st.retired": "引退",
    "au.system": "システム管理者",
    "au.naan": "NAAN 管理者",
    "au.manager": "組織管理者",
    # 委譲の構造
    "ov.title": "組織管理",
    # **一般の読み手を想定する。** ここは台帳を初めて見る人が最初に開く画面なので、
    # **用語は捨てず、括弧で残す。** 平易な言い方を先に置いて用語を添えると、
    # 初めての人はそのまま読め、用語を知っている人は対応が取れる。
    # 用語を消すと、この画面と仕様書・CLI・API の語が食い違ってしまう。
    "ov.lede": "<b>ARK を発行できる組織と、それぞれに渡した名前空間（shoulder）の"
               "一覧です。</b>ARK には、発行を取りまとめる中央の登録機関がありません。"
               "組織番号（NAAN）を預かった側が、その下に名前空間を渡し（委譲）、"
               "渡された側がその中で識別子を発行します。"
               "<b>発行した識別子をどこまで維持するかも、それぞれが決めて公開します</b>"
               "——各行に出ている「約束の水準（commitment level）」がそれです。",
    "ov.naans": "組織番号（NAAN）",
    "ov.authoritative": "自組織で管理（権威あり）",
    "ov.delegated_to": "委譲先",
    "ov.no_manager": "組織に未割当",
    "ov.records": "件",
    "ov.quota": "上限",
    "ov.per_day": "／日",
    "ov.succeeded": "承継済",
    "ov.inactive": "停止",
    "ov.manage": "操作",
    "ov.add_naan": "NAAN を登録",
    "ov.onboard": "組織を追加",
    "ov.add_shoulder": "名前空間を追加",
    "ov.empty": "まだ NAAN が登録されていません。",
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
    # 主体
    "cl.title": "利用者と鍵",
    "cl.lede": "<b>ARK を発行できる利用者と、その鍵の一覧です。</b>"
               "利用者は 2 種類——組織のシステム（API キーで名乗る）と、"
               "この画面に入る人（外部のログインで名乗る）。"
               "<b>どこまで届くかは登録したときに決まり</b>、"
               "リクエストやトークンの要求では広げられません。",
    "cl.issued": "資格情報を発行しました",
    "cl.issued_warn": "<b>この値はもう二度と表示されません。</b>いま控えてください。"
                      "保存しているのはハッシュだけです。",
    "cl.principals": "利用者",
    "cl.reach": "到達範囲",
    "cl.scope": "scope",
    "cl.creds": "資格情報",
    "cl.live": "有効",
    "cl.dead": "失効",
    "cl.open": "開く",
    "cl.add": "利用者を登録",
    "cl.disabled": "無効",
    "cl.all_naans": "全 NAAN",
    "cl.empty": "利用者がまだ登録されていません。",
    # 監査
    "au.title": "監査ログ",
    "au.lede": "<b>NAAN 以上に届く操作は全件記録します。</b>"
               "届く範囲が広いほど、後から誰が何をしたかを辿れる必要が高いためです。",
    "au.recent": "直近の操作",
    "au.at": "日時",
    "au.who": "主体",
    "au.action": "操作",
    "au.target": "対象",
    "au.detail": "詳細",
    "au.count": "件",
    "au.empty": "記録がありません。",
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
    "naan.new.title": "NAAN を登録",
    "naan.edit.title": "NAAN の設定",
    "naan.lede": "<b>NAA ポリシーは名前空間を配る側の宣言</b>です。"
                 "この NAAN の配下すべてにかかるので、組織単位では変えられません"
                 "（組織が自分について述べるのは<b>約束の水準</b>のほう）。",
    "naan.f.naan": "組織番号（NAAN）",
    "naan.f.naan_hint": "ARK Alliance から交付された番号。<b>後から変えられません。</b>",
    "naan.f.name": "組織名",
    "naan.f.description": "説明",
    "naan.f.policy": "NAA ポリシー",
    "naan.f.policy_hint": "<code>NP | NR, OP, CC | 2026 | &lt;URL&gt;</code> の形。"
                          "<b><code>?</code> と <code>??</code> でそのまま公開されます。</b>",
    "naan.f.minter": "採番の案内先",
    "naan.f.minter_hint": "採番を外で行っている場合の行き先。"
                          "<code>/.well-known/ark</code> で公開されます。",
    "naan.f.authoritative": "この NAAN の権威を持つ",
    "naan.f.authoritative_hint": "持つなら、未知の名前に <code>404</code> と答えます"
                                 "（＝「無い」と言える）。持たないなら委譲先が要ります。",
    "naan.f.redirect": "委譲先",
    "manager.new.title": "組織を追加",
    "manager.edit.title": "組織の設定",
    # **追加のときは、まず何が起きるかを述べる。** ここを開く人は、この操作が
    # 名前空間の受け渡しでもあることをまだ知らない。
    "manager.new.lede": "組織を追加すると、<b>同時に名前空間（shoulder）を 1 つ渡します</b>。"
                        "この 2 つは分けられません——名前空間を持たない組織は識別子を"
                        "発行できないので、置いても意味がないからです。"
                        "以後その組織は、渡した名前空間の中で ARK を発行します。",
    "manager.lede": "<b>約束の水準は組織自身の宣言</b>です。"
                    "だから組織管理者も自分の分は変えられます——"
                    "採番上限はそうではありません（配った側が課すもの）。",
    "manager.f.naan": "組織番号（NAAN）",
    "manager.f.name": "組織名",
    "manager.f.name_hint": "<b>内部専用です。</b>公開しません"
                           "（shoulder から組織が読めてはいけないため）。",
    "manager.f.shoulder": "委譲する名前空間",
    "manager.f.shoulder_hint": "<code>/x9</code> のように <code>/</code> で始めます。"
                               "<b>組織の登録と名前空間の委譲は必ず対で起きます。</b>",
    "manager.f.commitment": "約束の水準",
    "manager.f.commitment_hint": "<b><code>?</code> と <code>??</code> でそのまま公開されます。</b>"
                                 "組織が述べたことだけを入れてください——"
                                 "既定値を宣言として出すのは、何も出さないより悪い。"
                                 "<b>下げるのも正当な操作です。</b>",
    "manager.f.quota": "1 日あたりの採番上限",
    "manager.f.quota_hint": "空にすると無制限。",
    "cm.not-guaranteed": "約束しない",
    "cm.permanent-dynamic": "永続・内容は変わりうる",
    "cm.permanent-stable": "永続・内容は実質的に変わらない",
    "cm.permanent-unchanging": "永続・内容は変えない",
    "cm.descriptive-only": "記述だけ（対象がオンラインに無い）",
    "shoulder.new.title": "名前空間（shoulder）を追加",
    "shoulder.edit.title": "shoulder の設定",
    "shoulder.lede": "<b>一度配った名前空間は取り戻せません。</b>"
                     "<code>NR</code> を宣言している以上、既存の ARK は解決し続けます。"
                     "使わなくなったものは消すのではなく <b>retired</b> にします。",
    "shoulder.f.naan": "組織番号（NAAN）",
    "shoulder.f.shoulder": "shoulder",
    "shoulder.f.shoulder_hint": "<code>/x9</code> のように <code>/</code> で始めます。",
    "shoulder.f.manager": "組織",
    "shoulder.f.reserve": "押さえるだけで採番させない",
    "shoulder.f.status": "状態",
    "shoulder.f.status_hint": "<b>retired からは戻せません</b>"
                              "（引退した名前空間の再開は NR 違反の芽）。",
    "shoulder.f.minter": "採番の行き先",
    "shoulder.f.minter_hint": "<b>delegated</b> のときだけ意味を持ちます。",
    "shoulder.f.redirect": "解決の委譲先",
    "shoulder.f.redirect_hint": "<code>${blade}</code> が名前に置き換わります。",
    "shoulder.f.note": "運用の記録",
    # 利用者の登録と鍵の発行
    "cu.new.title": "利用者を登録",
    "cu.edit.title": "利用者",
    "cu.new.lede": "<b>まず何者かを決めます。</b>鍵はここでは出しません——"
                   "<b>人には鍵を出さない</b>ので、機械として登録したときだけ次の画面で"
                   "発行できます。人の身元は外部のログインが保証します。",
    "cu.lede": "この利用者に、どの鍵で、どこまで届く権限があるか。"
               "<b>鍵の平文は発行の直後に一度だけ表示されます。</b>",
    "cu.f.client_id": "識別子",
    "cu.f.client_id_hint": "機械なら分かりやすい名前（<code>univ-repo</code> など）。"
                           "<b>人なら、認証サーバが返す識別子</b>"
                           "（メールアドレスや eppn）をそのまま入れます。",
    "cu.f.person": "人として登録する",
    "cu.f.person_hint": "外部のログイン専用になり、<b>鍵は持てません</b>。"
                        "その人が組織を離れても鍵が生き残る、という事態を避けるためです。",
    "cu.f.manager": "所属組織",
    "cu.f.shoulder": "名前空間に固定する",
    "cu.f.shoulder_hint": "固定すると、鍵が漏れても<b>他組織の名前空間には届きません</b>。",
    "cu.f.scopes": "できること",
    "cu.f.label": "ラベル",
    "cu.f.label_hint": "鍵を入れ替えるときの目印。空でもかまいません。",
    "cu.machine": "機械",
    "cu.person": "人",
    "cu.reach": "届く範囲",
    "cu.scopes": "できること",
    # 鍵
    "cu.keys": "鍵",
    "cu.key.issue": "鍵を発行",
    "cu.key.kind": "種別",
    "cu.key.api_key": "API キー（Bearer でそのまま送る）",
    "cu.key.client_secret": "client_secret（OAuth2 でトークンに換える）",
    "cu.key.label": "ラベル",
    "cu.key.issued": "鍵を発行しました",
    "cu.key.once": "<b>この値はもう二度と表示されません。</b>いま控えてください。"
                   "保存しているのはハッシュだけです。",
    "cu.key.none": "まだ鍵がありません。",
    "cu.key.person": "人の主体には鍵を発行しません。身元は外部のログインが保証します。",
    "cu.key.created": "発行",
    "cu.key.used": "最終利用",
    "cu.key.never": "未使用",
    "cu.key.revoke": "失効させる",
    "cu.key.revoked": "失効",
    "cu.key.revoke_note": "<b>行は消しません。</b>いつ失効したかを残します。"
                          "入れ替えるときは、新しい鍵を配ってから古い方を失効させてください。",
    # パスワード
    "cu.pw.title": "パスワード",
    "cu.pw.lede": "<code>ARKHE_ADMIN_LOGIN=password</code> の構成でだけ使います。12 文字以上。",
    "cu.pw.set": "設定する",
    # ログインに戻す画面
    "notice.retry": "ログインし直す",
    "notice.expired.h": "ログインの往復が失効しました",
    "notice.expired.m": "認証サーバへ送り出してから戻ってくるまでに時間が空きすぎました。"
                        "もう一度ログインしてください。",
    "notice.state.h": "この応答は受け取れません",
    "notice.state.m": "こちらが送り出した要求と、戻ってきた応答が対応していません"
                      "（別の要求への応答を受け取らないための確認です）。"
                      "もう一度ログインしてください。",
    "notice.denied.h": "認証サーバが拒否しました",
    "notice.denied.m": "認証サーバから「{err}」と返されました。"
                       "権限や設定について、システム管理者にお問い合わせください。",
    "notice.nologin.h": "この構成にログイン画面はありません",
    "notice.nologin.m": "この arkhe は、ID とパスワードで入る構成になっていません。"
                        "入り方はシステム管理者にお問い合わせください。",
    # 認可サーバに寄せた構成での説明
    "cu.key.oidc": "<b>この構成では、トークンは認可サーバが出します。</b>"
                   "arkhe が持っているのは、上の識別子と<b>どこまで届くか</b>の"
                   "対応だけです。秘密は認可サーバ側で作り、そこで失効させます——"
                   "失効が 1 か所で効くのがこの形の利点です。",
    "cu.key.oidc_where": "秘密を作る場所: ",
    "cu.key.oidc_match": "認可サーバが出すトークンの <code>client_id</code>（Keycloak なら "
                         "<code>azp</code>）が、上の識別子と<b>同じ文字列</b>である"
                         "必要があります。",
    "cu.key.none_kind": "<b>この構成で発行できる鍵はありません。</b>"
                        "<code>ARKHE_ADMIN_LOGIN</code> ではなく "
                        "<code>ARKHE_AUTH</code> に <code>apikey</code> か "
                        "<code>oauth2</code> を入れると、ここから発行できるようになります。",
    # 認可サーバに寄せた構成での「登録」の意味
    "cu.new.lede_oidc": "<b>ここでの登録が、認可サーバの主体と arkhe の到達範囲を"
                        "結びつけます。</b>鍵はこの構成では出しません——秘密は認可"
                        "サーバが持っています。<b>登録が無ければ、正しいトークンを"
                        "持っていても通りません</b>：認可サーバで認証できることと、"
                        "この名前空間を触ってよいことは別だからです。",
    "cu.f.client_id_oidc": "<b>認可サーバが送ってくる文字列をそのまま入れます。</b>"
                           "機械なら <code>azp</code>（無ければ <code>client_id</code>、"
                           "それも無ければ <code>sub</code>）、人なら "
                           "<code>preferred_username</code>（無ければ "
                           "<code>email</code>、それも無ければ <code>sub</code>）。"
                           "1 文字でも違うと照合できません。",
    "cu.state": "状態",
    "cu.state.on": "有効",
    "cu.state.off": "停止中",
    "cu.disable": "この利用者を止める",
    "cu.enable": "戻す",
    "cu.disable_note": "<b>認可サーバに寄せた構成では、これが arkhe 側の唯一の止め方です。</b>"
                       "鍵を持っていないので、失効させるものがありません。"
                       "止めると、認可サーバが出したトークンでもこの名前空間には入れなくなります"
                       "（他の資源には影響しません）。",
    "cu.enable_note": "止まっています。戻すと、また入れるようになります。",
    "cu.key.only_one": "この構成で通るのは <code>{kind}</code> だけです。"
                       "もう一方も選べるようにするには <code>ARKHE_AUTH</code> に "
                       "<code>{missing}</code> を足してください——足さずに出した鍵は"
                       "どこからも通りません。",
    "login.title": "管理画面にログイン",
    "login.id": "ID",
    "login.id_ph": "メールアドレスなど",
    "login.password": "パスワード",
    "login.submit": "ログイン",
    "login.failed": "ID かパスワードが違います",
    "login.logout": "ログアウト",
}

EN: dict[str, str] = {
    "app.subtitle": "ARK identifier infrastructure",
    "nav.ledger": "Ledger",
    "nav.actions": "Actions",
    "nav.overview": "Organisations",
    "nav.clients": "Users & keys",
    "nav.mint": "Mint an ARK",
    "nav.audit": "Audit log",
    "lang.label": "Language",
    "st.active": "mintable",
    "st.reserved": "reserved",
    "st.delegated": "delegated",
    "st.retired": "retired",
    "au.system": "System administrator",
    "au.naan": "NAAN administrator",
    "au.manager": "Organisation administrator",
    "ov.title": "Organisations",
    "ov.lede": "<b>The organisations that can issue ARKs, and the namespace (shoulder) "
               "each one was given.</b> ARK has no central body issuing identifiers on "
               "everyone's behalf. Whoever holds the number (the NAAN) hands a namespace "
               "to an organisation — this is called delegation — and the organisation "
               "issues identifiers within it. <b>How far each organisation undertakes to "
               "keep those identifiers working is also its own to state</b>: that is the "
               "commitment level shown on each row.",
    "ov.naans": "Organisation numbers (NAAN)",
    "ov.authoritative": "run here (authoritative)",
    "ov.delegated_to": "delegated to",
    "ov.no_manager": "not assigned",
    "ov.records": "records",
    "ov.quota": "cap",
    "ov.per_day": "/day",
    "ov.succeeded": "succeeded",
    "ov.inactive": "inactive",
    "ov.manage": "Manage",
    "ov.add_naan": "Register a NAAN",
    "ov.onboard": "Add an organisation",
    "ov.add_shoulder": "Add a namespace",
    "ov.empty": "No NAAN registered yet.",
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
    "cl.title": "Users & keys",
    "cl.lede": "<b>Who may issue ARKs, and with which key.</b> There are two kinds: "
               "an organisation's systems, which identify themselves with an API key, and "
               "people who sign in here, who identify themselves through an external "
               "login. <b>How far each one reaches is fixed when it is registered</b> — "
               "it cannot be widened by a request or a token grant.",
    "cl.issued": "Credential issued",
    "cl.issued_warn": "<b>This value will never be shown again.</b> Copy it now. "
                      "Only its hash is stored.",
    "cl.principals": "Users",
    "cl.reach": "Reach",
    "cl.scope": "Scopes",
    "cl.creds": "Credentials",
    "cl.live": "active",
    "cl.dead": "revoked",
    "cl.open": "Open",
    "cl.add": "Register a user",
    "cl.disabled": "disabled",
    "cl.all_naans": "all NAANs",
    "cl.empty": "No user registered yet.",
    "au.title": "Audit log",
    "au.lede": "<b>Every action that reaches NAAN scope or wider is recorded.</b> "
               "The wider the reach, the more it matters that you can trace who did what.",
    "au.recent": "Recent actions",
    "au.at": "When",
    "au.who": "Principal",
    "au.action": "Action",
    "au.target": "Target",
    "au.detail": "Detail",
    "au.count": "entries",
    "au.empty": "Nothing recorded.",
    "f.paren_open": " (",
    "f.paren_close": ")",
    "f.save": "Save",
    "f.create": "Create",
    "f.cancel": "Cancel",
    "f.saved": "Saved.",
    "f.optional": "optional",
    "f.readonly_here": "cannot be changed here",
    "naan.new.title": "Register a NAAN",
    "naan.edit.title": "NAAN settings",
    "naan.lede": "<b>The NAA policy is the declaration of the side handing namespaces "
                 "out.</b> It covers everything under this NAAN, so an organisation "
                 "cannot change it — what an organisation states about itself is its "
                 "<b>commitment level</b>.",
    "naan.f.naan": "Organisation number (NAAN)",
    "naan.f.naan_hint": "The number issued by the ARK Alliance. <b>It cannot be changed "
                        "later.</b>",
    "naan.f.name": "Organisation",
    "naan.f.description": "Description",
    "naan.f.policy": "NAA policy",
    "naan.f.policy_hint": "In the form <code>NP | NR, OP, CC | 2026 | &lt;URL&gt;</code>. "
                          "<b>Published verbatim by <code>?</code> and <code>??</code>.</b>",
    "naan.f.minter": "Where minting happens",
    "naan.f.minter_hint": "Where to go if minting happens elsewhere. Published at "
                          "<code>/.well-known/ark</code>.",
    "naan.f.authoritative": "You hold authority over this NAAN",
    "naan.f.authoritative_hint": "If you do, an unknown name is answered with "
                                 "<code>404</code> — you can say it does not exist. "
                                 "If you do not, a delegation target is required.",
    "naan.f.redirect": "Delegate to",
    "manager.new.title": "Add an organisation",
    "manager.edit.title": "Organisation settings",
    "manager.new.lede": "Adding an organisation <b>hands it one namespace (shoulder) at "
                        "the same time</b>. The two cannot be separated: an organisation "
                        "with no namespace cannot issue identifiers, so there would be no "
                        "point putting one here. From then on it issues ARKs within that "
                        "namespace.",
    "manager.lede": "<b>The commitment level is the organisation's own declaration</b>, "
                    "which is why an organisational administrator may change their own. "
                    "The minting limit is not — that is imposed by the side handing the "
                    "namespace out.",
    "manager.f.naan": "Organisation number (NAAN)",
    "manager.f.name": "Organisation",
    "manager.f.name_hint": "<b>Internal only.</b> Never published — a shoulder must not "
                           "reveal which organisation holds it.",
    "manager.f.shoulder": "Namespace to delegate",
    "manager.f.shoulder_hint": "Begins with <code>/</code>, as in <code>/x9</code>. "
                               "<b>Registering the organisation and delegating the "
                               "namespace always happen together.</b>",
    "manager.f.commitment": "Commitment level",
    "manager.f.commitment_hint": "<b>Published verbatim by <code>?</code> and "
                                 "<code>??</code>.</b> Put in only what the organisation "
                                 "has stated — publishing a default as a declaration is "
                                 "worse than publishing nothing. <b>Lowering it is a "
                                 "legitimate operation.</b>",
    "manager.f.quota": "Minting limit per day",
    "manager.f.quota_hint": "Leave empty for unlimited.",
    "cm.not-guaranteed": "No commitment",
    "cm.permanent-dynamic": "Permanent; content may change",
    "cm.permanent-stable": "Permanent; content substantially unchanged",
    "cm.permanent-unchanging": "Permanent; content not changed",
    "cm.descriptive-only": "Description only (the object is not online)",
    "shoulder.new.title": "Add a namespace (shoulder)",
    "shoulder.edit.title": "Shoulder settings",
    "shoulder.lede": "<b>A namespace once handed out cannot be taken back.</b> Having "
                     "declared <code>NR</code>, existing ARKs go on resolving. One you "
                     "stop using is <b>retired</b>, not deleted.",
    "shoulder.f.naan": "Organisation number (NAAN)",
    "shoulder.f.shoulder": "Shoulder",
    "shoulder.f.shoulder_hint": "Begins with <code>/</code>, as in <code>/x9</code>.",
    "shoulder.f.manager": "Organisation",
    "shoulder.f.reserve": "Hold it without allowing minting",
    "shoulder.f.status": "Status",
    "shoulder.f.status_hint": "<b>There is no way back from retired</b> (reopening a "
                              "retired namespace is the seed of an NR violation).",
    "shoulder.f.minter": "Where minting goes",
    "shoulder.f.minter_hint": "Meaningful only when <b>delegated</b>.",
    "shoulder.f.redirect": "Delegate resolution to",
    "shoulder.f.redirect_hint": "<code>${blade}</code> is replaced by the name.",
    "shoulder.f.note": "Operational note",
    "cu.new.title": "Register a user",
    "cu.edit.title": "User",
    "cu.new.lede": "<b>First decide what it is.</b> No key is issued here — <b>people hold "
                   "no keys</b>, so only something registered as a machine can be given "
                   "one on the next page. A person's identity is vouched for by an "
                   "external login.",
    "cu.lede": "What this user may do, with which key, and how far it reaches. "
               "<b>A key's plaintext is shown once, just after it is issued.</b>",
    "cu.f.client_id": "Identifier",
    "cu.f.client_id_hint": "For a machine, a name you will recognise "
                           "(<code>univ-repo</code>). <b>For a person, whatever the "
                           "authentication server returns</b> — an email address, an "
                           "eppn — verbatim.",
    "cu.f.person": "Register as a person",
    "cu.f.person_hint": "External login only; <b>it can hold no key</b>. A key would "
                        "outlive the person's departure from the organisation.",
    "cu.f.manager": "Organisation",
    "cu.f.shoulder": "Pin to a namespace",
    "cu.f.shoulder_hint": "Pinned, a leaked key still <b>cannot reach another "
                          "organisation's namespace</b>.",
    "cu.f.scopes": "What it may do",
    "cu.f.label": "Label",
    "cu.f.label_hint": "A marker for when you rotate the key. May be left empty.",
    "cu.machine": "machine",
    "cu.person": "person",
    "cu.reach": "Reaches",
    "cu.scopes": "May do",
    "cu.keys": "Keys",
    "cu.key.issue": "Issue a key",
    "cu.key.kind": "Kind",
    "cu.key.api_key": "API key (sent as-is with Bearer)",
    "cu.key.client_secret": "client_secret (exchanged for a token via OAuth2)",
    "cu.key.label": "Label",
    "cu.key.issued": "Key issued",
    "cu.key.once": "<b>This value will never be shown again.</b> Copy it now. Only its "
                   "hash is stored.",
    "cu.key.none": "No key yet.",
    "cu.key.person": "People are issued no keys. Their identity is vouched for by an "
                     "external login.",
    "cu.key.created": "Issued",
    "cu.key.used": "Last used",
    "cu.key.never": "never",
    "cu.key.revoke": "Revoke",
    "cu.key.revoked": "revoked",
    "cu.key.revoke_note": "<b>The row is not deleted</b> — when it stopped remains. To "
                          "rotate, hand out the new key first, then revoke the old one.",
    "cu.pw.title": "Password",
    "cu.pw.lede": "Used only where <code>ARKHE_ADMIN_LOGIN=password</code>. 12 characters or more.",
    "cu.pw.set": "Set",
    "notice.retry": "Sign in again",
    "notice.expired.h": "The sign-in round trip expired",
    "notice.expired.m": "Too much time passed between being sent to the authentication "
                        "server and coming back. Please sign in again.",
    "notice.state.h": "This response cannot be accepted",
    "notice.state.m": "The response that came back does not correspond to the request "
                      "that was sent — a check that stops a response meant for another "
                      "request from being accepted. Please sign in again.",
    "notice.denied.h": "The authentication server refused",
    "notice.denied.m": "The authentication server answered \u201c{err}\u201d. Ask a "
                       "system administrator about your access and the configuration.",
    "notice.nologin.h": "This deployment has no sign-in page",
    "notice.nologin.m": "This arkhe is not configured for signing in with an ID and "
                        "password. Ask a system administrator how to get in.",
    "cu.key.oidc": "<b>In this deployment the tokens come from the authorization "
                   "server.</b> What arkhe holds is the mapping from the identifier "
                   "above to <b>how far it reaches</b>. The secret is created and "
                   "revoked at the authorization server — revocation taking effect in "
                   "one place is the point of this arrangement.",
    "cu.key.oidc_where": "Where the secret is created: ",
    "cu.key.oidc_match": "The <code>client_id</code> in the token the authorization "
                         "server issues (<code>azp</code> in Keycloak) must be the "
                         "<b>same string</b> as the identifier above.",
    "cu.key.none_kind": "<b>No key can be issued in this deployment.</b> Add "
                        "<code>apikey</code> or <code>oauth2</code> to "
                        "<code>ARKHE_AUTH</code> (not <code>ARKHE_ADMIN_LOGIN</code>) "
                        "to issue one here.",
    "cu.new.lede_oidc": "<b>Registering here is what ties a subject at the "
                        "authorization server to a reach in arkhe.</b> No key is issued "
                        "in this deployment — the secret lives at the authorization "
                        "server. <b>Without this registration even a valid token is "
                        "refused</b>: being able to authenticate is not the same as "
                        "being allowed into this namespace.",
    "cu.f.client_id_oidc": "<b>Enter the string the authorization server sends, "
                           "verbatim.</b> For a machine that is <code>azp</code> "
                           "(failing that <code>client_id</code>, then <code>sub</code>); "
                           "for a person <code>preferred_username</code> (failing that "
                           "<code>email</code>, then <code>sub</code>). One character "
                           "out and it will not match.",
    "cu.state": "State",
    "cu.state.on": "active",
    "cu.state.off": "stopped",
    "cu.disable": "Stop this user",
    "cu.enable": "Restore",
    "cu.disable_note": "<b>Where authentication is delegated, this is the only way to "
                       "stop a user from arkhe's side.</b> It holds no key, so there is "
                       "nothing to revoke. Stopped, a token from the authorization "
                       "server no longer gets into this namespace — other resources are "
                       "unaffected.",
    "cu.enable_note": "Stopped. Restoring lets it in again.",
    "cu.key.only_one": "Only <code>{kind}</code> authenticates in this deployment. To "
                       "offer the other as well, add <code>{missing}</code> to "
                       "<code>ARKHE_AUTH</code> — a key issued without it goes nowhere.",
    "login.title": "Sign in to the admin interface",
    "login.id": "ID",
    "login.id_ph": "your email address, for example",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.failed": "That ID and password do not match",
    "login.logout": "Sign out",
}

CATALOGS = {"ja": JA, "en": EN}

#: 翻訳の抜けは**起動時に落とす**。片方だけ足して気づかない、を防ぐ。
_missing = {lang: sorted(set(JA) - set(cat)) for lang, cat in CATALOGS.items()}
if any(_missing.values()):  # pragma: no cover - 開発時にしか起きない
    raise RuntimeError(f"翻訳の抜け: { {k: v for k, v in _missing.items() if v} }")


def pick(request: Request) -> str:
    """`?lang=` → cookie → `Accept-Language` → 既定 の順で決める。"""
    q = request.query_params.get("lang")
    if q in CATALOGS:
        return q
    c = request.cookies.get(COOKIE)
    if c in CATALOGS:
        return c
    for part in request.headers.get("accept-language", "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in CATALOGS:
            return tag[:2]
    return DEFAULT


def translator(lang: str):
    cat = CATALOGS.get(lang, JA)
    def t(key: str) -> str:
        return cat.get(key, key)
    return t
