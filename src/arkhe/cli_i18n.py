"""コマンドの国際化。日本語と英語を既定で持つ。

管理画面（`api/i18n/`）と同じく **gettext ではなく辞書**にしてある。理由も同じで、
`.mo` のコンパイルをビルド手順に増やさずに済み、翻訳の抜けが起動時に分かる。

## 画面と違うのは、言語を決める時点

画面は要求ごとに決められるが、**Typer は import の時点で help を組み立てる**
（デコレータが評価されるのがそこだから）。だから言語は環境から一度だけ決める。
`arkhe --lang en` のような実行時の切り替えは作れない——作っても、その値が読まれる
頃には help 文字列が確定している。

順序は **`ARKHE_LANG` → `LC_ALL` → `LC_MESSAGES` → `LANG` → 既定(ja)**。
POSIX の変数を見るのは、この種の道具に期待される作法だから。`C` と `POSIX` は
「言語の情報が無い」の意味なので飛ばす。既定を `ja` にしてあるのは管理画面と
揃えるため（`api/i18n/` の `DEFAULT`）。
"""

from __future__ import annotations

import os

DEFAULT = "ja"
LANGS = ("ja", "en")
ENV = "ARKHE_LANG"


def pick(environ: dict[str, str] | None = None) -> str:
    """環境から言語を決める。**引数を取るのはテストのため。**"""
    env = os.environ if environ is None else environ
    explicit = env.get(ENV, "").strip().lower()
    if explicit in LANGS:
        return explicit
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        raw = env.get(var, "").strip()
        if not raw or raw.upper() in {"C", "POSIX", "C.UTF-8"}:
            # 「言語の情報が無い」であって「英語」ではない。次の変数を見る。
            continue
        tag = raw.split(".")[0].split("_")[0].lower()
        if tag in LANGS:
            return tag
    return DEFAULT


