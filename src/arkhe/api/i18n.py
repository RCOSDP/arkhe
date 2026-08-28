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
    "nav.overview": "委譲の構造",
    "nav.clients": "主体と資格情報",
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
    "ov.title": "委譲の構造",
    "ov.lede": "ARK は中央の権威が保証する体系ではなく、"
               "<b>名前空間を委譲し、各機関が自分の約束を自己申告する</b>体系です。"
               "ここに見えているのが、その委譲の実体です。",
    "ov.tree": "NAAN → 機関 → shoulder",
    "ov.naans": "NAAN",
    "ov.authoritative": "権威あり",
    "ov.delegated_to": "委譲先",
    "ov.no_manager": "機関未割当",
    "ov.records": "件",
    "ov.quota": "上限",
    "ov.per_day": "／日",
    "ov.succeeded": "承継済",
    "ov.inactive": "停止",
    "ov.manage": "操作",
    "ov.add_naan": "NAAN を登録",
    "ov.onboard": "機関をオンボード",
    "ov.add_shoulder": "shoulder を切り出す",
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
    "mint.shoulder": "shoulder",
    "mint.shoulder_opt": "省略すると機関の既定",
    "mint.shoulder_default": "（既定の shoulder）",
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
    "cl.title": "主体と資格情報",
    "cl.lede": "採番する主体と、その鍵。<b>到達範囲は主体の登録属性</b>で、"
               "リクエストやトークン要求では広げられません。",
    "cl.issued": "資格情報を発行しました",
    "cl.issued_warn": "<b>この値はもう二度と表示されません。</b>いま控えてください。"
                      "保存しているのはハッシュだけです。",
    "cl.principals": "主体",
    "cl.reach": "到達範囲",
    "cl.scope": "scope",
    "cl.creds": "資格情報",
    "cl.live": "有効",
    "cl.dead": "失効",
    "cl.open": "開く",
    "cl.add": "主体を登録",
    "cl.disabled": "無効",
    "cl.all_naans": "全 NAAN",
    "cl.empty": "主体がまだ登録されていません。",
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
}

EN: dict[str, str] = {
    "app.subtitle": "ARK identifier infrastructure",
    "nav.ledger": "Ledger",
    "nav.actions": "Actions",
    "nav.overview": "Delegation",
    "nav.clients": "Principals & credentials",
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
    "ov.title": "Delegation",
    "ov.lede": "ARK is not a scheme where a central authority guarantees persistence. "
               "It <b>delegates namespaces and lets each institution declare its own "
               "commitment</b>. What you see here is that delegation, made concrete.",
    "ov.tree": "NAAN → institution → shoulder",
    "ov.naans": "NAANs",
    "ov.authoritative": "authoritative",
    "ov.delegated_to": "delegated to",
    "ov.no_manager": "no institution",
    "ov.records": "records",
    "ov.quota": "cap",
    "ov.per_day": "/day",
    "ov.succeeded": "succeeded",
    "ov.inactive": "inactive",
    "ov.manage": "Manage",
    "ov.add_naan": "Register a NAAN",
    "ov.onboard": "Onboard an institution",
    "ov.add_shoulder": "Carve out a shoulder",
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
    "mint.shoulder": "Shoulder",
    "mint.shoulder_opt": "omit to use the institution's default",
    "mint.shoulder_default": "(default shoulder)",
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
    "cl.title": "Principals & credentials",
    "cl.lede": "Who may mint, and with which key. <b>Reach is an attribute of the "
               "registration</b> — it cannot be widened by a request or a token grant.",
    "cl.issued": "Credential issued",
    "cl.issued_warn": "<b>This value will never be shown again.</b> Copy it now. "
                      "Only its hash is stored.",
    "cl.principals": "Principals",
    "cl.reach": "Reach",
    "cl.scope": "Scopes",
    "cl.creds": "Credentials",
    "cl.live": "active",
    "cl.dead": "revoked",
    "cl.open": "Open",
    "cl.add": "Register a principal",
    "cl.disabled": "disabled",
    "cl.all_naans": "all NAANs",
    "cl.empty": "No principal registered yet.",
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
