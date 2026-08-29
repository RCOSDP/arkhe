"""ログインの文言。ログイン画面と、戻すための案内。

**訳の対を同じファイルに置く。** 片方だけ足したのが差分で見える
——起動時の検査に頼るのは最後の砦であって、最初の砦ではない。
"""

from __future__ import annotations

JA: dict[str, str] = {
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
    "login.title": "管理画面にログイン",
    "login.id": "ID",
    "login.id_ph": "メールアドレスなど",
    "login.password": "パスワード",
    "login.submit": "ログイン",
    "login.failed": "ID かパスワードが違います",
    "login.logout": "ログアウト",
}

EN: dict[str, str] = {
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
    "login.title": "Sign in to the admin interface",
    "login.id": "ID",
    "login.id_ph": "your email address, for example",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.failed": "That ID and password do not match",
    "login.logout": "Sign out",
}