JA: dict[str, str] = {
    # 骨格
    "app.help": "arkhe — ARK 識別子基盤の運用コマンド",
    "naan.help": "NAAN",
    "shoulder.help": "shoulder",
    "manager.help": "組織。迎え入れは onboard、以後の手当てはここ",
    "client.help": "主体と資格情報",
    # 共通の語
    "opt.manager_id": "組織 id",
    "opt.note": "運用の記録",
    "opt.only_naan": "この NAAN のものだけ",
    "word.unassigned": "(組織未割当)",
    "word.no_default": "(既定なし)",
    "word.person": "人",
    "word.machine": "機械",
    "word.authoritative": "権威あり",
    "word.delegated_to": "委譲 → {target}",
    # naan add
    "naan.list.help": "NAAN を並べる。**権威を持つのか、どこへ委譲しているのか**が出る。",
    "naan.add.help": "NAAN を登録する。",
    "naan.add.policy": "NAA ポリシー（`NP | NR, OP, CC | 2026 | <URL>`）",
    "naan.add.authoritative": "この NAAN の権威を持つか",
    "naan.add.redirect": "権威を持たない場合の委譲先",
    "naan.add.done": "NAAN {naan} ({name}) を登録しました",
    # onboard
    "onboard.help": "組織を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。**\n\n"
                    "`--commitment` は迎え入れる時点で組織に確かめること。**既定のまま置くと、"
                    "組織が述べていない水準を組織の名前で `??` が公開する。**",
    "onboard.name": "組織名（内部専用。公開しない）",
    "onboard.shoulder": "委譲する名前空間（例 /x9）",
    "onboard.quota": "1 日あたりの採番上限。省略で無制限",
    "onboard.commitment": "約束の水準。`arkhe manager commitment --list` で一覧",
    "onboard.done": "組織 {name} を迎え、{naan}{shoulder} を委譲しました（shoulder id {id}）",
    "onboard.level": "約束の水準: {level}",
    "onboard.default_warning": "↑ 既定のままです。組織に確かめて "
                               "`arkhe manager commitment` で言い直してください。",
    # shoulder
    "shoulder.list.help": "shoulder を並べる。**id は他のコマンドの入力になる。**",
    "shoulder.add.help": "名前空間を切り出す。`--reserve` で将来用に確保できる。",
    "shoulder.add.reserve": "押さえるだけで採番させない",
    "shoulder.add.done": "{naan}{shoulder} を切り出しました（id {id}）",
    "shoulder.status.help": "状態を変える。**retired からは戻せない**"
                            "（引退した名前空間の再開は NR 違反の芽）。",
    "shoulder.status.arg": "active / reserved / delegated / retired",
    "shoulder.status.minter": "delegated のときの採番の行き先"
                              "（機械が叩ける口。外から届かないなら空のまま）",
    "shoulder.status.about": "外から到達できない委譲のときの、人向けの案内ページ",
    # manager
    "manager.list.help": "組織を並べる。**id は他のコマンドの入力になる。**",
    "manager.commitment.help": "組織の約束の水準を言い直す。\n\n"
                               "**これは `??` でそのまま公開される。** 組織が述べたことだけを"
                               "入れること——既定値を宣言として出すのは、何も出さないより悪い。\n\n"
                               "水準を**下げる**のも正当な操作である。守れない約束を掲げ続ける"
                               "より、実態に合わせて言い直すほうが誠実で、尋ねる意味も保たれる。",
    "manager.policy.help": "組織に何を任せ、何を制限するかを決める。"
                           "**組織自身では変えられない**（課された制限を課された側が"
                           "外せては意味がない）。省略した項目は触らない。",
    "manager.policy.auth": "許す入り方。空白区切り（apikey / oauth2 / oidc）。空で制限なし",
    "manager.policy.self_register": "組織の管理者が自分で利用者を登録してよいか",
    "manager.policy.max_scopes": "与えられる scope の上限。空白区切り。空で制限なし",
    "manager.policy.auth_now": "入り方  : {v}",
    "manager.policy.self_now": "自己登録: {v}",
    "manager.policy.scopes_now": "scope 上限: {v}",
    "word.unrestricted": "制限なし",
    "word.yes": "許す",
    "word.no": "許さない",
    "manager.commitment.level": "約束の水準",
    "manager.commitment.list": "選べる水準を並べて終わる",
    "manager.commitment.need_args": "組織 id と水準が要ります（--list で一覧）",
    # client add
    "client.add.help": "主体を登録する。\n\n"
                       "既定は機械（API キーで名乗る）。**管理画面に人としてログインさせるなら"
                       "`--person`** を付け、client_id には認可サーバが返す識別子"
                       "（メールや eppn）を入れる。",
    "client.add.shoulder": "この shoulder に固定する",
    "client.add.scopes": "空白区切り",
    "client.add.person": "人の主体として登録する（外部ログイン専用。資格情報を持てない）",
    "client.add.authority": "manager / naan / system",
    "client.add.done": "{kind}の主体 {client_id} を登録しました（scope: {scopes}）",
    "client.add.person_note": "外部ログイン専用です。資格情報は発行しません。",
    # client key
    "client.key.help": "資格情報を発行する。**平文はこの一度しか表示されない。**",
    "client.key.kind": "api_key / client_secret",
    "client.not_found": "主体 {client_id} が見つかりません",
    "client.key.once": "↑ この値はもう二度と表示されません。保存しているのはハッシュだけです。",
    # breakglass
    "client.breakglass.help": "NAAN 配下すべてに届く一時的な主体を作る。**期限つき。**\n\n"
                              "障害対応のための逃げ道。恒久的な万能鍵にしないよう期限を必須に"
                              "してある。この主体の操作は**全件が監査に残る**。",
    "client.breakglass.client_id": "登録する client_id",
    "client.breakglass.days": "有効期限（日）",
    "client.breakglass.expires": "↑ {days} 日で失効します。操作は全件監査に残ります。",
    # passwd / revoke
    "client.passwd.help": "人の主体にパスワードを設定する（管理画面へのローカルログイン用）。",
    "client.passwd.password": "12 文字以上。入力は画面に出ない",
    "client.passwd.done": "{client_id} のパスワードを設定しました",
    "client.revoke.help": "失効させる。**行は消さない**（いつ失効したかを残す）。",
    "client.disable.help": "主体を止める。**認可サーバに寄せた構成ではこれが唯一の止め方**"
                           "——資格情報を arkhe が持たないので revoke は効かない。",
    "client.enable.help": "止めた主体を戻す。**去った組織の主体は戻せない。**",
    "client.disabled": "{client_id} を止めました",
    "client.enabled": "{client_id} を戻しました",
    "client.revoke.done": "資格情報 {id} を失効させました",
    # succeed / depart
    "succeed.help": "統廃合。**識別子は壊さない**（名前空間ごと承継先に移す）。",
    "succeed.predecessor": "承継元の組織 id",
    "succeed.successor": "承継先の組織 id",
    "succeed.retire": "移した shoulder の新規採番を止める",
    "succeed.done": "{successor} が承継しました: {moved}",
    "succeed.revoked": "停止した資格情報: {revoked}",
    "depart.help": "組織の離脱。**新規採番は止め、解決は続ける。**",
    "depart.manager": "離脱する組織 id",
    "depart.resolver": "転送先を組織のリゾルバに一括で向け直す。"
                       "例 'https://repo.example.ac.jp/ark/${blade}'",
    "depart.keep_update": "更新権限だけの主体を残す（ラベル）",
    "depart.shoulders": "停止した shoulder: {shoulders}",
    "depart.rewritten": "転送先を書き換えた ARK: {count} 件",
    "depart.update_note": "↑ 更新権限だけの鍵。この一度しか表示されません。",
    # check
    "shoulder.redirect.help": "shoulder 単位で解決を委譲する（N2T のテンプレート）。",
    "shoulder.redirect.arg": "行き先。`$id` / `${blade}` と先頭の `303 ` が使える",
    "shoulder.redirect.done": "{naan}{shoulder} の解決を {redirect} へ委譲した",
    "shoulder.redirect.cleared": "{naan}{shoulder} の解決の委譲を外した",
    "hold.help": "転送の一時停止",
    "hold.add.help": "転送を一時的に止める。**解決は止めない**（記述は返り続ける）。",
    "hold.add.kind": "止める層（ark / shoulder / naan）。**狭いほうが優先する**",
    "hold.add.key": "対象（ARK・shoulder の id・NAAN）",
    "hold.add.days": "何日で自動的に戻すか。**期限は必須**——一時的を記憶に頼らない",
    "hold.add.reason": "止めている理由。**公開の口に出る**ので機微を書かない",
    "hold.add.done": "{kind} {target} の転送を止めた（{until} まで）",
    "hold.release.help": "保留を期限より前に外す。",
    "hold.release.done": "{kind} {target} の保留を外した",
    "hold.list.help": "今かかっている保留を並べる。**見えないと恒久化する。**",
    "hold.list.empty": "保留は無い",
    "ark.help": "発行した ARK",
    "ark.list.help": "発行した ARK を並べる。**件数は増える一方なので既定で打ち切る。**",
    "ark.list.org": "この組織のものだけ（id は manager list で分かる）",
    "ark.list.search": "ARK・行き先・題名を部分一致で引く",
    "ark.list.limit": "取り出す件数の上限",
    "ark.list.offset": "先頭から飛ばす件数",
    "ark.list.more": "ここまでで打ち切った。続きは --offset {next} から",
    "ark.list.empty": "該当なし",
    "ark.list.state": "public / reserved で絞る（公開済みだけ・公開前だけ）",
    "ark.mark.reserved": "公開前",
    "ark.publish.help": "**グローバルに公開する。** 公開すると解決を始め、"
                        "以後は削除できない（tombstone にするしかない）。\n\n"
                        "二度実行しても落ちない——同じ結果になるだけ。",
    "ark.publish.done": "{ark} を公開しました",
    "ark.publish.already": "{ark} は既に公開済み",
    "ark.unpublish.help": "**公開を取り下げる。** 行は残るので `ark publish` で出し直せる"
                          "——**戻せるのはこちらだけ**で、削除は戻せない。\n\n"
                          "取り下げているあいだ、その ARK は解決しない。**名前が別のもの"
                          "を指すことは無い**（残った参照は 404 になるだけ）。",
    "ark.unpublish.reason": "取り下げる理由。**必須**——その間に誰かが引用しているかも"
                            "しれず、こちらからは知りようがない",
    "ark.unpublish.yes": "訊かずに取り下げる",
    "ark.unpublish.confirm": "{ark} の公開を取り下げます。**外に出た名前が解決しなく"
                             "なります。** よろしいですか",
    "ark.unpublish.aborted": "取り下げませんでした",
    "ark.unpublish.done": "{ark} の公開を取り下げました（`ark publish` で出し直せます）",
    "ark.delete.help": "**公開していない ARK を消す。** 公開中のものには効かない"
                       "——先に `ark unpublish` を通す。\n\n"
                       "消えるのは台帳の行だけで、**名前は二度と採られない**"
                       "——予約した文字列は既に誰かの手にあるかもしれないため。"
                       "**一度でも公開した名前なら、理由を要求し、一度訊く。**",
    "ark.delete.reason": "取り下げる理由。消えた行について残る唯一の説明になる"
                         "（**一度でも公開した名前では必須**）",
    "ark.delete.yes": "訊かずに消す",
    "ark.delete.confirm": "{ark} は一度公開されています。**消すと戻せません。**"
                          "よろしいですか",
    "ark.delete.aborted": "消しませんでした",
    "ark.delete.done": "{ark} を取り下げました（この名前は二度と採られません）",
    "ark.purge.help": "**公開した ARK を破棄する。** これは約束を破る操作である"
                      "——削除命令や、公開してはならなかったものへの逃げ道として"
                      "だけ使う。\n\n"
                      "理由は必須で、名前は二度と採られない。監査に必ず残る。",
    "ark.purge.reason": "破棄する理由。**消えた識別子について残る唯一の説明**",
    "ark.purge.yes": "確認を省く（スクリプト用）",
    "ark.purge.confirm": "公開した ARK {ark} を破棄する。解決は止まり、戻せない。続ける？",
    "ark.purge.aborted": "やめました",
    "ark.purge.done": "{ark} を破棄しました（この名前は二度と採られません）",
    "stat.help": "**台帳を数える。** 届く範囲の内側だけ——数えるのは行数に比例して"
                 "重い（30 万件で約 110 ms）。**繰り返し叩く用途には向かない。**",
    "stat.json": "JSON で出す（機械で読むとき）",
    "stat.by_shoulder": "shoulder ごとの内訳も出す",
    "stat.head": "台帳の統計（範囲: {scope}）",
    "stat.scope.system": "全 NAAN",
    "stat.scope.naan": "自 NAAN",
    "stat.scope.organisation": "自組織",
    "stat.naans": "NAAN",
    "stat.arks": "ARK",
    "stat.arks_note": "公開 {public} / 公開前 {reserved}",
    "stat.withdrawn": "取り下げた名前",
    "stat.withdrawn_note": "うち公開後に消したもの {n}",
    "stat.shoulders": "shoulder",
    "stat.orgs": "組織",
    "stat.clients": "主体",
    "stat.active_note": "有効 {n}",
    "stat.holds": "保留（今かかっているもの）",
    "stat.minted": "採番",
    "stat.first": "最初の採番",
    "stat.last": "最後の採番",
    "stat.per_shoulder": "shoulder ごと:",
    "check.help": "設定を検証する。**起動前に落としたいものをここで落とす。**",
    "check.auth": "認証機構: {auth}",
    "check.role": "役割    : {role}",
    "check.db": "DB      : {url}",
    "check.read_db": "  読取専用: {url}",
    "check.ok": "設定は妥当です",
}

