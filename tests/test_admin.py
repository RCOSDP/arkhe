"""管理画面と管理操作。

**画面の出し分けと実際の認可に同じ判定を使う**ことを固定する。別々にすると
「ボタンは出ないが URL を直接叩けば通る」穴ができる。
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Authority, Client, ShoulderStatus
from arkhe.domain import admin_ops as ops
from arkhe.domain.authz import Invalid

# ------------------------------------------------------------- 遷移の禁則


def test_retiredからは戻せない(db, world, root):
    """**引退した名前空間の再開は NR 違反の芽。** その間に外部が同じ名前を使って
    いる可能性を否定できない。"""
    ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="retired")
    db.commit()
    with pytest.raises(Invalid) as e:
        ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="active")
    assert "retired" in e.value.detail["reason"]


def test_委譲には採番の行き先が要る(db, world, root):
    with pytest.raises(Invalid):
        ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="delegated")
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    assert world["sh_a"].status == ShoulderStatus.DELEGATED


def test_組織と名前空間は対で生まれる(db, world):
    """片方だけでは意味がない（採番できない組織を作るだけ）。"""
    assert world["a"].default_shoulder_id == world["sh_a"].id


# ------------------------------------------------------------- 権限の階層


def test_NAANを配れるのはシステム管理者だけ(db, world, principal_of):
    with pytest.raises(Forbidden):
        ops.create_naan(db, principal_of(authority=Authority.NAAN), naan="77777", name="x")


def test_自分より広い到達範囲は与えられない(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="evil", naan="99999", authority=Authority.SYSTEM.value
        )


def test_他組織の主体は作れない(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="x", naan="99999", manager_id=world["b"].id
        )


# ------------------------------------------------------------- 画面


def test_組織管理者には自分の範囲しか見えない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    body = c.get("/admin/").text
    assert "A組織" in body
    assert "B組織" not in body  # 同じ NAAN の他組織も見えない
    assert "88888" not in body


def test_監査ログは組織管理者には見せない(db, world, principal_of, as_principal):
    """誰がいつ何をしたかは、その名前空間を預かる側の情報。"""
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/audit").status_code == 403
    c2 = as_principal(principal_of(authority=Authority.NAAN))
    assert c2.get("/admin/audit").status_code == 200


def test_画面から採番できる(db, world, principal_of, as_principal):
    """**API と同じ経路**（authz → minting）を通る。画面専用の抜け道を作らない。"""
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/mint", data={"url": "https://example.org/manual"})
    assert r.status_code == 200 and "ark:/99999/a1" in r.text


def test_画面からでも他組織には採番できない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.post("/admin/mint", data={"shoulder": "/b2"}).status_code == 403


def test_採番権限が無ければ画面も開けない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert c.get("/admin/mint").status_code == 403


# ------------------------------------------------------------- 国際化


@pytest.mark.parametrize(
    "lang,needle", [("ja", "組織管理"), ("en", "Organisations")]
)
def test_日英を切り替えられる(db, world, principal_of, as_principal, lang, needle):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    assert needle in c.get("/admin/", params={"lang": lang}).text


def test_言語の選択は記憶される(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", params={"lang": "en"})
    assert r.cookies.get("arkhe_lang") == "en"


def test_Accept_Languageを見る(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", headers={"accept-language": "en-US,en;q=0.9"})
    assert "Organisations" in r.text


def test_翻訳に抜けが無い():
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        assert set(cat) == set(i18n.JA), f"{lang} に抜けがある"


def test_scopeにはすべて説明がある():
    """**語彙が増えたら訳も増える。** 言語間の抜けは既存の検査で見つかるが、
    `SCOPES` に足して**どの言語にも入れ忘れる**と、対が揃ってしまうので通る
    ——実際 `ark:hold` は、画面に `sc.ark:hold` という生のキーが出ていた。

    OpenAPI の `clientCredentials.scopes` もここから起こすので、抜けると
    仕様書にキーが漏れる。
    """
    from arkhe.api import i18n
    from arkhe.domain import authz

    for lang, cat in i18n.CATALOGS.items():
        missing = [f"sc.{s}{sfx}" for s in authz.SCOPES for sfx in ("", ".d")
                   if f"sc.{s}{sfx}" not in cat]
        assert not missing, f"{lang} に無い scope の語: {missing}"


def test_予約は作成時にしか指定できない(db, world, root):
    """**active から reserved へは戻せない。** 一度採番できる状態にした名前空間を
    後から「未使用扱い」にはできない。"""
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    assert sh.status == ShoulderStatus.RESERVED
    with pytest.raises(Invalid):
        ops.add_shoulder(db, root, naan="99999", shoulder="/bad", status="retired")


def test_予約枠は採番できるようにできる(db, world, root):
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="active")
    assert sh.status == ShoulderStatus.ACTIVE


def test_言語切替のUIが常に出る(db, world, principal_of, as_principal):
    """**横並びのセグメントにしない。** 言語が増えると横に伸びて破綻するため、
    アイコンから開く一覧にしてある。開閉は Popover API に任せる（外側クリックと
    Esc が標準で効くので JS が要らない）。"""
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    body = c.get("/admin/").text
    assert 'popovertarget="lang-menu"' in body
    assert 'id="lang-menu" popover' in body
    # 選べる言語がすべて並び、現在の言語に印が付く
    from arkhe.api import i18n

    for code, label in i18n.LANGS.items():
        assert f'href="?lang={code}"' in body and label in body
    assert 'class="menu-i on"' in body


# ------------------------------------------------------- 管理画面への入口
#
# **ブラウザは Authorization ヘッダを付けられない。** API は Bearer で足りるが、
# 人が管理画面に入る経路は別に要る。3 つの入口を設定で選ぶ。


@pytest.fixture
def raw_app(factory):
    """認証を差し替えない素のアプリ。**入口そのものを試す。**"""
    from fastapi import FastAPI

    from arkhe import observability
    from arkhe.api import admin as admin_router
    from arkhe.app import _install_handlers
    from arkhe.db import session as session_mod
    from arkhe.settings import get_settings

    def build(settings):
        a = FastAPI()
        _install_handlers(a)
        observability.install(a)
        a.include_router(admin_router.router)

        def one_session():
            s = factory()
            try:
                yield s
            finally:
                s.close()

        a.dependency_overrides[session_mod.get_session] = one_session
        a.dependency_overrides[get_settings] = lambda: settings
        return a

    return build


def _settings(**kw):
    import secrets

    from arkhe.settings import Settings

    return Settings(
        auth=["apikey"], database_url="sqlite://",
        session_secret=secrets.token_urlsafe(48), session_secure=False, **kw
    )


def test_bearer_モードにログイン画面は無い(db, world, raw_app):
    """自動化・curl 専用の構成。**401 を返す**（ブラウザ向けの導線は持たない）。"""
    from fastapi.testclient import TestClient

    c = TestClient(raw_app(_settings(admin_login="bearer")), follow_redirects=False)
    assert c.get("/admin/").status_code == 401
    assert c.get("/admin/login").status_code == 404


def test_oidc_モードは未ログインならログインへ送る(db, world, raw_app):
    """**401 を返さない。** ブラウザにヘッダは付けられないので、401 を見せても
    人には何もできない。"""
    from fastapi.testclient import TestClient

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    c = TestClient(raw_app(cfg), follow_redirects=False)
    r = c.get("/admin/")
    assert r.status_code == 302 and r.headers["location"].startswith("/admin/login")


def test_proxy_モードは前段のヘッダを信じる(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    # **人の主体として登録する。** 機械用の主体は外部ログインでは名乗れない。
    ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint", subject_type="person")
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    # ヘッダが無ければログインへ（この構成に画面は無いので 404 になる）
    assert cli.get("/admin/").status_code == 302
    r = cli.get("/admin/", headers={"X-Forwarded-User": "alice@example.ac.jp"})
    assert r.status_code == 200 and "A組織" in r.text


def test_proxy_モードでも台帳に無い身元は通さない(db, world, raw_app):
    """認可サーバで認証できることと、この名前空間を触ってよいことは別。"""
    from fastapi.testclient import TestClient

    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    r = cli.get("/admin/", headers={"X-Forwarded-User": "stranger@example.com"})
    assert r.status_code == 302  # ログインへ送られる（＝入れない）


def test_セッションは署名され改竄できない(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    from arkhe.auth import session as sess

    ops.register_client(db, root, client_id="bob", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint", subject_type="person")
    db.commit()
    cfg = _settings(admin_login="proxy")
    cli = TestClient(raw_app(cfg), follow_redirects=False)

    good = sess.issue("bob", secret=cfg.session_secret, ttl=600)
    cli.cookies.set(sess.COOKIE, good)
    assert cli.get("/admin/").status_code == 200

    # 別の鍵で署名したものは通らない
    forged = sess.issue("bob", secret="x" * 48, ttl=600)
    cli.cookies.set(sess.COOKIE, forged)
    assert cli.get("/admin/").status_code == 302


def test_機械の主体は外部ログインで名乗れない(db, world, root, raw_app):
    """**前段の設定が緩んでヘッダが外から通っても、一括投入バッチには化けられない。**

    プロキシを正しく置けば防げる話だが、設定 1 つの誤りが「全件書き換え」に化ける
    のは脆い。人と機械を型で分けて、経路そのものを塞ぐ。
    """
    from fastapi.testclient import TestClient

    ops.register_client(db, root, client_id="batch", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")  # 既定は machine
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    assert cli.get("/admin/", headers={"X-Forwarded-User": "batch"}).status_code == 302


def test_人の主体は資格情報を持てない(db, world, root):
    """身元は外部が保証する。arkhe に鍵を持たせると、外部で失効させても入れてしまう。"""
    c = ops.register_client(db, root, client_id="carol@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.commit()
    with pytest.raises(Invalid):
        ops.issue_credential(db, root, client_pk=c.id)


def test_人の主体はAPIキーで認証できない(db, world, root):
    """逆向きも塞ぐ。鍵が何らかの経路で作られても、認証は通さない。"""
    from arkhe.auth import apikey
    from arkhe.db.models import Credential, CredentialKind

    c = ops.register_client(db, root, client_id="dave@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.flush()
    raw, prefix, hashed = apikey.generate_key()
    db.add(Credential(client_pk=c.id, kind=CredentialKind.API_KEY.value,
                      prefix=prefix, hashed=hashed))
    db.commit()
    from arkhe.auth.errors import AuthError

    with pytest.raises(AuthError):
        apikey.authenticate(db, raw)


# ------------------------------------------------------- ID とパスワード
#
# 外部 IdP を持たない組織でも単体で建てられるようにするための入口。
# oidc / proxy が使えるならそちらがよい（身元の管理が 1 か所に集まる）。


@pytest.fixture
def with_password(db, world, root):
    """人の主体を 1 つ作り、パスワードを設定する。"""
    c = ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint",
                            subject_type="person")
    db.flush()
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()
    return c


def _pw_client(raw_app):
    from fastapi.testclient import TestClient

    return TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)


def test_パスワードでログインできる(db, world, with_password, raw_app):
    cli = _pw_client(raw_app)
    assert cli.get("/admin/").status_code == 302  # 未ログインはログインへ
    assert cli.get("/admin/login").status_code == 200
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 302 and r.headers["location"] == "/admin/"
    assert "A組織" in cli.get("/admin/").text


def test_誤ったパスワードは入れない(db, world, with_password, raw_app):
    cli = _pw_client(raw_app)
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    assert r.status_code == 401
    assert cli.get("/admin/").status_code == 302


def test_存在しないIDと誤ったパスワードを区別しない(db, world, with_password, raw_app):
    """**「その ID は無い」と分かると、利用者の一覧を総当たりで作れる。**"""
    cli = _pw_client(raw_app)
    a = cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    b = cli.post("/admin/login", data={"username": "nobody@example.ac.jp", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    from arkhe.api import i18n

    assert i18n.JA["login.failed"] in a.text and i18n.JA["login.failed"] in b.text


def test_連続失敗で一時的に施錠される(db, world, with_password, raw_app):
    """**ログイン画面を出す以上、これが無いと辞書攻撃に素で晒される。**"""
    from arkhe.auth import password as pw

    cli = _pw_client(raw_app)
    for _ in range(pw.MAX_ATTEMPTS):
        cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    # 正しいパスワードでも受け付けない
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 401


def test_短いパスワードは設定できない(db, world, root):
    c = ops.register_client(db, root, client_id="bob@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.flush()
    with pytest.raises(Invalid):
        ops.set_password(db, root, client_pk=c.id, password="short")


def test_機械の主体にパスワードは設定できない(db, world, root):
    """機械はパスワードを覚えない。持たせると書き留められた鍵が増えるだけ。"""
    c = ops.register_client(db, root, client_id="batch2", naan="99999",
                            manager_id=world["a"].id)
    db.flush()
    with pytest.raises(Invalid):
        ops.set_password(db, root, client_pk=c.id, password="long-enough-password")


def test_パスワードの変更で古いものは通らなくなる(db, world, root, with_password, raw_app):
    """**古い行は消さずに無効化する**（いつ変えたかが残る）。"""
    ops.set_password(db, root, client_pk=with_password.id, password="a-brand-new-secret")
    db.commit()
    cli = _pw_client(raw_app)
    old = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                         "password": "correct-horse-battery"})
    assert old.status_code == 401
    new = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                         "password": "a-brand-new-secret"})
    assert new.status_code == 302


def test_外部URLへのリダイレクトに使えない(db, world, with_password, raw_app):
    """next に外部 URL を入れられると、ログイン直後に別サイトへ飛ばす踏み台になる。"""
    cli = _pw_client(raw_app)
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery",
                                       "next": "https://evil.example.com/"})
    assert r.headers["location"] == "/admin/"


def test_shoulder固定の主体は組織を継ぐ(db, world, root):
    """**shoulder は既に組織を決めている。**

    別々に渡させると、manager を書き忘れた主体ができ、認可の入口で必ず弾かれる
    ——しかも「shoulder は合っているのに通らない」という分かりにくい形で。
    """
    sh = world["a"].default_shoulder
    c = ops.register_client(
        db, root, client_id="pinned", naan=sh.naan, shoulder_id=sh.id,
        scopes="ark:mint",
    )
    db.commit()
    assert c.manager_id == sh.manager_id


def test_shoulderと組織の食い違いは拒む(db, world, root):
    """黙って片方を優先しない。どちらが正しいかは呼び出し側しか知らない。"""
    from arkhe.domain.authz import Invalid

    sh = world["a"].default_shoulder
    with pytest.raises(Invalid):
        ops.register_client(
            db, root, client_id="mismatch", naan=sh.naan, shoulder_id=sh.id,
            manager_id=world["b"].id, scopes="ark:mint",
        )


def test_約束の水準は言い直せる(db, world, root):
    """**既定のまま放置させないための口。**

    これが無いと全組織が `permanent-dynamic` を名乗ったまま動き、`??` は
    ソフトウェアの既定値を組織の宣言として公開してしまう。
    """
    m = world["a"]
    ops.set_commitment(db, root, manager_id=m.id, level="permanent-unchanging")
    db.commit()
    assert m.commitment_level == "permanent-unchanging"


def test_約束の水準は下げられる(db, world, root):
    """守れない約束を掲げ続けるより、言い直せるほうが誠実。"""
    m = world["a"]
    ops.set_commitment(db, root, manager_id=m.id, level="not-guaranteed")
    db.commit()
    assert m.commitment_level == "not-guaranteed"


def test_知らない水準は通さない(db, world, root):
    """`??` でそのまま公開される値なので、綴り間違いを通すと、組織が述べて
    いない水準を組織の名前で名乗ることになる。"""
    from arkhe.domain.authz import Invalid

    with pytest.raises(Invalid):
        ops.set_commitment(db, root, manager_id=world["a"].id, level="permanent")


def test_他組織の約束は変えられない(db, world, principal_of):
    """約束はその組織のもの。"""
    from arkhe.auth.errors import Forbidden

    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.set_commitment(db, p, manager_id=world["b"].id, level="not-guaranteed")


def test_onboard時に水準を述べられる(db, world, root):
    """迎え入れる時点で確かめる——後から直す運用にすると必ず既定が残る。"""
    m, _ = ops.onboard_manager(
        db, root, naan="99999", name="約束を述べた組織", shoulder="/c1",
        commitment_level="permanent-stable",
    )
    db.commit()
    assert m.commitment_level == "permanent-stable"


# ----------------------------------------------------------------- ログアウト


def test_oidcのログアウトは認可サーバのセッションも終わらせる(db, world, raw_app, monkeypatch):
    """**こちらの Cookie を消すだけでは、ログアウトしたことにならない。**

    次に `/admin/` を開くと認可サーバへ送られ、そちらのセッションが生きていれば
    何も訊かれずに戻ってくる——利用者から見れば「ログアウトできない」。
    """
    from fastapi.testclient import TestClient

    from arkhe.auth import login as login_flow

    monkeypatch.setattr(
        login_flow, "_discovery",
        {"end_session_endpoint": "https://kc.example.org/realms/arkhe/logout"},
    )
    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).post("/admin/logout")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://kc.example.org/realms/arkhe/logout")
    assert "client_id=arkhe-admin" in loc
    # **戻り先も渡す。** 渡さないと認可サーバの画面で行き止まりになる。
    assert "post_logout_redirect_uri=" in loc
    # **ID トークンは渡さない**——渡すには Cookie に抱えることになり、claim の多い
    # 環境で 4 KB を超えてブラウザに黙って捨てられる。
    assert "id_token_hint" not in loc


def test_end_sessionが無い認可サーバならこちらだけで終える(db, world, raw_app, monkeypatch):
    """RP からのログアウトに対応していない認可サーバもある。**落とさない。**"""
    from fastapi.testclient import TestClient

    from arkhe.auth import login as login_flow

    monkeypatch.setattr(login_flow, "_discovery", {"token_endpoint": "https://kc/token"})
    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).post("/admin/logout")
    assert r.status_code == 302 and r.headers["location"] == "/admin/"


def test_パスワードのログアウトは外に出ない(db, world, raw_app):
    """外部の認可サーバを使っていないので、終わらせるセッションはこちらだけ。"""
    from fastapi.testclient import TestClient

    r = TestClient(
        raw_app(_settings(admin_login="password")), follow_redirects=False
    ).post("/admin/logout")
    assert r.status_code == 302 and r.headers["location"] == "/admin/"
    assert 'arkhe_session=""' in r.headers.get("set-cookie", "") or \
           "Max-Age=0" in r.headers.get("set-cookie", "")


# ------------------------------------------------- ログインに戻す画面


def test_往復が失効したらログインへ戻れる(db, world, raw_app):
    """**行き止まりを作らない。**

    素のテキストを返していたので、利用者は URL を手で直すしかなかった。
    """
    from fastapi.testclient import TestClient

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).get("/admin/callback?code=x&state=y")
    assert r.status_code == 400
    assert 'href="/admin/login"' in r.text        # 戻り道がある
    assert "arkhe" in r.text and "<style" in r.text  # ログイン画面と同じ体裁


def test_認可サーバの拒否も同じ画面で返す(db, world, raw_app, monkeypatch):
    from fastapi.testclient import TestClient

    from arkhe.auth import session as sess

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    cli = TestClient(raw_app(cfg), follow_redirects=False)
    flow = sess.issue("flow", secret=cfg.session_secret, ttl=600,
                      extra={"flow": '{"state": "s1", "verifier": "v", "next": "/admin/"}'})
    cli.cookies.set("arkhe_login", flow)
    r = cli.get("/admin/callback?state=s1&error=access_denied")
    assert r.status_code == 403
    assert "access_denied" in r.text and 'href="/admin/login"' in r.text


def test_ログイン画面の無い構成でも案内を出す(db, world, raw_app):
    """404 を素のテキストで返すと、何が起きたのか分からない。"""
    from fastapi.testclient import TestClient

    r = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False).get(
        "/admin/login"
    )
    assert r.status_code == 404 and 'href="/admin/"' in r.text


def test_接続元を刻んでから渡す(db, world, root, raw_app):
    """**要求の層でしか分からないものを、そこで刻む。**

    ここが抜けると監査には空の接続元が並ぶ（画面は動くので気づきにくい）。
    前段 1 段の構成に長い `X-Forwarded-For` を投げ、**client の書いた左端では
    なく右端**が残ることまで見る。
    """
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    # 監査は NAAN 単位以上の操作だけ残すので、その範囲の人として入る。
    ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                        scopes="ark:mint", subject_type="person",
                        authority="naan",
                        expires_at=datetime.now(UTC) + timedelta(days=1))
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy", trusted_proxies=1)),
                     follow_redirects=False)
    r = cli.post(
        f"/admin/manager/{world['a'].id}",
        data={"commitment": "permanent-stable"},
        headers={"X-Forwarded-User": "alice@example.ac.jp",
                 "X-Forwarded-For": "203.0.113.9, 10.0.0.9"},
    )
    assert r.status_code == 303, r.text[:200]
    ev = db.scalars(db.query(AuditEvent).filter_by(action="set_commitment").statement).all()
    assert ev and ev[-1].ip == "10.0.0.9"


def test_ログアウトはGETでは通らない(db, world, raw_app):
    """**`SameSite=Lax` はトップレベルの GET 遷移では Cookie を送る。**

    GET のままだと、外部サイトから `<img src=".../logout">` で強制ログアウト
    させられる。
    """
    from fastapi.testclient import TestClient

    r = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False).get(
        "/admin/logout"
    )
    assert r.status_code == 405


def test_readyzはDBを見る(db, world, raw_app):
    """`/healthz` と兼ねていたので、**DB が落ちても Ready のままだった。**"""
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import get_settings

    cfg = _settings()
    app = create_app(cfg)
    app.dependency_overrides[get_settings] = lambda: cfg
    c = TestClient(app, follow_redirects=False)
    assert c.get("/healthz").status_code == 200

    # 届かない DB を指した構成で見る（依存を壊すのではなく、実際の失敗の形）。
    bad = _settings()
    bad = bad.model_copy(update={"database_url": "postgresql+psycopg://x@127.0.0.1:1/none"})
    gone = create_app(bad)
    g = TestClient(gone, follow_redirects=False)
    # **生存は変わらない**（プロセスは生きている）が、可用は落ちる。
    assert g.get("/healthz").status_code == 200
    assert g.get("/readyz").status_code == 503


def test_要求IDが応答に返る(db, world, raw_app):
    """利用者が「この ID で調べてほしい」と言えるようにする。"""
    from fastapi.testclient import TestClient

    c = TestClient(raw_app(_settings()), follow_redirects=False)
    r = c.get("/healthz", headers={"X-Request-Id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    # 前段が付けていなければ、こちらで作る
    assert TestClient(raw_app(_settings())).get("/healthz").headers.get("x-request-id")


# --------------------------------------------------- 入退室の記録


def test_ログインの成功が残る(db, world, root, raw_app):
    """**入退室は誰のものでも残す。** 到達範囲で間引かない。"""
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    ops.register_client(db, root, client_id="alice", naan="99999",
                        manager_id=world["a"].id, subject_type="person")
    c = db.scalar(db.query(Client).filter_by(client_id="alice").statement)
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()

    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    r = cli.post("/admin/login", data={"username": "alice",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 302
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_in").statement).all()
    # 組織単位の人でも残る（`audit()` なら間引かれる）
    assert len(ev) == 1 and ev[0].client_id == "alice" and ev[0].detail["ok"] is True


def test_ログインの失敗こそ残す(db, world, root, raw_app):
    """**成功したものより先に見たい記録。**

    打ち込まれた ID は残すが、パスワードは当然残さない。
    """
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    assert cli.post("/admin/login",
                    data={"username": "mallory", "password": "hunter2"}).status_code == 401
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_in").statement).all()
    assert len(ev) == 1
    assert ev[0].client_id == "mallory" and ev[0].detail["ok"] is False
    assert "hunter2" not in str(ev[0].detail), "パスワードが記録に残っている"


def test_ログアウトも残る(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    ops.register_client(db, root, client_id="bob", naan="99999",
                        manager_id=world["a"].id, subject_type="person")
    c = db.scalar(db.query(Client).filter_by(client_id="bob").statement)
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    cli.post("/admin/login", data={"username": "bob", "password": "correct-horse-battery"})
    cli.post("/admin/logout")
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_out").statement).all()
    assert len(ev) == 1 and ev[0].client_id == "bob"
