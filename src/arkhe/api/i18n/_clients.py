"""利用者と鍵の文言。主体の登録、資格情報、入り方と scope。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
    # 認可サーバから来たが登録の無い主体
    # **綴りが 1 文字違うだけで 401 になる。** その 1 文字を弾いた時点で
    # 持っているので、打ち直させずに登録へ渡す。
    "uk.title": "認可サーバから来た、登録の無い主体",
    "uk.lede": "<b>トークンは正しいのに、この台帳に登録がなかった主体です。</b>"
               "登録が無ければ通りません——認可サーバで認証できることと、"
               "この名前空間を触ってよいことは別だからです。"
               "<b>下の識別子は認可サーバが署名した値そのもの</b>なので、"
               "「登録する」から進めば打ち間違いは起こりません。",
    "uk.subject": "識別子",
    "uk.issuer": "認可サーバ",
    "uk.seen": "回数",
    "uk.last": "最後に来た",
    "uk.register": "登録する",
    "uk.hint": "1 回だけなら打ち間違い、何度も来るならその設定が生きています。",
    "uk.note": "<b>どの組織のものかは分かりません。</b>トークンにその情報が無く、"
               "推測もしないためです——この一覧が見えるのは NAAN 以上に届く"
               "主体だけにしてあります。",
    "uk.gone": "登録が済んだものは、この一覧から自動的に消えます。",
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
    # 入り方（どの経路で入ってくるか）
    "cl.search": "検索",
    "cl.search_ph": "識別子・ラベル（repo / jc2-web-api）",
    "au.search": "検索",
    "au.search_ph": "主体・操作・対象（ops / set_commitment / 99999）",
    "cl.entry": "入り方",
    "en.key": "鍵",
    "en.idp": "認可サーバに委ねる",
    "en.person": "外部ログイン",
    "en.none": "未設定",
    "en.idp_hint": "この構成では、認可サーバがこの識別子を保証するトークンを出せば入れます。"
                   "arkhe 側に鍵はありません。<b>その主体が認可サーバに実在するかどうかは、"
                   "arkhe からは分かりません</b>——確かめるには認可サーバ側を見てください。",
    "en.none_hint": "<b>まだ入れません。</b>鍵を発行するか、"
                    "<code>ARKHE_AUTH</code> に <code>oidc</code> を足して"
                    "認可サーバに任せてください。",
    # scope（できること）
    "sc.ark:mint": "採番する",
    "sc.ark:mint.d": "新しい ARK を発行する。<b>取り消せない。</b>",
    "sc.ark:update": "転送先を変える",
    "sc.ark:update.d": "既存の ARK の解決先や記述を書き換える。",
    "sc.ark:read": "読む",
    "sc.ark:read.d": "台帳を API から読む（解決そのものは誰でもできる）。",
    "sc.ark:tombstone": "失われたと宣言する",
    "sc.ark:tombstone.d": "対象が失われたことを述べる。<b>転送先の付け替えとは意味が違う</b>"
                          "ので、権限も分けてある。",
    "cu.f.scopes_hint": "<b>ここが上限です。</b>認可サーバのトークンに載っている scope との"
                        "積が、実際にできることになります——トークンで広がることはありません。",
}

EN: dict[str, str] = {
    "uk.title": "Subjects from the authorization server with no registration",
    "uk.lede": "<b>Their token was valid, but they are not in this ledger.</b> "
               "Without a registration they do not get in — authenticating with the "
               "authorization server and being allowed into this namespace are "
               "different questions. <b>The identifier below is exactly what the "
               "authorization server signed</b>, so registering from here cannot "
               "introduce a typo.",
    "uk.subject": "Identifier",
    "uk.issuer": "Authorization server",
    "uk.seen": "Times",
    "uk.last": "Last seen",
    "uk.register": "Register",
    "uk.hint": "Once is a typo; repeatedly means that configuration is live.",
    "uk.note": "<b>Which organisation it belongs to is unknown.</b> The token does not "
               "say and arkhe does not guess — which is why only NAAN-wide principals "
               "see this list.",
    "uk.gone": "Once registered, an entry disappears from this list by itself.",
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
    "cl.search": "Search",
    "cl.search_ph": "identifier or label (repo / jc2-web-api)",
    "au.search": "Search",
    "au.search_ph": "principal, action or target (ops / set_commitment / 99999)",
    "cl.entry": "Gets in by",
    "en.key": "a key",
    "en.idp": "delegated to the IdP",
    "en.person": "an external login",
    "en.none": "nothing yet",
    "en.idp_hint": "In this deployment it gets in if the authorization server issues a "
                   "token vouching for this identifier. There is no key on arkhe's side. "
                   "<b>Whether the subject actually exists there is not something arkhe "
                   "can see</b> — check at the authorization server.",
    "en.none_hint": "<b>It cannot get in yet.</b> Either issue a key, or add "
                    "<code>oidc</code> to <code>ARKHE_AUTH</code> and let the "
                    "authorization server vouch for it.",
    "sc.ark:mint": "Mint",
    "sc.ark:mint.d": "Issue new ARKs. <b>This cannot be taken back.</b>",
    "sc.ark:update": "Change where it points",
    "sc.ark:update.d": "Rewrite an existing ARK's target or description.",
    "sc.ark:read": "Read",
    "sc.ark:read.d": "Read the ledger through the API (resolution itself is open to all).",
    "sc.ark:tombstone": "Declare it lost",
    "sc.ark:tombstone.d": "State that the object is gone. <b>That means something other "
                          "than repointing</b>, so the permission is separate.",
    "cu.f.scopes_hint": "<b>This is the ceiling.</b> What it may actually do is the "
                        "intersection with the scopes in the token — a token cannot widen "
                        "it.",
}
