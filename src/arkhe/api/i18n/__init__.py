"""管理画面の国際化。日本語と英語を既定で持つ。

gettext ではなく辞書にしてある。理由は 2 つ:
  - `.mo` のコンパイルがイメージのビルド手順に増える（この規模では割に合わない）
  - 言語を足すのがモジュール 1 つで済み、翻訳の抜けが起動時に分かる

将来 translator に渡す必要が出たら、この辞書から `.po` を吐けばよい。

言語の決め方は **`?lang=` → cookie → `Accept-Language` → 既定(ja)** の順。
明示の選択を記憶するので、切り替えたら以降のページでも保たれる。

## 画面ごとに分けてある

1 ファイルに 288 件を並べると、直したい語を探すのに全体を読むことになる。
**分ける単位は言語ではなく画面。** 日本語と英語を別ファイルにすると対が
離れてしまい、片方だけ足したことが差分に出ない——起動時の検査に頼るのは
最後の砦であって、最初の砦ではない。

  _shell    どの画面にも出る語（見出し・状態・フォームの共通語）
  _ledger   組織と名前空間。委譲の構造と、それを組む操作
  _clients  主体の登録、資格情報、入り方と scope
  _arks     採番と、発行した ARK
  _signin   ログイン画面と、戻すための案内
  _audit    監査ログ
"""

from __future__ import annotations

from fastapi import Request

from arkhe.api.i18n import _arks, _audit, _clients, _ledger, _shell, _signin

DEFAULT = "ja"
LANGS = {"ja": "日本語", "en": "English"}
COOKIE = "arkhe_lang"

#: 画面ごとの語彙を 1 つに束ねる。**同じキーが 2 か所にあれば起動時に落とす**
#: ——後から入れたほうが黙って勝つと、直したはずの語が直らない。
_PARTS = (_shell, _ledger, _clients, _arks, _signin, _audit)


def _merge(attr: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in _PARTS:
        cat = getattr(part, attr)
        clash = out.keys() & cat.keys()
        if clash:  # pragma: no cover - 開発時にしか起きない
            raise RuntimeError(f"{part.__name__} でキーが重複: {sorted(clash)}")
        out |= cat
    return out


JA: dict[str, str] = _merge("JA")
EN: dict[str, str] = _merge("EN")

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
