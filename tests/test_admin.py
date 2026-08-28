"""管理画面と管理操作。

**画面の出し分けと実際の認可に同じ判定を使う**ことを固定する。別々にすると
「ボタンは出ないが URL を直接叩けば通る」穴ができる。
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Authority, ShoulderStatus
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


def test_機関と名前空間は対で生まれる(db, world):
    """片方だけでは意味がない（採番できない機関を作るだけ）。"""
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


def test_他機関の主体は作れない(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="x", naan="99999", manager_id=world["b"].id
        )


# ------------------------------------------------------------- 画面


def test_機関管理者には自分の範囲しか見えない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    body = c.get("/admin/").text
    assert "A機関" in body
    assert "B機関" not in body  # 同じ NAAN の他機関も見えない
    assert "88888" not in body


def test_監査ログは機関管理者には見せない(db, world, principal_of, as_principal):
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


def test_画面からでも他機関には採番できない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.post("/admin/mint", data={"shoulder": "/b2"}).status_code == 403


def test_採番権限が無ければ画面も開けない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert c.get("/admin/mint").status_code == 403


# ------------------------------------------------------------- 国際化


@pytest.mark.parametrize(
    "lang,needle", [("ja", "委譲の構造"), ("en", "Delegation")]
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
    assert "Delegation" in r.text


def test_翻訳に抜けが無い():
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        assert set(cat) == set(i18n.JA), f"{lang} に抜けがある"


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

    from arkhe.api import admin as admin_router
    from arkhe.app import _install_handlers
    from arkhe.db import session as session_mod
    from arkhe.settings import get_settings

    def build(settings):
        a = FastAPI()
        _install_handlers(a)
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
    assert r.status_code == 200 and "A機関" in r.text


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
# 外部 IdP を持たない機関でも単体で建てられるようにするための入口。
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
    assert "A機関" in cli.get("/admin/").text


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
