"""API が返す誤りの符号。**一覧はここだけ。**

**符号を付けるのは、本文の文言に頼らせないため。** 文面は直る（訳も直る、語調も
変わる）が、符号は変わらない。呼び出し側が `if "は存在しない" in body` のような
書き方をせずに済む。

**英語と日本語を両方持つ。** `message` は応答本文に出る英語で、読者はこの台帳の
外にいる。`ja` は文書に載せる日本語の説明で、**運用する人は日本語で読む**。
2 つを別々の場所に置くと必ずずれるので、1 つの表にしてある——参照ページも
この表から検査する（`tests/test_docs.py`）。

対象は **API と解決の口だけ**。管理画面は `api/i18n/` で別に日本語を持っており、
起動時の設定エラーは運用者の端末に出るものなので、どちらもここには入れない。

番号の割り当て:

  1000 番台  要求が読めない・値が不正（400）
  1200 番台  認証（401）
  1300 番台  認可（403）と委譲の案内（307）
  1400 番台  見つからない（404）
  1600 番台  上限（429）
"""

from __future__ import annotations

from dataclasses import dataclass


class ApiError(Exception):
    """符号を持つ誤り。**応答本文は `{code, message, detail}` になる。**

    `Code` を渡すと符号・状態符号・英語の文面が付き、`**fmt` は文面を埋めると
    同時に `detail` として**構造化されたまま**本文に載る（`limit` や `missing`
    を文字列から切り出させない）。

    文字列や辞書を渡した**従来の形も受ける**。管理画面はそちらで、日本語の文面を
    そのまま返す——読者が違うので、無理に符号を振らない。
    """

    status = 400

    def __init__(self, detail=None, /, *, challenge: str | None = None, **fmt):
        self.code: Code | None = None
        self.message = ""
        if isinstance(detail, Code):
            self.code = detail
            self.status = detail.status
            self.message = detail.say(**fmt)
            self.detail = fmt
        else:
            self.detail = detail
        if challenge is not None:
            self.challenge = challenge
        super().__init__(self.message or str(self.detail))

    def body(self) -> dict:
        """HTTP に載せる形。**符号が無いものは従来どおり。**"""
        if self.code is None:
            return self.detail if isinstance(self.detail, dict) else {"detail": self.detail}
        out = {"code": self.code.number, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class Code:
    """1 つの誤り。**符号・状態符号・英語の文面・日本語の説明**をまとめて持つ。"""

    number: str
    status: int
    #: 応答本文に出る英語。`{}` は `say()` で埋める。
    message: str
    #: 参照ページに出す日本語の説明。**本文には出さない。**
    ja: str

    def say(self, **kw) -> str:
        return self.message.format(**kw) if kw else self.message


# --------------------------------------------------------------- 400 値が不正
ARK_UNREADABLE = Code(
    "ARKHE-1001", 400,
    "Not readable as an ARK: {reason}",
    "ARK として読めない。ラベル・NAAN・名前のいずれかが仕様に合わない",
)
QUALIFIER_FORM = Code(
    "ARKHE-1002", 400,
    "A qualifier must begin with '/' (a part) or '.' (a variant).",
    "修飾子は `/`（包含）か `.`（変種）で始める。ほかの文字では始められない",
)
QUALIFIER_OUTSIDE_BASE = Code(
    "ARKHE-1003", 400,
    "The qualifier does not point inside the base name: {qualifier}",
    "修飾子が base を指していない。base の内側にある部分参照でなければならない",
)
NAME_TOO_LONG = Code(
    "ARKHE-1004", 400,
    "The name is {length} octets; at most {limit} are indexed "
    "(Base Name plus Qualifier, draft-kunze-ark-42 §3.1).",
    "名前が長すぎる。仕様が受け取る側に義務づける 255 オクテットまでを索引できる",
)
ALREADY_REGISTERED = Code(
    "ARKHE-1005", 400,
    "{ark} is already registered.",
    "既に登録済み。**黙って上書きしない**——書き換えるなら update を使う",
)
URL_SCHEME_REFUSED = Code(
    "ARKHE-1006", 400,
    "A target must not use a scheme a browser would execute ({schemes}).",
    "ブラウザに解釈させると危ないスキームは行き先にできない。"
    "`urn:` `doi:` などは通る（空も正当）",
)
SHOULDER_REQUIRED = Code(
    "ARKHE-1007", 400,
    "A principal with authority={authority} must name a shoulder.",
    "NAAN 単位以上の主体は shoulder を明示する。既定を持たせないのは誤爆を防ぐため",
)
SHOULDER_UNKNOWN = Code(
    "ARKHE-1008", 400,
    "No such shoulder: {shoulder}",
    "その shoulder は存在しない",
)
SHOULDER_AMBIGUOUS = Code(
    "ARKHE-1009", 400,
    "Shoulder {shoulder} exists under more than one NAAN; name the naan as well.",
    "同じ shoulder が複数の NAAN にある。**どれか 1 つを勝手に選ばない**",
)
NO_DEFAULT_SHOULDER = Code(
    "ARKHE-1010", 400,
    "The organisation has no default shoulder.",
    "組織に default_shoulder が設定されていない",
)
IMPORT_CHECK_DIGIT = Code(
    "ARKHE-1012", 400,
    "Check digit mismatch: {ark} was not minted by a NOID minter, or was mistyped.",
    "取り込もうとした名前の検査桁が合わない。**外で採番された名前を信じる唯一の手段**"
    "なので、ここは緩めない",
)
IMPORT_NAME_OUTSIDE_SHOULDER = Code(
    "ARKHE-1013", 400,
    "The name {name} does not fall inside a shoulder of NAAN {naan}.",
    "取り込む名前が、その NAAN のどの shoulder にも属していない",
)

BULK_LIMIT = Code(
    "ARKHE-1011", 400,
    "A request holds at most {limit} rows.",
    "1 リクエストの件数上限（`ARKHE_BULK_LIMIT`）を超えた",
)

# ----------------------------------------------------------------- 401 認証
NO_CREDENTIALS = Code(
    "ARKHE-1201", 401,
    "No credentials.",
    "資格情報が無い。**公開情報の読取には要らない**ので、これは書き込みの口",
)
INVALID_CREDENTIALS = Code(
    "ARKHE-1202", 401,
    "Invalid credentials.",
    "資格情報が受け付けられない。有効な機構は `ARKHE_AUTH` で決まる",
)

TOKEN_ENDPOINT_DISABLED = Code(
    "ARKHE-1203", 404,
    "This deployment does not issue tokens itself (see ARKHE_AUTH).",
    "この構成は自前でトークンを発行しない。**口の無い構成で広告しない**ため 404",
)
UNSUPPORTED_GRANT_TYPE = Code(
    "ARKHE-1204", 400,
    "Only client_credentials is supported.",
    "対応していない grant_type。**実装しないものは明示して返す**",
)

# ------------------------------------------------------- 403 認可 / 307 委譲
INSUFFICIENT_SCOPE = Code(
    "ARKHE-1301", 403,
    "The token does not carry the required scope: {scope}",
    "トークンに要求された scope が無い。**scope は narrow できても広げられない**",
)
OUT_OF_REACH = Code(
    "ARKHE-1302", 403,
    "Outside this principal's registered reach: {target}",
    "到達範囲の外。範囲は資格情報の登録属性で決まり、リクエストでは広がらない",
)
NO_ORGANISATION = Code(
    "ARKHE-1303", 403,
    "The principal has no active organisation.",
    "主体に有効な組織が紐づいていない",
)
SHOULDER_NOT_MINTABLE = Code(
    "ARKHE-1304", 403,
    "Shoulder {shoulder} has status={status} and cannot be minted into.",
    "その shoulder は今の状態では採番できない（`retired` / `reserved` など）",
)
INVALID_SCOPE = Code(
    "ARKHE-1305", 403,
    "Scopes not allowed for this client: {scopes}",
    "そのクライアントに許可されていない scope を要求した。"
    "**本文は RFC 6749 §5.2 の形**（`error` / `error_description`）で、符号は併記",
)
IMPORT_NAAN_NOT_AUTHORITATIVE = Code(
    "ARKHE-1308", 403,
    "This resolver is not authoritative for NAAN {naan}; it cannot take custody of names in it.",
    "取り次いでいるだけの NAAN には取り込めない。**他所の名前空間の保管者を"
    "名乗ることになる**",
)

IMPORT_SHOULDER_NOT_DELEGATED = Code(
    "ARKHE-1307", 403,
    "Shoulder {shoulder} has status={status}; only a delegated shoulder can be imported into.",
    "委譲していない shoulder には取り込めない。**自分で採番している名前空間に外から"
    "名前を入れると、採番と衝突しうる**——委譲したからこそ、外で採られた名前がある",
)

SHOULDER_DELEGATED = Code(
    "ARKHE-1306", 307,
    "Minting for shoulder {shoulder} is delegated; go to the minter in Location.",
    "その shoulder の採番は外に委譲されている。**代理では呼ばない**"
    "——応答が失われると「向こうにはあるがこちらは知らない ARK」が生まれる",
)

# ------------------------------------------------------------- 404 見つからない
ARK_NOT_FOUND = Code(
    "ARKHE-1401", 404,
    "No such ARK in this ledger.",
    "台帳にその ARK が無い（一括操作では 1 件でも欠ければ全体が失敗する）",
)
ARK_UNKNOWN_NAME = Code(
    "ARKHE-1402", 404,
    "This resolver is authoritative for the NAAN and has no such name.",
    "その NAAN はこのリゾルバが権威を持つ。**だから「無い」と言い切れる**",
)
CHECK_DIGIT_MISMATCH = Code(
    "ARKHE-1403", 404,
    "Check digit mismatch: the identifier looks mistranscribed.",
    "検査桁が合わない。**打ち間違い・転記ミスの疑い**（NOID の NCDA が"
    "単一文字誤りと隣接転置を検出する）",
)
NO_METADATA_FOR_UNKNOWN_NAAN = Code(
    "ARKHE-1404", 404,
    "Metadata for an unknown NAAN is not held by this resolver.",
    "知らない NAAN について述べられることは無い。"
    "inflection 無しなら上位リゾルバへ取り次ぐ",
)

# ------------------------------------------------------------------ 429 上限
QUOTA_EXCEEDED = Code(
    "ARKHE-1601", 429,
    "Daily quota exhausted: {used} of {quota} used in the last 24 hours.",
    "1 日の採番上限に達した（組織ごとの `quota_per_day`）",
)


#: 参照ページの検査が使う一覧。**番号順**。
CODES: tuple[Code, ...] = tuple(
    sorted(
        (v for v in list(globals().values()) if isinstance(v, Code)),
        key=lambda c: c.number,
    )
)
