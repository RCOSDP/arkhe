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
    "nav.overview": "機関管理",
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
    "au.manager": "機関管理者",
    # 委譲の構造
    "ov.title": "機関管理",
    # **一般の読み手を想定する。** ここは台帳を初めて見る人が最初に開く画面なので、
    # **用語は捨てず、括弧で残す。** 平易な言い方を先に置いて用語を添えると、
    # 初めての人はそのまま読め、用語を知っている人は対応が取れる。
    # 用語を消すと、この画面と仕様書・CLI・API の語が食い違ってしまう。
    "ov.lede": "<b>ARK を発行できる機関と、それぞれに渡した名前空間（shoulder）の"
               "一覧です。</b>ARK には発行を束ねる中央組織がありません。"
               "番号（NAAN）を預かった側が機関に名前空間を渡し（委譲）、"
               "機関はその中で識別子を発行します。<b>発行した識別子をどこまで維持するかも、"
               "機関ごとに決めて公開します</b>——各行に出ている「約束の水準"
               "（commitment level）」がそれです。",
    "ov.naans": "番号（NAAN）",
    "ov.authoritative": "自組織で管理（権威あり）",
    "ov.delegated_to": "委譲先",
    "ov.no_manager": "機関に未割当",
    "ov.records": "件",
    "ov.quota": "上限",
    "ov.per_day": "／日",
    "ov.succeeded": "承継済",
    "ov.inactive": "停止",
    "ov.manage": "操作",
    "ov.add_naan": "NAAN を登録",
    "ov.onboard": "機関を追加",
    "ov.add_shoulder": "名前空間を追加",
    "ov.empty": "まだ NAAN が登録されていません。",
    # 採番
    "mint.title": "ARK を採番",
    "mint.lede": "通常の採番は機関のシステムが API から行います。この画面は"
                 "<b>手作業で 1 本必要なとき</b>——移行時の個別対応、物理オブジェクト、"
                 "動作確認——のためのものです。",
    "mint.done": "採番しました",
    "mint.irreversible": "この識別子は<b>取り消せません</b>。ARK は再割当てしないと"
                         "宣言しているため、不要になっても削除ではなく tombstone にします。",
    "mint.target": "解決先",
    "mint.form": "新規採番",
    "mint.shoulder": "採番する名前空間",
    "mint.shoulder_opt": "省略すると機関の既定",
    "mint.shoulder_default": "（機関の既定）",
    "mint.shoulder_required": "NAAN 単位以上の権限では<b>明示が必須</b>です"
                              "（誤って他機関の名前空間に打つのを防ぐため）。",
    "mint.url": "解決先 URL",
    "mint.url_opt": "空なら記述を返す",
    "mint.url_hint": "空のままでも採番できます。物理オブジェクトなど、"
                     "行き先が無い対象はこれが正しい形です。",
    "mint.title_field": "タイトル",
    "mint.type": "種別",
    "mint.submit": "採番する",
    "mint.flash": "を採番しました",
    # 主体
    "cl.title": "利用者と鍵",
    "cl.lede": "<b>ARK を発行できる利用者と、その鍵の一覧です。</b>"
               "利用者は 2 種類——機関のシステム（API キーで名乗る）と、"
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
                 "この NAAN の配下すべてにかかるので、機関単位では変えられません"
                 "（機関が自分について述べるのは<b>約束の水準</b>のほう）。",
    "naan.f.naan": "番号（NAAN）",
    "naan.f.naan_hint": "ARK Alliance から交付された番号。<b>後から変えられません。</b>",
    "naan.f.name": "機関名",
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
    "manager.new.title": "機関を追加",
    "manager.edit.title": "機関の設定",
    # **追加のときは、まず何が起きるかを述べる。** ここを開く人は、この操作が
    # 名前空間の受け渡しでもあることをまだ知らない。
    "manager.new.lede": "機関を追加すると、<b>同時に名前空間（shoulder）を 1 つ渡します</b>。"
                        "この 2 つは分けられません——名前空間を持たない機関は識別子を"
                        "発行できないので、置いても意味がないからです。"
                        "以後その機関は、渡した名前空間の中で ARK を発行します。",
    "manager.lede": "<b>約束の水準は機関自身の宣言</b>です。"
                    "だから機関管理者も自分の分は変えられます——"
                    "採番上限はそうではありません（配った側が課すもの）。",
    "manager.f.naan": "番号（NAAN）",
    "manager.f.name": "機関名",
    "manager.f.name_hint": "<b>内部専用です。</b>公開しません"
                           "（shoulder から機関が読めてはいけないため）。",
    "manager.f.shoulder": "委譲する名前空間",
    "manager.f.shoulder_hint": "<code>/x9</code> のように <code>/</code> で始めます。"
                               "<b>機関の登録と名前空間の委譲は必ず対で起きます。</b>",
    "manager.f.commitment": "約束の水準",
    "manager.f.commitment_hint": "<b><code>?</code> と <code>??</code> でそのまま公開されます。</b>"
                                 "機関が述べたことだけを入れてください——"
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
    "shoulder.f.naan": "番号（NAAN）",
    "shoulder.f.shoulder": "shoulder",
    "shoulder.f.shoulder_hint": "<code>/x9</code> のように <code>/</code> で始めます。",
    "shoulder.f.manager": "機関",
    "shoulder.f.reserve": "押さえるだけで採番させない",
    "shoulder.f.status": "状態",
    "shoulder.f.status_hint": "<b>retired からは戻せません</b>"
                              "（引退した名前空間の再開は NR 違反の芽）。",
    "shoulder.f.minter": "採番の行き先",
    "shoulder.f.minter_hint": "<b>delegated</b> のときだけ意味を持ちます。",
    "shoulder.f.redirect": "解決の委譲先",
    "shoulder.f.redirect_hint": "<code>${blade}</code> が名前に置き換わります。",
    "shoulder.f.note": "運用の記録",
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
    "nav.overview": "Institutions",
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
    "au.manager": "Institution administrator",
    "ov.title": "Institutions",
    "ov.lede": "<b>The institutions that can issue ARKs, and the namespace (shoulder) "
               "each one was given.</b> ARK has no central body issuing identifiers on "
               "everyone's behalf. Whoever holds the number (the NAAN) hands a namespace "
               "to an institution — this is called delegation — and the institution "
               "issues identifiers within it. <b>How far each institution undertakes to "
               "keep those identifiers working is also its own to state</b>: that is the "
               "commitment level shown on each row.",
    "ov.naans": "Numbers (NAAN)",
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
    "ov.onboard": "Add an institution",
    "ov.add_shoulder": "Add a namespace",
    "ov.empty": "No NAAN registered yet.",
    "mint.title": "Mint an ARK",
    "mint.lede": "Institutions normally mint through the API. This page is for the times "
                 "you need <b>one by hand</b> — a migration edge case, a physical object, "
                 "a smoke test.",
    "mint.done": "Minted",
    "mint.irreversible": "This identifier <b>cannot be taken back</b>. ARK declares that "
                         "names are never re-assigned, so an unwanted one is tombstoned, "
                         "not deleted.",
    "mint.target": "Resolves to",
    "mint.form": "New ARK",
    "mint.shoulder": "Namespace to mint in",
    "mint.shoulder_opt": "omit to use the institution's default",
    "mint.shoulder_default": "(the institution's default)",
    "mint.shoulder_required": "At NAAN level and above the shoulder <b>must be explicit</b>, "
                              "so you cannot mint into another institution's namespace by mistake.",
    "mint.url": "Target URL",
    "mint.url_opt": "leave empty to return a description",
    "mint.url_hint": "An empty target is valid. For a physical object, with nowhere to "
                     "redirect to, this is the correct shape.",
    "mint.title_field": "Title",
    "mint.type": "Type",
    "mint.submit": "Mint",
    "mint.flash": "minted",
    "cl.title": "Users & keys",
    "cl.lede": "<b>Who may issue ARKs, and with which key.</b> There are two kinds: "
               "an institution's systems, which identify themselves with an API key, and "
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
                 "out.</b> It covers everything under this NAAN, so an institution "
                 "cannot change it — what an institution states about itself is its "
                 "<b>commitment level</b>.",
    "naan.f.naan": "Number (NAAN)",
    "naan.f.naan_hint": "The number issued by the ARK Alliance. <b>It cannot be changed "
                        "later.</b>",
    "naan.f.name": "Institution",
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
    "manager.new.title": "Add an institution",
    "manager.edit.title": "Institution settings",
    "manager.new.lede": "Adding an institution <b>hands it one namespace (shoulder) at "
                        "the same time</b>. The two cannot be separated: an institution "
                        "with no namespace cannot issue identifiers, so there would be no "
                        "point putting one here. From then on it issues ARKs within that "
                        "namespace.",
    "manager.lede": "<b>The commitment level is the institution's own declaration</b>, "
                    "which is why an institutional administrator may change their own. "
                    "The minting limit is not — that is imposed by the side handing the "
                    "namespace out.",
    "manager.f.naan": "Number (NAAN)",
    "manager.f.name": "Institution",
    "manager.f.name_hint": "<b>Internal only.</b> Never published — a shoulder must not "
                           "reveal which institution holds it.",
    "manager.f.shoulder": "Namespace to delegate",
    "manager.f.shoulder_hint": "Begins with <code>/</code>, as in <code>/x9</code>. "
                               "<b>Registering the institution and delegating the "
                               "namespace always happen together.</b>",
    "manager.f.commitment": "Commitment level",
    "manager.f.commitment_hint": "<b>Published verbatim by <code>?</code> and "
                                 "<code>??</code>.</b> Put in only what the institution "
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
    "shoulder.f.naan": "Number (NAAN)",
    "shoulder.f.shoulder": "Shoulder",
    "shoulder.f.shoulder_hint": "Begins with <code>/</code>, as in <code>/x9</code>.",
    "shoulder.f.manager": "Institution",
    "shoulder.f.reserve": "Hold it without allowing minting",
    "shoulder.f.status": "Status",
    "shoulder.f.status_hint": "<b>There is no way back from retired</b> (reopening a "
                              "retired namespace is the seed of an NR violation).",
    "shoulder.f.minter": "Where minting goes",
    "shoulder.f.minter_hint": "Meaningful only when <b>delegated</b>.",
    "shoulder.f.redirect": "Delegate resolution to",
    "shoulder.f.redirect_hint": "<code>${blade}</code> is replaced by the name.",
    "shoulder.f.note": "Operational note",
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
