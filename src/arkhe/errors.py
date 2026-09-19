"""The error codes the API returns. This is the only list of them.

A code exists so that callers do not have to read the wording. Wording changes, with a
translation or a change of tone; a code does not, so nobody has to write something like
`if "does not exist" in body`.

Each entry carries both languages. message is the English that appears in the response,
for readers outside this ledger; ja is the Japanese explanation for the reference page,
because the people running arkhe read it in Japanese. Kept in two places they would
drift, so they are one table, and the reference page is checked against it
(tests/test_docs.py).

Only the API and the resolution endpoints are covered. The admin screens carry their own
wording in api/i18n, and a settings error at startup appears on an operator's terminal;
neither belongs here.

How the numbers are assigned:

  1000s  the request cannot be read, or a value is wrong (400)
  1200s  authentication (401)
  1300s  authorisation (403) and pointing at a delegate (307)
  1400s  not found (404)
  1500s  the wrong state (409): the values and the permissions are right, but the row
         is not in that state
  1600s  a limit was reached (429)
"""

from __future__ import annotations

from dataclasses import dataclass


class ApiError(Exception):
    """An error that carries a code. The response body is {code, message, detail}.

    Passing a Code attaches the code, the status and the English wording. Anything in
    **fmt fills the wording and also appears in detail, still structured, so that values
    such as limit or missing do not have to be cut out of a sentence.

    A plain string or dictionary is still accepted. The admin screens use that and
    return their own wording: they have a different reader, so no code is forced on
    them.
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
        """The shape that goes over HTTP. Without a code, it is as it was."""
        if self.code is None:
            return self.detail if isinstance(self.detail, dict) else {"detail": self.detail}
        out = {"code": self.code.number, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class Code:
    """One error: its code, its status, the English wording and the Japanese note."""

    number: str
    status: int
    #: The English that appears in the response. say() fills the placeholders.
    message: str
    #: The Japanese explanation for the reference page. It never appears in a
    #: response.
    ja: str

    def say(self, **kw) -> str:
        return self.message.format(**kw) if kw else self.message


# ------------------------------------------------------- 400 a value is wrong
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

NAME_WITHDRAWN = Code(
    "ARKHE-1014", 400,
    "{ark} was withdrawn before publication; that name is never assigned again.",
    "公開前に取り下げられた名前。**二度と採らない**——予約した文字列は既に人の手に"
    "渡っているので、別の対象に付け直せば外からは NR 違反と見分けがつかない",
)

PURGE_NEEDS_REASON = Code(
    "ARKHE-1015", 400,
    "Purging a published ARK requires a reason; it is kept with the name.",
    "公開した ARK の破棄には理由が要る。**残らない破棄は、無かったことと同じ**"
    "——消えた識別子について後から言えることが、これしか残らない",
)
EXPOSED_NEEDS_REASON = Code(
    "ARKHE-1017", 400,
    "This ARK has been published; unpublishing or deleting it requires a reason.",
    "**一度でも外に出した名前**を引っ込める・消すには理由が要る。その間に誰かが"
    "引用しているかもしれず、**こちらからは知りようがない**——後から言えることが"
    "これしか残らない",
)
EXPOSED_NOT_CONFIRMED = Code(
    "ARKHE-1018", 400,
    "Send `confirm` with the ARK itself ({ark}): it has been published.",
    "**一度でも外に出した名前**なので、対象を `confirm` に打ち直す"
    "——一覧を回すスクリプトが、意図せず全件を引っ込めることのないように",
)
PURGE_NOT_CONFIRMED = Code(
    "ARKHE-1016", 400,
    "Send `confirm` with the ARK itself ({ark}) to purge it.",
    "破棄する ARK を `confirm` に打ち直す。**一覧を回すスクリプトが、意図せず"
    "全件消すことのないように**",
)

BULK_LIMIT = Code(
    "ARKHE-1011", 400,
    "A request holds at most {limit} rows.",
    "1 リクエストの件数上限（`ARKHE_BULK_LIMIT`）を超えた",
)

# ------------------------------------------------------- 401 authentication
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

# ------------------------------------- 403 authorisation, 307 delegation
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

SHOULDER_DELEGATED_UNREACHABLE = Code(
    "ARKHE-1309", 403,
    "Minting for shoulder {shoulder} happens elsewhere; this ledger does not mint in it.",
    "その shoulder の採番は外で行われており、**ここから叩ける口は無い**（閉域など）。"
    "案内のページがあれば `detail.about` に載る——`Location` に人向けのページを"
    "載せると、クライアントはそこへ POST しにいく",
)

SHOULDER_DELEGATED = Code(
    "ARKHE-1306", 307,
    "Minting for shoulder {shoulder} is delegated; go to the minter in Location.",
    "その shoulder の採番は外に委譲されている。**代理では呼ばない**"
    "——応答が失われると「向こうにはあるがこちらは知らない ARK」が生まれる",
)


# ------------------------------------------------------------ 404 not found
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

# ----------------------------------------------------- 409 the wrong state
ARK_ALREADY_PUBLIC = Code(
    "ARKHE-1501", 409,
    "{ark} is published; unpublish it first (or purge it in one step).",
    "**公開中の ARK は、そのままでは削除できない。** 先に公開を取り下げる"
    "（`/api/unpublish`）か、`/api/purge` で一手に行う。**どちらも理由と打ち直しを"
    "要求する**。消さずに済ませるなら tombstone に付け替えるか `url` を空にする"
    "（`NR` を宣言している以上、"
    "解決が止まることは許されない）",
)
ARK_NOT_PUBLIC = Code(
    "ARKHE-1503", 409,
    "{ark} is not published; there is nothing to withdraw from publication.",
    "その ARK は公開していないので、公開を取り下げることはできない"
    "（消すなら取り下げではなく削除）",
)
ARK_HAS_PARTS = Code(
    "ARKHE-1502", 409,
    "{ark} has {count} qualified name(s) under it; withdraw those first.",
    "修飾子付きの名前がぶら下がっている。**先に下から取り下げる**"
    "——親だけ消すと、行き先を継ぐ先の無い部分参照が残る",
)

# ---------------------------------------------------------------- 429 limits
QUOTA_EXCEEDED = Code(
    "ARKHE-1601", 429,
    "Daily quota exhausted: {used} of {quota} used in the last 24 hours.",
    "1 日の採番上限に達した（組織ごとの `quota_per_day`）",
)


#: The list the reference-page check reads, in number order.
CODES: tuple[Code, ...] = tuple(
    sorted(
        (v for v in list(globals().values()) if isinstance(v, Code)),
        key=lambda c: c.number,
    )
)
