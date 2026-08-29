"""監査ログの文言。誰が何をしたかの記録。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
    # 監査
    "au.title": "監査ログ",
    "au.lede": "<b>NAAN 以上に届く操作は全件記録します。</b>"
               "届く範囲が広いほど、後から誰が何をしたかを辿れる必要が高いためです。",
    "au.recent": "直近の操作",
    "au.at": "日時",
    "au.who": "主体",
    "au.action": "操作",
    "au.target": "対象",
    "au.act.sign_in": "ログイン",
    "au.act.sign_out": "ログアウト",
    "au.failed": "失敗",
    "au.ip": "接続元",
    "au.ip_hint": "<b>前段を信じた結果であって、証拠ではありません。</b>"
                  "<code>ARKHE_TRUSTED_PROXIES</code> が 0 なら直接の接続元、"
                  "n なら <code>X-Forwarded-For</code> の右から n 番目です"
                  "——このヘッダは誰でも付けられるので、左端は採りません。",
    "au.detail": "詳細",
    "au.count": "件",
    "au.empty": "記録がありません。",
}

EN: dict[str, str] = {
    "au.title": "Audit log",
    "au.lede": "<b>Every action that reaches NAAN scope or wider is recorded.</b> "
               "The wider the reach, the more it matters that you can trace who did "
               "what. <b>Sign-ins and sign-outs are recorded for everyone</b> — "
               "including the ones that failed.",
    "au.recent": "Recent actions",
    "au.at": "When",
    "au.who": "Principal",
    "au.action": "Action",
    "au.target": "Target",
    "au.act.sign_in": "signed in",
    "au.act.sign_out": "signed out",
    "au.failed": "failed",
    "au.ip": "From",
    "au.ip_hint": "<b>This is what the hop in front reported, not proof.</b> With "
                  "<code>ARKHE_TRUSTED_PROXIES</code> at 0 it is the peer that "
                  "connected; at n it is the n-th entry from the right of "
                  "<code>X-Forwarded-For</code> — anyone can set that header, so the "
                  "leftmost entry is never used.",
    "au.detail": "Detail",
    "au.count": "entries",
    "au.empty": "Nothing recorded.",
}
