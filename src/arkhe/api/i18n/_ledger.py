"""台帳の文言。組織と名前空間。委譲の構造と、それを組む操作。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
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
    "hold.f.legend": "転送の保留",
    "hold.f.lede": "この名前空間の<b>転送だけ</b>を一時的に止めます。"
    "解決は続き、記述は答え続けます——委譲先が落ちた・行き先が信用できない、"
    "といった場面のためのものです。",
    "hold.f.days": "日数",
    "hold.f.days_hint": "過ぎれば自動的に戻ります。上限は",
    "hold.f.reason": "理由",
    "hold.f.reason_hint": "<b>公開の口に出ます。</b>機微は書かないこと。",
    "hold.f.on": "保留中",
    "hold.f.until": "この日時まで",
    "hold.f.release": "保留を外す",
    "hold.none": "止めている転送はありません。",
    "shoulder.f.minter": "採番の行き先",
    "shoulder.f.minter_hint": "<b>delegated</b> のときだけ意味を持ちます。",
    "shoulder.f.redirect": "解決の委譲先",
    "shoulder.f.redirect_hint": "<code>${blade}</code> が名前に置き換わります。",
    "shoulder.f.note": "運用の記録",
    # 組織に何を任せ、何を制限するか
    "np.title": "この名前空間の決まり",
    "np.lede": "<b>配下の組織すべてにかかる既定です。</b>組織ごとの設定は"
               "ここから<b>狭めるだけ</b>で、広げられません。"
               "組織が増えると 1 つずつ掛けるのは現実的でないので、原則はここに置きます。",
    "np.at_create": "登録の時点で決められます。あとから変えられますが、"
                    "<b>後回しにすると掛け忘れが残ります</b>。",
    "op.from_naan": "名前空間の決まりで既に絞られています：",
    "op.narrow_only": "ここで選べるのは<b>さらに狭めること</b>だけです。"
                      "広げるには名前空間の決まりのほうを変えてください。",
    "op.title": "この組織に任せること",
    "op.lede": "<b>名前空間を配る側が決めます。</b>組織自身では変えられません"
               "——課された制限を課された側が外せては意味がないからです。",
    "op.at_create": "迎える時点で決められます。あとから変えられますが、"
                    "<b>後回しにすると掛け忘れが残ります</b>。",
    "op.auth": "許す入り方",
    "op.auth_hint": "何も選ばなければ制限なし（構成の既定に従う）。"
                    "<b>発行時だけでなく認証時にも効きます</b>——"
                    "制限を掛ける前に出した鍵も、以後は通りません。",
    "op.self": "自分で利用者を登録してよい",
    "op.self_hint": "許さない場合、この組織の利用者は NAAN 管理者が登録します。"
                    "誰が入れるかを一手に把握したいときに使います。",
    "op.max": "与えられる scope の上限",
    "op.max_hint": "何も選ばなければ制限なし。<b>上限であって既定ではありません。</b>"
                   "誰が作った利用者かによらず効きます——例外を作るなら、"
                   "この上限のほうを動かしてください。",
    "au.mech.apikey": "API キー",
    "au.mech.oauth2": "arkhe のトークン",
    "au.mech.oidc": "認可サーバ",
    "op.restricted": "制限あり",
    "op.no_self": "自己登録なし",
}

EN: dict[str, str] = {
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
    "hold.f.legend": "Hold on redirection",
    "hold.f.lede": "Temporarily stop <b>the redirect only</b> for this namespace. "
    "Resolution continues and descriptions keep answering — for when a delegate is "
    "down, or its target can no longer be trusted.",
    "hold.f.days": "Days",
    "hold.f.days_hint": "It lifts itself when this passes. The maximum is",
    "hold.f.reason": "Reason",
    "hold.f.reason_hint": "<b>This is published.</b> Keep it non-sensitive.",
    "hold.f.on": "On hold",
    "hold.f.until": "Until",
    "hold.f.release": "Lift the hold",
    "hold.none": "No redirection is being held.",
    "shoulder.f.minter": "Where minting goes",
    "shoulder.f.minter_hint": "Meaningful only when <b>delegated</b>.",
    "shoulder.f.redirect": "Delegate resolution to",
    "shoulder.f.redirect_hint": "<code>${blade}</code> is replaced by the name.",
    "shoulder.f.note": "Operational note",
    "np.title": "The rules of this namespace",
    "np.lede": "<b>The default for every organisation under it.</b> A per-organisation "
               "setting can only <b>narrow</b> this, never widen it. Applying the same "
               "restriction to each organisation stops being practical as they grow, so "
               "the rule belongs here.",
    "np.at_create": "These can be set as the number is registered. They can be changed "
                    "later, but <b>left for later they tend to stay unset</b>.",
    "op.from_naan": "Already narrowed by the namespace rules:",
    "op.narrow_only": "What you can do here is <b>narrow it further</b>. To widen it, "
                      "change the namespace rules instead.",
    "op.title": "What this organisation is trusted with",
    "op.lede": "<b>Decided by the side handing the namespace out.</b> The organisation "
               "cannot change it — a limit the limited party can lift is not a limit.",
    "op.at_create": "These can be set as you onboard. They can be changed later, "
                    "but <b>left for later they tend to stay unset</b>.",
    "op.auth": "Permitted ways in",
    "op.auth_hint": "Select none for no restriction (the deployment's default applies). "
                    "<b>It bites at authentication, not only at issuance</b> — a key "
                    "issued before the restriction stops working too.",
    "op.self": "May register its own users",
    "op.self_hint": "If not, a NAAN administrator registers this organisation's users. "
                    "Useful when you want one place that knows who can get in.",
    "op.max": "Ceiling on scopes",
    "op.max_hint": "Select none for no ceiling. <b>It is a ceiling, not a default.</b> "
                   "It applies whoever creates the user — to make an exception, move the "
                   "ceiling.",
    "au.mech.apikey": "API key",
    "au.mech.oauth2": "arkhe's own token",
    "au.mech.oidc": "authorization server",
    "op.restricted": "restricted",
    "op.no_self": "no self-registration",
}
