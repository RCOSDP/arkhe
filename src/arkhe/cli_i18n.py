"""コマンドの国際化。日本語と英語を既定で持つ。

管理画面（`api/i18n.py`）と同じく **gettext ではなく辞書**にしてある。理由も同じで、
`.mo` のコンパイルをビルド手順に増やさずに済み、翻訳の抜けが起動時に分かる。

## 画面と違うのは、言語を決める時点

画面は要求ごとに決められるが、**Typer は import の時点で help を組み立てる**
（デコレータが評価されるのがそこだから）。だから言語は環境から一度だけ決める。
`arkhe --lang en` のような実行時の切り替えは作れない——作っても、その値が読まれる
頃には help 文字列が確定している。

順序は **`ARKHE_LANG` → `LC_ALL` → `LC_MESSAGES` → `LANG` → 既定(ja)**。
POSIX の変数を見るのは、この種の道具に期待される作法だから。`C` と `POSIX` は
「言語の情報が無い」の意味なので飛ばす。既定を `ja` にしてあるのは管理画面と
揃えるため（`api/i18n.py` の `DEFAULT`）。
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
    "onboard.done": "組織 {name} を迎え、{naan}{shoulder} を委譲しました",
    "onboard.level": "約束の水準: {level}",
    "onboard.default_warning": "↑ 既定のままです。組織に確かめて "
                               "`arkhe manager commitment` で言い直してください。",
    # shoulder
    "shoulder.add.help": "名前空間を切り出す。`--reserve` で将来用に確保できる。",
    "shoulder.add.reserve": "押さえるだけで採番させない",
    "shoulder.add.done": "{naan}{shoulder} を切り出しました",
    "shoulder.status.help": "状態を変える。**retired からは戻せない**"
                            "（引退した名前空間の再開は NR 違反の芽）。",
    "shoulder.status.arg": "active / reserved / delegated / retired",
    "shoulder.status.minter": "delegated のときの採番の行き先",
    # manager
    "manager.list.help": "組織を並べる。**id は他のコマンドの入力になる。**",
    "manager.commitment.help": "組織の約束の水準を言い直す。\n\n"
                               "**これは `??` でそのまま公開される。** 組織が述べたことだけを"
                               "入れること——既定値を宣言として出すのは、何も出さないより悪い。\n\n"
                               "水準を**下げる**のも正当な操作である。守れない約束を掲げ続ける"
                               "より、実態に合わせて言い直すほうが誠実で、尋ねる意味も保たれる。",
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
    "onboard.done": "Onboarded {name} and delegated {naan}{shoulder}",
    "onboard.level": "Commitment level: {level}",
    "onboard.default_warning": "↑ Left at the default. Confirm it with the organisation "
                               "and restate it with `arkhe manager commitment`.",
    "shoulder.add.help": "Carve out a namespace. `--reserve` holds one for later.",
    "shoulder.add.reserve": "hold it without allowing minting",
    "shoulder.add.done": "Carved out {naan}{shoulder}",
    "shoulder.status.help": "Change the status. **There is no way back from retired** "
                            "(reopening a retired namespace is the seed of an NR violation).",
    "shoulder.status.arg": "active / reserved / delegated / retired",
    "shoulder.status.minter": "where minting goes when delegated",
    "manager.list.help": "List organisations. **The ids are input to other commands.**",
    "manager.commitment.help": "Restate an organisation's commitment level.\n\n"
                               "**This is published verbatim by `??`.** Put in only what the "
                               "organisation has stated — publishing a default as a declaration "
                               "is worse than publishing nothing.\n\n"
                               "**Lowering** it is a legitimate operation. Saying it plainly is "
                               "more honest than holding up a promise you cannot keep, and it "
                               "is what keeps asking worth doing.",
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
    "check.help": "Validate the configuration. **Fail here rather than at startup.**",
    "check.auth": "Mechanisms: {auth}",
    "check.role": "Role      : {role}",
    "check.db": "Database  : {url}",
    "check.read_db": "  read-only: {url}",
    "check.ok": "The configuration is valid",
}

CATALOGS = {"ja": JA, "en": EN}

#: 翻訳の抜けは**起動時に落とす**（`api/i18n.py` と同じ）。片方だけ足して気づかない、を防ぐ。
_missing = {lang: sorted(set(JA) - set(cat)) for lang, cat in CATALOGS.items()}
if any(_missing.values()):  # pragma: no cover - 開発時にしか起きない
    raise RuntimeError(f"翻訳の抜け: { {k: v for k, v in _missing.items() if v} }")

#: **import の時点で確定する。** Typer が help を組み立てるのがここだから。
LANG = pick()


def t(key: str, **kw: object) -> str:
    """訳を引く。`{}` を含む訳は `kw` で埋める。"""
    s = CATALOGS.get(LANG, JA).get(key, key)
    return s.format(**kw) if kw else s