EN: dict[str, str] = {
    "app.help": "arkhe — operational commands for ARK identifier infrastructure",
    "naan.help": "NAANs",
    "shoulder.help": "Shoulders",
    "manager.help": "Organisations. Onboarding is `onboard`; everything after is here",
    "client.help": "Principals and credentials",
    "opt.manager_id": "organisation id",
    "opt.note": "an operational note",
    "opt.only_naan": "only those under this NAAN",
    "word.unassigned": "(no organisation)",
    "word.no_default": "(no default)",
    "word.person": "person",
    "word.machine": "machine",
    "word.authoritative": "authoritative",
    "word.delegated_to": "delegated → {target}",
    "naan.list.help": "List NAANs. Shows **which it holds authority for, and where "
                      "the rest are delegated**.",
    "naan.add.help": "Register a NAAN.",
    "naan.add.policy": "NAA policy (`NP | NR, OP, CC | 2026 | <URL>`)",
    "naan.add.authoritative": "whether you hold authority over this NAAN",
    "naan.add.redirect": "where to delegate to, if you do not",
    "naan.add.done": "Registered NAAN {naan} ({name})",
    "onboard.help": "Onboard an organisation and delegate one namespace to it. "
                    "**The two always happen together.**\n\n"
                    "Confirm `--commitment` with the organisation as you onboard it. "
                    "**Left at the default, `??` publishes, in the organisation's name, "
                    "a level the organisation never stated.**",
    "onboard.name": "organisation name (internal only; never published)",
    "onboard.shoulder": "the namespace to delegate (e.g. /x9)",
    "onboard.quota": "minting limit per day; unlimited if omitted",
    "onboard.commitment": "commitment level; `arkhe manager commitment --list` to see them",
    "onboard.done": "Onboarded {name} and delegated {naan}{shoulder} (shoulder id {id})",
    "onboard.level": "Commitment level: {level}",
    "onboard.default_warning": "↑ Left at the default. Confirm it with the organisation "
                               "and restate it with `arkhe manager commitment`.",
    "shoulder.list.help": "List shoulders. **The id is the input to the other commands.**",
    "shoulder.add.help": "Carve out a namespace. `--reserve` holds one for later.",
    "shoulder.add.reserve": "hold it without allowing minting",
    "shoulder.add.done": "Carved out {naan}{shoulder} (id {id})",
    "shoulder.status.help": "Change the status. **There is no way back from retired** "
                            "(reopening a retired namespace is the seed of an NR violation).",
    "shoulder.status.arg": "active / reserved / delegated / retired",
    "shoulder.status.minter": "where minting goes when delegated (an endpoint a "
                              "client can call; leave empty if unreachable)",
    "shoulder.status.about": "a page for people, when the delegate cannot be reached from outside",
    "manager.list.help": "List organisations. **The ids are input to other commands.**",
    "manager.commitment.help": "Restate an organisation's commitment level.\n\n"
                               "**This is published verbatim by `??`.** Put in only what the "
                               "organisation has stated — publishing a default as a declaration "
                               "is worse than publishing nothing.\n\n"
                               "**Lowering** it is a legitimate operation. Saying it plainly is "
                               "more honest than holding up a promise you cannot keep, and it "
                               "is what keeps asking worth doing.",
    "manager.policy.help": "Decide what an organisation is trusted with and what it is "
                           "restricted to. **The organisation cannot change this** — a "
                           "limit the limited party can lift is not a limit. Omitted "
                           "options are left alone.",
    "manager.policy.auth": "Permitted ways in, space separated (apikey / oauth2 / oidc); "
                           "empty for no restriction",
    "manager.policy.self_register": "whether its administrator may register users",
    "manager.policy.max_scopes": "ceiling on the scopes its users may hold, space "
                                 "separated; empty for no ceiling",
    "manager.policy.auth_now": "Ways in    : {v}",
    "manager.policy.self_now": "Self-register: {v}",
    "manager.policy.scopes_now": "Scope ceiling: {v}",
    "word.unrestricted": "unrestricted",
    "word.yes": "yes",
    "word.no": "no",
    "manager.commitment.level": "the commitment level",
    "manager.commitment.list": "list the available levels and stop",
    "manager.commitment.need_args": "an organisation id and a level are required "
                                    "(--list to see them)",
    "client.add.help": "Register a principal.\n\n"
                       "The default is a machine, which identifies itself with an API key. "
                       "**To let a person sign in to the admin interface, pass `--person`** "
                       "and put in client_id whatever the authorization server returns "
                       "(an email address, an eppn).",
    "client.add.shoulder": "pin it to this shoulder",
    "client.add.scopes": "space separated",
    "client.add.person": "register as a person (external login only; holds no credentials)",
    "client.add.authority": "manager / naan / system",
    "client.add.done": "Registered {kind} principal {client_id} (scope: {scopes})",
    "client.add.person_note": "External login only. No credential will be issued.",
    "client.key.help": "Issue a credential. **The plaintext is shown this once and never again.**",
    "client.key.kind": "api_key / client_secret",
    "client.not_found": "No principal {client_id}",
    "client.key.once": "↑ This value will never be shown again. Only a hash is stored.",
    "client.breakglass.help": "Create a temporary principal reaching everything under a NAAN. "
                              "**Time-boxed.**\n\n"
                              "A way out during an incident. The expiry is mandatory so that it "
                              "cannot become a permanent master key. **Everything this principal "
                              "does is recorded in the audit log.**",
    "client.breakglass.client_id": "the client_id to register",
    "client.breakglass.days": "lifetime in days",
    "client.breakglass.expires": "↑ Expires in {days} days. Every action is recorded "
                                 "in the audit log.",
    "client.passwd.help": "Set a password on a person (for local sign-in to the admin interface).",
    "client.passwd.password": "12 characters or more; input is not echoed",
    "client.passwd.done": "Set the password for {client_id}",
    "client.revoke.help": "Revoke. **The row is not deleted** — when it stopped remains.",
    "client.disable.help": "Stop a principal. **Where authentication is delegated this is "
                           "the only way to stop one** — arkhe holds no credential, so "
                           "revoke has nothing to act on.",
    "client.enable.help": "Restore a stopped principal. **One belonging to an "
                          "organisation that has left cannot be restored.**",
    "client.disabled": "Stopped {client_id}",
    "client.enabled": "Restored {client_id}",
    "client.revoke.done": "Revoked credential {id}",
    "succeed.help": "A merger. **Identifiers are not broken** — the namespace moves with them.",
    "succeed.predecessor": "id of the organisation being succeeded",
    "succeed.successor": "id of the organisation succeeding it",
    "succeed.retire": "stop new minting in the namespaces moved",
    "succeed.done": "{successor} has succeeded: {moved}",
    "succeed.revoked": "Credentials stopped: {revoked}",
    "depart.help": "An organisation leaves. **Minting stops; resolution continues.**",
    "depart.manager": "id of the departing organisation",
    "depart.resolver": "repoint all targets at the organisation's own resolver, "
                       "e.g. 'https://repo.example.ac.uk/ark/${blade}'",
    "depart.keep_update": "keep a principal with update rights only (by label)",
    "depart.shoulders": "Shoulders stopped: {shoulders}",
    "depart.rewritten": "ARKs whose target was rewritten: {count}",
    "depart.update_note": "↑ A key with update rights only. Shown this once.",
    "shoulder.redirect.help": "Delegate resolution for a shoulder (an N2T template).",
    "shoulder.redirect.arg": "where to send it: `$id` / `${blade}`, and a leading `303 `",
    "shoulder.redirect.done": "resolution for {naan}{shoulder} now goes to {redirect}",
    "shoulder.redirect.cleared": "resolution for {naan}{shoulder} is no longer delegated",
    "hold.help": "Suspended redirection",
    "hold.add.help": "Suspend redirection. **Resolution is not stopped** — "
    "the description still answers.",
    "hold.add.kind": "what to hold: ark / shoulder / naan. **The narrowest one wins**",
    "hold.add.key": "the target: an ARK, a shoulder id, or a NAAN",
    "hold.add.days": "days until it lifts itself. **An expiry is required** — memory is not one",
    "hold.add.reason": "why it is held. **This is published**, so keep it non-sensitive",
    "hold.add.done": "held {kind} {target} until {until}",
    "hold.release.help": "Lift a hold before its expiry.",
    "hold.release.done": "released the hold on {kind} {target}",
    "hold.list.help": "List the holds in force. **What is not visible becomes permanent.**",
    "hold.list.empty": "no holds in force",
    "ark.help": "Minted ARKs",
    "ark.list.help": "List minted ARKs. **The count only grows, so this stops by default.**",
    "ark.list.org": "only this organisation (see `manager list` for the id)",
    "ark.list.search": "substring match on the ARK, its target and its title",
    "ark.list.limit": "how many rows at most",
    "ark.list.offset": "how many rows to skip",
    "ark.list.more": "stopped here; continue from --offset {next}",
    "ark.list.empty": "nothing matched",
    "ark.list.state": "only `public` or only `reserved` ones",
    "ark.mark.reserved": "reserved",
    "ark.publish.help": "**Publish it globally.** From then on it resolves, and it can no "
                        "longer be deleted — only tombstoned.\n\n"
                        "Running it twice is not an error; the result is the same.",
    "ark.publish.done": "published {ark}",
    "ark.publish.already": "{ark} was already public",
    "ark.unpublish.help": "**Withdraw an ARK from publication.** The row stays, so "
                          "`ark publish` puts it back — **this is the half that comes "
                          "back**; deleting does not.\n\n"
                          "While it is withdrawn the ARK does not resolve. **The name "
                          "never comes to mean something else**: a stale reference gets "
                          "404, never a different object.",
    "ark.unpublish.reason": "why it is withdrawn. **Required** — someone may be citing it "
                            "already, and there is no way to know that from here",
    "ark.unpublish.yes": "withdraw without asking",
    "ark.unpublish.confirm": "Withdraw {ark} from publication. **A name that went out "
                             "into the world will stop resolving.** Continue",
    "ark.unpublish.aborted": "left it published",
    "ark.unpublish.done": "withdrew {ark} from publication (`ark publish` puts it back)",
    "ark.delete.help": "**Delete an ARK that is not currently published.** It does nothing "
                       "to a published one — unpublish it first.\n\n"
                       "Only the row goes: **the name is never assigned again**, because a "
                       "reserved identifier may already be in someone's hands.",
    "ark.delete.reason": "why it is withdrawn; the only account left of a row that is gone "
                        "(**required if it has ever been published**)",
    "ark.delete.yes": "delete without asking",
    "ark.delete.confirm": "{ark} has been published. **Deleting it does not come back.** "
                          "Continue",
    "ark.delete.aborted": "left it in the ledger",
    "ark.delete.done": "withdrew {ark} (that name is never assigned again)",
    "ark.purge.help": "**Purge a published ARK.** This breaks the promise the service "
                      "makes — use it only as a way out for a removal order, or for "
                      "what should never have been published.\n\n"
                      "A reason is required, the name is never assigned again, and the "
                      "audit log always keeps it.",
    "ark.purge.reason": "why it is purged. **The only account left of the identifier**",
    "ark.purge.yes": "skip the confirmation (for scripts)",
    "ark.purge.confirm": "Purge the published ARK {ark}? Resolution stops, and there is "
                         "no way back. Continue?",
    "ark.purge.aborted": "left alone",
    "ark.purge.done": "purged {ark} (that name is never assigned again)",
    "stat.help": "**Count the ledger.** Only within your reach — counting costs time "
                 "proportional to the number of rows (about 110 ms over 300,000). "
                 "**Not made for polling.**",
    "stat.json": "print JSON (for machines)",
    "stat.by_shoulder": "also break it down per shoulder",
    "stat.head": "Ledger statistics (reach: {scope})",
    "stat.scope.system": "every NAAN",
    "stat.scope.naan": "its NAAN",
    "stat.scope.organisation": "its organisation",
    "stat.naans": "NAANs",
    "stat.arks": "ARKs",
    "stat.arks_note": "public {public} / reserved {reserved}",
    "stat.withdrawn": "withdrawn names",
    "stat.withdrawn_note": "of which removed after publication: {n}",
    "stat.shoulders": "shoulders",
    "stat.orgs": "organisations",
    "stat.clients": "clients",
    "stat.active_note": "active {n}",
    "stat.holds": "holds in force",
    "stat.minted": "minted",
    "stat.first": "first mint",
    "stat.last": "last mint",
    "stat.per_shoulder": "Per shoulder:",
    "check.help": "Validate the configuration. **Fail here rather than at startup.**",
    "check.auth": "Mechanisms: {auth}",
    "check.role": "Role      : {role}",
    "check.db": "Database  : {url}",
    "check.read_db": "  read-only: {url}",
    "check.ok": "The configuration is valid",
}

CATALOGS = {"ja": JA, "en": EN}

#: 翻訳の抜けは**起動時に落とす**（`api/i18n/` と同じ）。片方だけ足して気づかない、を防ぐ。
_missing = {lang: sorted(set(JA) - set(cat)) for lang, cat in CATALOGS.items()}
if any(_missing.values()):  # pragma: no cover - 開発時にしか起きない
    raise RuntimeError(f"翻訳の抜け: { {k: v for k, v in _missing.items() if v} }")

#: **import の時点で確定する。** Typer が help を組み立てるのがここだから。
LANG = pick()


def t(key: str, **kw: object) -> str:
    """訳を引く。`{}` を含む訳は `kw` で埋める。"""
    s = CATALOGS.get(LANG, JA).get(key, key)
    return s.format(**kw) if kw else s
