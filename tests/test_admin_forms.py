"""管理画面から台帳を組む操作。

**画面の出し分けと実際の認可が同じ判定であること**を見る。別々になっていると
「ボタンは出ないが POST は通る」穴ができる——ここで確かめたいのはそれ。
"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority, Client, Manager, Naan, Shoulder
from arkhe.domain import admin_ops as ops

# ------------------------------------------------ 約束の水準（組織自身の宣言）


def test_組織管理者は自組織の約束を変えられる(db, world, principal_of, as_principal):
    """**約束は組織自身のもの。** 述べる主体が述べられなければ意味がない。"""
    a = world["a"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-unchanging"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, a.id).commitment_level == "permanent-unchanging"


def test_組織管理者は他組織の約束を変えられない(db, world, principal_of, as_principal):
    a, b = world["a"], world["b"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{b.id}", data={"commitment": "not-guaranteed"})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Manager, b.id).commitment_level != "not-guaranteed"


def test_システム管理者はどの組織の約束も変えられる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM))
    r = c.post(f"/admin/manager/{world['c'].id}", data={"commitment": "descriptive-only"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, world["c"].id).commitment_level == "descriptive-only"


def test_組織管理者は自組織の採番上限を外せない(db, world, principal_of, as_principal):
    """**上限は配った側が課すもの。** 課された側が外せては意味がない。"""
    a = world["a"]
    a.quota_per_day = 10
    db.commit()
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-stable", "quota": ""})
    assert r.status_code == 303          # 約束のほうは通る
    db.expire_all()
    assert db.get(Manager, a.id).quota_per_day == 10   # 上限は動かない


# ---------------------------------------- NAA ポリシー（名前空間を配る側の宣言）


def test_NAAポリシーは組織管理者には変えられない(db, world, principal_of, as_principal):
    """**NAAN 配下の全組織にかかる宣言。** 1 組織が他組織の分まで書き換えられない。"""
    before = db.get(Naan, "99999").na_policy
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/naan/99999", data={"policy": "書き換えた", "minter": ""})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == before


def test_NAAN管理者はポリシーを宣言できる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/naan/99999", data={"policy": "NP | NR, OP, CC | 2027 |", "minter": ""})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == "NP | NR, OP, CC | 2027 |"


def test_NAANの登録はシステム管理者だけ(db, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.get("/admin/naan/new").status_code == 403
    assert c.post(
        "/admin/naan/new", data={"naan": "77777", "name": "x"}
    ).status_code == 403


# ------------------------------------------------------------ 画面が届く範囲


def test_NAANの設定画面は組織管理者には開けない(world, principal_of, as_principal):
    """**開ける条件と保存できる条件を揃える。**

    開けてしまうと、編集できるように見えるフォームが保存で 403 になる。
    出し分けと認可がずれているのと同じ。
    """
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/naan/99999").status_code == 403


def test_他組織の設定画面は開けない(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get(f"/admin/manager/{world['b'].id}").status_code == 403


def test_自組織の設定画面は開ける(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.get(f"/admin/manager/{world['a'].id}")
    assert r.status_code == 200
    assert "permanent-dynamic" in r.text


def test_一覧に自組織への導線が出る(world, principal_of, as_principal):
    """**約束は組織自身のものなので、組織管理者にも導線を出す。**"""
    a = world["a"]
    r = as_principal(principal_of(manager=a)).get("/admin/")
    assert f"/admin/manager/{a.id}" in r.text
    # NAAN の設定と shoulder の操作は出さない（届かないので）
    assert "/admin/naan/99999" not in r.text
    assert "/admin/naan/new" not in r.text


# -------------------------------------------------------------- 組み立て操作


def test_オンボードは画面からもできる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/manager/new", data={
        "naan": "99999", "name": "D組織", "shoulder": "/d4",
        "commitment": "permanent-stable", "quota": "100",
    })
    assert r.status_code == 303
    m = db.scalar(db.query(Manager).filter_by(name="D組織").statement)
    assert m.commitment_level == "permanent-stable"
    assert m.quota_per_day == 100
    # **組織と名前空間は必ず対で作られる。**
    assert db.get(Shoulder, m.default_shoulder_id).shoulder == "/d4"


def test_shoulderはretiredから戻せない(db, world, principal_of, as_principal):
    """画面から入っても不変条件は同じ——判定は `admin_ops` にしかない。"""
    sh = world["sh_a"]
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.post(f"/admin/shoulder/{sh.id}", data={"status": "retired"}).status_code == 303
    db.expire_all()
    r = c.post(f"/admin/shoulder/{sh.id}", data={"status": "active"})
    # **403 ではなく 400。** 権限の問題ではなく、誰にも許されていない操作。
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Shoulder, sh.id).status == "retired"


@pytest.mark.parametrize("level", ["permanent", "eternal", ""])
def test_知らない水準は画面からも入らない(db, world, principal_of, as_principal, level):
    a = world["a"]
    before = a.commitment_level
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": level})
    db.expire_all()
    if level == "":
        assert r.status_code == 303      # 空は「変えない」
    else:
        assert r.status_code == 400
    assert db.get(Manager, a.id).commitment_level == before


# ------------------------------------------------------ 利用者と鍵の発行


def test_画面から鍵を発行できる(db, world, root, principal_of, as_principal):
    """**平文はこの応答にしか載らない。** 保存しているのはハッシュだけ。"""
    c = ops.register_client(db, root, client_id="repo", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert r.status_code == 200
    db.expire_all()
    cred = db.get(Client, c.id).credentials[0]
    assert cred.active and cred.prefix in r.text
    # **平文は保存していない。** 画面に出たものが DB に無いことを確かめる。
    secret = r.text.split('class="secret">')[1].split("<")[0].strip()
    assert secret and secret not in cred.hashed


def test_再読み込みでは鍵は出てこない(db, world, root, principal_of, as_principal):
    """発行のたびに一度きり。リダイレクトで戻すと消える、を型で示す。"""
    c = ops.register_client(db, root, client_id="repo2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert 'class="secret"' not in cli.get(f"/admin/client/{c.id}").text


def test_人には鍵を発行しない(db, world, root, principal_of, as_principal):
    """**人に鍵を配ると、その人が組織を離れても鍵が生き残る。**"""
    c = ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 400
    # 画面にも発行の口を出さない
    assert "/key" not in cli.get(f"/admin/client/{c.id}").text


def test_他組織の利用者の鍵は発行できない(db, world, root, principal_of, as_principal):
    c = ops.register_client(db, root, client_id="other", naan="99999",
                            manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.get(f"/admin/client/{c.id}").status_code == 403
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 403


def test_失効させても行は残る(db, world, root, principal_of, as_principal):
    """**いつ失効したかを残す。** 誰の鍵だったかが辿れなくなってはいけない。"""
    from arkhe.db.models import Credential

    c = ops.register_client(db, root, client_id="rot", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    cid = issued.credential.id
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/revoke", data={"credential_id": cid})
    assert r.status_code == 303
    db.expire_all()
    cred = db.get(Credential, cid)
    assert cred is not None and not cred.active and cred.expires_at is not None


def test_組織管理者は自組織の利用者を登録できる(db, world, principal_of, as_principal):
    """画面の判定を `admin_ops` より厳しくしない（出せるはずのものが出せなくなる）。"""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "own-repo", "scopes": "ark:mint", "person": "",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="own-repo").statement)
    assert made.manager_id == world["a"].id


def test_組織管理者は他組織を選べない(db, world, principal_of, as_principal):
    """選択肢を出していない値が送られてきても、自組織に落とす。"""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "sneaky", "manager_id": str(world["b"].id), "scopes": "ark:mint",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="sneaky").statement)
    assert made.manager_id == world["a"].id


# ------------------------------------------- 押せないものは出さない


def test_組織管理者に監査ログを見せない(world, principal_of, as_principal):
    """**押しても断られるだけの導線は出さない。**

    監査ログは NAAN 単位以上にしか見せないので、組織単位の管理者には
    リンクごと出さない（出すと、押して 403 を見るまで分からない）。
    """
    c = as_principal(principal_of(manager=world["a"]))
    home = c.get("/admin/").text
    assert "/admin/audit" not in home
    assert c.get("/admin/audit").status_code == 403   # 直接叩けば当然断る


def test_NAAN管理者には監査ログを見せる(world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert "/admin/audit" in c.get("/admin/").text
    assert c.get("/admin/audit").status_code == 200


def test_採番できない主体には採番の導線を出さない(world, principal_of, as_principal):
    """scope で決まる。**出し分けとルートの判定は同じもの。**"""
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:read"]))
    assert "/admin/mint" not in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 403


def test_採番できる主体には出す(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:mint"]))
    assert "/admin/mint" in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 200


def test_所属の無い主体には利用者の登録を出さない(world, principal_of, as_principal):
    """自組織が無ければ誰の利用者も作れない。"""
    c = as_principal(principal_of(manager=None))
    assert "/admin/client/new" not in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 403


def test_組織管理者には利用者の登録を出す(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert "/admin/client/new" in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 200


def test_出ている導線は全て開ける(world, principal_of, as_principal):
    """**出し分けと認可がずれていないこと**の総当たり確認。

    画面に出ているリンクを片端から開き、1 つでも断られたら出し分けが間違っている。
    """
    import re

    for p in (principal_of(authority=Authority.SYSTEM),
              principal_of(authority=Authority.NAAN),
              principal_of(manager=world["a"])):
        c = as_principal(p)
        seen, todo = set(), ["/admin/", "/admin/clients"]
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            r = c.get(path)
            assert r.status_code == 200, f"{p.authority} に出ている {path} が {r.status_code}"
            for href in re.findall(r'href="(/admin/[^"?#]*)"', r.text):
                if href not in seen and not href.endswith(("logout", "login")):
                    todo.append(href)


# --------------------------------- 構成が受け付ける鍵だけを出す


@pytest.fixture
def with_auth(app, settings, as_principal, principal_of):
    """`ARKHE_AUTH` を差し替えた画面を、システム管理者として開く。"""
    from arkhe.settings import get_settings

    def use(mechanisms):
        app.dependency_overrides[get_settings] = lambda: settings.model_copy(
            update={"auth": mechanisms}
        )
        return as_principal(principal_of(authority=Authority.SYSTEM))

    return use


def test_apikeyを受けない構成ではAPIキーを出さない(db, world, root, with_auth):
    """**使えない鍵を出せる画面は、押しても何も起きないボタンと同じ。**

    `authenticate` は `ARKHE_AUTH` に挙がった機構しか試さないので、
    apikey が無効なら、出した API キーはどこからも通らない。
    """
    c = ops.register_client(db, root, client_id="m1", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = with_auth(["oidc"])
    page = cli.get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' not in page and 'value="client_secret"' not in page
    # 認可サーバに寄せた構成であることを画面で説明する
    assert "azp" in page
    # URL を直接叩いても作らせない
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 403
    db.expire_all()
    assert db.get(Client, c.id).credentials == []


def test_oauth2を受ける構成ではclient_secretも出す(db, world, root, with_auth):
    c = ops.register_client(db, root, client_id="m2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey", "oauth2"]).get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' in page and 'value="client_secret"' in page


def test_どちらも受けない構成では理由を出す(db, world, root, with_auth):
    """空欄を見せて終わらせない。**何を直せばよいかまで書く。**"""
    c = ops.register_client(db, root, client_id="m3", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth([]).get(f"/admin/client/{c.id}").text
    assert "ARKHE_AUTH" in page


def test_登録が無ければ正しいトークンでも通さない(db, world, root):
    """**紐付けが要る。** 認可サーバで認証できることと、この名前空間を
    触ってよいことは別なので、台帳に無い主体は通さない。

    照合は `azp` → `client_id` → `sub` の順（`auth/oidc.py`）。
    """
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    v = OidcVerifier.__new__(OidcVerifier)
    v.decode = lambda _t: {"azp": "誰でもない", "scope": "ark:mint"}
    with pytest.raises(AuthError, match="not registered"):
        v.authenticate(db, "dummy")


def test_登録すれば同じトークンが通る(db, world, root):
    """登録＝紐付け。鍵を出さずに、これだけで通るようになる。"""
    from arkhe.auth.oidc import OidcVerifier

    ops.register_client(db, root, client_id="kc-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.decode = lambda _t: {"azp": "kc-repo", "scope": "ark:mint"}
    p = v.authenticate(db, "dummy")
    assert p.client_id == "kc-repo" and p.has("ark:mint")


def test_認可サーバ構成では登録の意味を説明する(db, world, root, with_auth):
    """鍵を出す画面ではなく、**紐付けの画面**であることを先に言う。"""
    page = with_auth(["oidc"]).get("/admin/client/new").text
    assert "azp" in page and "preferred_username" in page


def test_認可サーバの場所を画面に出す(db, world, root, app, settings, as_principal, principal_of):
    """**「認可サーバで作れ」だけでは、どの認可サーバか分からない。**"""
    from arkhe.settings import get_settings

    c = ops.register_client(db, root, client_id="kc-m", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"auth": ["oidc"], "oidc_issuer": "https://kc.example.org/realms/arkhe"}
    )
    page = as_principal(principal_of(authority=Authority.SYSTEM)).get(
        f"/admin/client/{c.id}"
    ).text
    assert "https://kc.example.org/realms/arkhe" in page


# ------------------------------ 認可サーバ構成での止め方（唯一の止め方）


def test_oidcでは止める手段が要る(db, world, root):
    """**鍵が無いので `revoke_credential` は効かない。**

    ここを落とさない限り、認可サーバが出し続けるトークンで通ってしまう。
    """
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    c = ops.register_client(db, root, client_id="kc-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.decode = lambda _t: {"azp": "kc-stop", "scope": "ark:mint"}
    assert v.authenticate(db, "t").client_id == "kc-stop"

    ops.set_client_active(db, root, client_pk=c.id, active=False)
    db.commit()
    with pytest.raises(AuthError, match="not registered"):
        v.authenticate(db, "t")


def test_止めても戻せる(db, world, root):
    c = ops.register_client(db, root, client_id="back", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_client_active(db, root, client_pk=c.id, active=False)
    ops.set_client_active(db, root, client_pk=c.id, active=True)
    db.commit()
    assert c.active


def test_去った組織の主体は戻せない(db, world, root):
    """**「新規採番は止める」という宣言を、個別の復帰で骨抜きにしない。**"""
    from arkhe.domain.authz import Invalid

    c = ops.register_client(db, root, client_id="gone", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    assert not c.active
    with pytest.raises(Invalid):
        ops.set_client_active(db, root, client_pk=c.id, active=True)


def test_画面から止められる(db, world, root, principal_of, as_principal):
    c = ops.register_client(db, root, client_id="ui-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/active", data={"active": ""}).status_code == 303
    db.expire_all()
    assert not db.get(Client, c.id).active


def test_他組織の主体は止められない(db, world, root, principal_of, as_principal):
    c = ops.register_client(db, root, client_id="other-stop", naan="99999",
                            manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/active", data={"active": ""}).status_code == 403
    db.expire_all()
    assert db.get(Client, c.id).active


# ----------------------------------------------------- 種別を選べること


def test_鍵の種別が構成に応じて選べる(db, world, root, with_auth):
    """有効な機構が 2 つあれば、2 つとも選べる。"""
    c = ops.register_client(db, root, client_id="k2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey", "oauth2"]).get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' in page and 'value="client_secret"' in page
    # 両方選べるなら、片方しか無い理由の注記は出さない
    # （`ARKHE_AUTH` は他の注記にも出るので、この注記そのものを見る）
    assert "one-kind" not in page


def test_片方しか選べないなら理由を出す(db, world, root, with_auth):
    """**空欄ではなく、何を足せばよいかを出す。**"""
    c = ops.register_client(db, root, client_id="k1", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey"]).get(f"/admin/client/{c.id}").text
    assert 'value="client_secret"' not in page
    assert "one-kind" in page and "oauth2" in page


def test_採番の種別は候補であって縛りではない(world, principal_of, as_principal):
    """ERC の `what` は語彙を定めない。**画面が縛ってはいけない。**"""
    c = as_principal(principal_of(manager=world["a"]))
    page = c.get("/admin/mint").text
    assert "<datalist" in page and 'value="Dataset"' in page
    # select ではないので、一覧に無い値も送れる
    assert c.post("/admin/mint", data={"url": "https://x/1", "type": "自由な値"}).status_code == 200


def test_一覧に無い種別も保存できる(db, world, principal_of, as_principal):
    from arkhe.db.models import Ark

    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/mint", data={"url": "https://x/2", "type": "うちの資料区分"})
    saved = db.scalars(db.query(Ark).filter_by(type="うちの資料区分").statement).all()
    assert saved, "一覧に無い種別が保存されていない"


# ------------------------------------------------- 入り方が画面から分かる


def test_認可サーバ構成の機械は未設定に見えない(db, world, root, with_auth):
    """**鍵の本数を出すと、正しく設定できている主体が未設定に見える。**

    `oidc` だけの構成では機械も鍵を持たない。「資格情報 0 有効」ではなく
    「認可サーバ」と出す。
    """
    from arkhe.api import i18n

    ops.register_client(db, root, client_id="idp-only", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["oidc"]).get("/admin/clients").text
    assert 'data-entry="idp"' in page
    assert "0 " + i18n.JA["cl.live"] not in page


def test_鍵を持つ機械は鍵と出る(db, world, root, with_auth):

    c = ops.register_client(db, root, client_id="with-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert 'data-entry="key"' in with_auth(["apikey"]).get("/admin/clients").text


def test_本当に未設定なら未設定と出す(db, world, root, with_auth):
    """**「認可サーバに任せてある」と「まだ入れない」を混ぜない。**"""

    c = ops.register_client(db, root, client_id="nothing", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = with_auth(["apikey"])          # oidc 無し・鍵無し ＝ 入れない
    assert 'data-entry="none"' in cli.get("/admin/clients").text
    # 詳細では、何をすればよいかまで出す
    assert "ARKHE_AUTH" in cli.get(f"/admin/client/{c.id}").text


def test_止めた主体は入り方によらず通らない(db, world, root):
    """入り方の表示は説明であって、認可そのものではない。"""
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    c = ops.register_client(db, root, client_id="idp-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_client_active(db, root, client_pk=c.id, active=False)
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.decode = lambda _t: {"azp": "idp-stop", "scope": "ark:mint"}
    with pytest.raises(AuthError):
        v.authenticate(db, "t")


def test_機構が無効な鍵は入り方に数えない(db, world, root, with_auth):
    """**持っていても通らない鍵を「鍵」と出すと嘘になる。**

    `oidc` だけの構成に残っている古い API キーがまさにこれ。
    """

    c = ops.register_client(db, root, client_id="stale-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.issue_credential(db, root, client_pk=c.id)   # api_key
    db.commit()
    page = with_auth(["oidc"]).get(f"/admin/client/{c.id}").text
    # 文言ではなく印で見る（「鍵」は見出しにも出るので誤検出する）
    assert 'data-entry="idp"' in page
    assert 'data-entry="key"' not in page


def test_認可サーバ側の実在は断言しない(db, world, root, with_auth):
    """**arkhe は認可サーバに問い合わせない。**

    「入れる」と断言すると、向こうにクライアントが無い主体まで設定済みに
    見える。委ねていることを述べ、確かめる先を示すに留める。
    """

    c = ops.register_client(db, root, client_id="not-in-kc", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["oidc"]).get(f"/admin/client/{c.id}").text
    assert 'data-entry="idp"' in page
    assert "arkhe からは分かりません" in page or "not something arkhe" in page


# ------------------------------------------------ できること（scope）の選択


def test_scopeはチェックボックスで選ぶ(world, principal_of, as_principal):
    """**自由入力だと、検査されない綴りを登録できてしまう。**"""
    from arkhe.domain.authz import SCOPES

    page = as_principal(principal_of(manager=world["a"])).get("/admin/client/new").text
    for sc in SCOPES:
        assert f'value="{sc}"' in page
    assert '<input id="scopes"' not in page      # 自由入力は残っていない


def test_選んだscopeだけが入る(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "picked", "scopes": ["ark:mint", "ark:tombstone"]})
    made = db.scalar(db.query(Client).filter_by(client_id="picked").statement)
    assert set(made.allowed_scopes.split()) == {"ark:mint", "ark:tombstone"}


def test_語彙の外は捨てる(db, world, principal_of, as_principal):
    """画面に出していない値が送られてきても使わない。"""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "sneaky-scope", "scopes": ["ark:mint", "ark:everything"]})
    made = db.scalar(db.query(Client).filter_by(client_id="sneaky-scope").statement)
    assert made.allowed_scopes == "ark:mint"


def test_ひとつも選ばなければ最小になる(db, world, principal_of, as_principal):
    """空で登録して**何もできない主体**を作らない（採番だけは残す）。"""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={"client_id": "nothing-picked"})
    made = db.scalar(db.query(Client).filter_by(client_id="nothing-picked").statement)
    assert made.allowed_scopes == "ark:mint"


# ------------------------- 組織管理者が作る利用者は自組織から出られない


def test_他組織のshoulderに固定できない(db, world, principal_of, as_principal):
    """**画面に出していない shoulder_id を送っても通らない。**"""
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/client/new", data={
        "client_id": "cross-shoulder", "shoulder_id": str(world["sh_b"].id),
        "scopes": ["ark:mint"]})
    assert r.status_code in (400, 403)
    assert db.scalar(db.query(Client).filter_by(client_id="cross-shoulder").statement) is None


def test_他組織を所属先にできない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "cross-org", "manager_id": str(world["b"].id), "scopes": ["ark:mint"]})
    made = db.scalar(db.query(Client).filter_by(client_id="cross-org").statement)
    assert made.manager_id == world["a"].id      # 自組織に落ちる


def test_他NAANには作れない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/client/new", data={
        "client_id": "cross-naan", "naan": "88888", "scopes": ["ark:mint"]})
    assert r.status_code == 403
    assert db.scalar(db.query(Client).filter_by(client_id="cross-naan").statement) is None


def test_より広い権限の主体は作れない(db, world, principal_of, as_principal):
    """`authority=naan` や `system` を送っても、自分より広くはならない。

    **ルートがこの欄を受け取らない**ので、送られても捨てられる。拒むより、
    そもそも入口を持たないほうが確実。
    """
    c = as_principal(principal_of(manager=world["a"]))
    for auth in ("naan", "system"):
        c.post("/admin/client/new", data={
            "client_id": f"climb-{auth}", "authority": auth, "scopes": ["ark:mint"]})
        made = db.scalar(db.query(Client).filter_by(client_id=f"climb-{auth}").statement)
        assert made is not None and made.authority == "manager", auth


def test_作られた利用者は自組織にしか打てない(
    db, world, root, principal_of, as_principal
):
    """**登録の範囲だけでなく、採番の範囲も自組織に閉じている。**"""
    from arkhe.auth.errors import Forbidden
    from arkhe.domain import authz

    cli = as_principal(principal_of(manager=world["a"]))
    cli.post("/admin/client/new", data={"client_id": "org-repo", "scopes": ["ark:mint"]})
    made = db.scalar(db.query(Client).filter_by(client_id="org-repo").statement)

    p = principal_of(manager=world["a"], client_id="org-repo")
    # 省略すれば自組織の既定
    assert authz.shoulder_for(db, p, None).manager_id == world["a"].id
    # 他組織の shoulder を名指ししても通らない
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, world["sh_b"].shoulder)
    assert made.manager_id == world["a"].id


# ------------------------------- 組織に何を任せ、何を制限するか


def test_許していない機構では通らない(db, world, root):
    """**発行を止めるだけでは足りない。**

    制限を掛ける前に出した鍵が生き残り、「制限した」と思っているのに
    通り続けてしまう。認証時にも効かせる。
    """
    from arkhe.auth import apikey
    from arkhe.auth.errors import AuthError

    c = ops.register_client(db, root, client_id="pre-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert apikey.authenticate(db, issued.secret).client_id == "pre-key"

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, issued.secret)


def test_許していない機構の鍵は発行できない(db, world, root):
    from arkhe.domain.authz import Invalid

    c = ops.register_client(db, root, client_id="no-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    with pytest.raises(Invalid):
        ops.issue_credential(db, root, client_pk=c.id)


def test_自己登録を止められる(db, world, root, principal_of, as_principal):
    from arkhe.auth.errors import Forbidden

    ops.set_org_policy(db, root, manager_id=world["a"].id, may_self_register=False)
    db.commit()
    with pytest.raises(Forbidden):
        ops.register_client(db, principal_of(manager=world["a"]), client_id="blocked",
                            naan="99999", manager_id=world["a"].id, scopes="ark:mint")
    # 配る側は作れる
    ops.register_client(db, root, client_id="by-naan", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()

    # 画面にも導線を出さない
    cli = as_principal(principal_of(manager=world["a"]))
    assert "/admin/client/new" not in cli.get("/admin/clients").text


def test_scopeの上限を超えられない(db, world, root, principal_of):
    """**誰が作るかによらず効く。** 例外を作るなら上限のほうを動かす。"""
    from arkhe.domain.authz import Invalid

    ops.set_org_policy(db, root, manager_id=world["a"].id,
                       max_scopes=["ark:mint", "ark:update"])
    db.commit()
    with pytest.raises(Invalid):
        ops.register_client(db, principal_of(manager=world["a"]), client_id="over",
                            naan="99999", manager_id=world["a"].id,
                            scopes="ark:mint ark:tombstone")
    # 配る側でも同じ（宣言した上限を超える主体を台帳に並べない）
    with pytest.raises(Invalid):
        ops.register_client(db, root, client_id="over2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:tombstone")


def test_組織は自分の制限を外せない(db, world, root, principal_of):
    from arkhe.auth.errors import Forbidden

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"],
                       may_self_register=False, max_scopes=["ark:mint"])
    db.commit()
    p = principal_of(manager=world["a"])
    for kw in ({"mechanisms": []}, {"may_self_register": True}, {"max_scopes": []}):
        with pytest.raises(Forbidden):
            ops.set_org_policy(db, p, manager_id=world["a"].id, **kw)


def test_制限は画面から掛けられる(db, world, principal_of, as_principal):
    from arkhe.db.models import Manager

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post(f"/admin/manager/{world['a'].id}", data={
        "commitment": "", "quota": "", "policy": "1",
        "allowed_auth": ["oidc"], "self_register": "", "max_scopes": ["ark:mint"]})
    assert r.status_code == 303
    db.expire_all()
    m = db.get(Manager, world["a"].id)
    assert m.allowed_auth == "oidc" and not m.may_self_register and m.max_scopes == "ark:mint"


def test_制限欄を出していない画面からは消えない(db, world, root, principal_of, as_principal):
    """**組織管理者の保存で、配る側が掛けた制限が消えてはいけない。**"""
    from arkhe.db.models import Manager

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    db.expire_all()
    assert db.get(Manager, world["a"].id).allowed_auth == "oidc"


def test_監査に接続元が残る(db, world, principal_of, as_principal):
    """主体が運んできた接続元が、監査の行に落ちること。

    刻む側（要求の層）は `test_admin.py` で別に見る——ここは
    認証を差し替えているので、刻印そのものは通らない。
    """
    from dataclasses import replace

    from arkhe.db.models import AuditEvent

    p = replace(principal_of(authority=Authority.NAAN), ip="198.51.100.7")
    as_principal(p).post(f"/admin/manager/{world['a'].id}",
                         data={"commitment": "permanent-stable"})
    ev = db.scalars(db.query(AuditEvent).filter_by(action="set_commitment").statement).all()
    assert ev and ev[-1].ip == "198.51.100.7"


def test_監査ログの画面に接続元が出る(world, principal_of, as_principal):
    from arkhe.api import i18n

    c = as_principal(principal_of(authority=Authority.NAAN))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    page = c.get("/admin/audit").text
    assert i18n.JA["au.ip"] in page
    assert "X-Forwarded-For" in page or "x-forwarded-for" in page.lower()


# ------------------------------------------------- 発行した ARK の一覧


@pytest.fixture
def minted(db, world, root):
    """3 つの組織で 1 本ずつ採番する。**他組織のものが見えないこと**を見るため。"""
    from arkhe.domain import minting

    made = {}
    for key in ("a", "b", "c"):
        sh = world[key].default_shoulder
        ark, _ = minting.mint(db, shoulder=sh, created_by=f"{key}-repo",
                              url=f"https://{key}.example.org/1", title=f"{key} の対象")
        made[key] = ark
    db.commit()
    return made


def test_システム管理者は全arkを見られる(minted, principal_of, as_principal):
    page = as_principal(principal_of(authority=Authority.SYSTEM)).get("/admin/arks").text
    for a in minted.values():
        assert a.ark in page


def test_NAAN管理者はそのNAANだけ(minted, world, principal_of, as_principal):
    page = as_principal(principal_of(authority=Authority.NAAN, naan="99999")).get(
        "/admin/arks").text
    assert minted["a"].ark in page and minted["b"].ark in page
    assert minted["c"].ark not in page      # 別 NAAN


def test_組織管理者は自組織だけ(minted, world, principal_of, as_principal):
    page = as_principal(principal_of(manager=world["a"])).get("/admin/arks").text
    assert minted["a"].ark in page
    assert minted["b"].ark not in page      # 同じ NAAN の別組織
    assert minted["c"].ark not in page


def test_shoulder固定の主体はその範囲だけ(
    db, world, root, minted, principal_of, as_principal
):
    """採番できる範囲と、見える範囲を同じ絞り方にする。"""
    from arkhe.domain import minting

    other, _ = minting.mint(db, shoulder=world["sh_b"], created_by="x", url="https://x/9")
    db.commit()
    p = principal_of(manager=world["a"], shoulder=world["sh_a"])
    page = as_principal(p).get("/admin/arks").text
    assert minted["a"].ark in page and other.ark not in page


def test_検索は範囲を広げない(minted, world, principal_of, as_principal):
    """**絞り込みで他組織のものが出てきてはいけない。**"""
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/arks?q=example.org").text
    assert minted["a"].ark in page
    assert minted["b"].ark not in page and minted["c"].ark not in page


def test_ページ送りができる(db, world, root, principal_of, as_principal):
    """**件数は増える一方。** 並べるだけの画面はすぐ使えなくなる。"""
    from arkhe.api.admin import PAGE
    from arkhe.domain import minting

    for i in range(PAGE + 3):
        minting.mint(db, shoulder=world["a"].default_shoulder, created_by="bulk",
                     url=f"https://bulk.example.org/{i}")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    first = c.get("/admin/arks").text
    assert first.count("ark:/") >= PAGE
    assert "page=2" in first                       # 次があると分かる
    assert c.get("/admin/arks?page=2").status_code == 200


def test_他組織のarkの履歴は見られない(db, world, minted, principal_of, as_principal):
    """**一覧に出ないものが URL 直打ちで見えてはいけない。**

    到達範囲の判定を一覧と共有していることの確認。
    """
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get(f"/admin/arks/{minted['a'].ark}").status_code == 200
    assert c.get(f"/admin/arks/{minted['b'].ark}").status_code == 403
    assert c.get(f"/admin/arks/{minted['c'].ark}").status_code == 403


def test_履歴が画面から辿れる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://one.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://two.example/2"})
    page = c.get("/admin/arks/" + key.removeprefix("ark:/")).text
    assert "https://one.example/1" in page and "https://two.example/2" in page


# --------------------------------- 増えても使える（検索とページ送り）


def test_利用者一覧にページ送りがある(db, world, root, principal_of, as_principal):
    """**全件表示のままでは、増えたときに使えなくなる。**"""
    from arkhe.api.admin import PAGE

    for i in range(PAGE + 2):
        ops.register_client(db, root, client_id=f"bulk-{i:03}", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    first = c.get("/admin/clients").text
    assert "page=2" in first
    assert c.get("/admin/clients?page=2").status_code == 200


def test_利用者を検索できる(db, world, root, principal_of, as_principal):
    ops.register_client(db, root, client_id="findme-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    ops.register_client(db, root, client_id="other-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/clients?q=findme").text
    assert "findme-repo" in page and "other-repo" not in page


def test_利用者の検索は範囲を広げない(db, world, root, principal_of, as_principal):
    """**絞り込みで他組織のものが出てきてはいけない。**"""
    ops.register_client(db, root, client_id="b-secret", naan="99999",
                        manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/clients?q=secret").text
    assert "b-secret" not in page


def test_監査ログにページ送りがある(db, world, principal_of, as_principal):
    """直近 200 件で頭打ちだと、**古いものを見る手段が無かった**。"""
    from arkhe.api.admin import PAGE

    c = as_principal(principal_of(authority=Authority.NAAN))
    for _ in range(PAGE + 2):
        c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    first = c.get("/admin/audit").text
    assert "page=2" in first
    assert c.get("/admin/audit?page=2").status_code == 200


def test_監査ログを検索できる(db, world, principal_of, as_principal):
    """行そのものを見る——`set_commitment` は入力欄の例示にも出るので、
    本文の有無で判定すると誤検出する。"""
    import re

    def rows(html):
        return re.findall(r'data-label="[^"]*">([^<]*set_commitment[^<]*)<', html)

    c = as_principal(principal_of(authority=Authority.NAAN))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    assert rows(c.get("/admin/audit?q=set_commit").text)
    assert not rows(c.get("/admin/audit?q=見つからない語").text)


def test_一覧の集計は見えている範囲だけを数える(db, world, principal_of, as_principal):
    """**以前は `ark` 全体を毎回集計していた。**

    ARK は増える一方なので、組織管理の画面を開くたびに全表走査が走る。
    発行するクエリを見て、範囲で絞られていることを確かめる。
    """
    seen = []

    from sqlalchemy import event

    engine = db.get_bind()

    def spy(conn, cursor, statement, params, context, many):  # noqa: ARG001
        if "count(" in statement.lower() and " ark" in statement.lower():
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        as_principal(principal_of(manager=world["a"])).get("/admin/")
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert seen, "集計クエリが見つからない"
    assert any("shoulder_id IN" in s or "shoulder_id in" in s for s in seen), (
        "範囲で絞られていない（全件集計している）"
    )


def test_ark一覧を組織で絞れる(minted, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    both = c.get("/admin/arks").text
    assert minted["a"].ark in both and minted["b"].ark in both
    only_a = c.get(f"/admin/arks?org={world['a'].id}").text
    assert minted["a"].ark in only_a and minted["b"].ark not in only_a


def test_絞り込みは到達範囲を広げない(minted, world, principal_of, as_principal):
    """**届かない組織を指定しても、何も出ない。**"""
    c = as_principal(principal_of(manager=world["a"]))
    page = c.get(f"/admin/arks?org={world['b'].id}").text
    assert minted["b"].ark not in page and minted["a"].ark not in page


def test_組織単位の管理者に絞り込みは出さない(minted, world, principal_of, as_principal):
    """自組織しか見えないので、選択肢 1 つの絞り込みは操作を増やすだけ。"""
    page = as_principal(principal_of(manager=world["a"])).get("/admin/arks").text
    assert 'name="org"' not in page


def test_ark詳細に記述が出る(db, world, principal_of, as_principal):
    """**`?` と `??` で公開されるのはこの内容。** 画面と公開面がずれていないか
    を見られるようにする。"""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://x/1", "title": "題", "who": "山田", "when": "2026",
        "type": "Dataset", "source": "どこか",
    }).json()["ark"].removeprefix("ark:/")
    page = c.get(f"/admin/arks/{key}").text
    for v in ("題", "山田", "2026", "Dataset", "どこか"):
        assert v in page, v


def test_画面の文言にマークダウンを残さない():
    """**翻訳は HTML として出す。** バッククォートやアスタリスクをそのまま
    書くと、記号が画面に出てしまう（実際に何度か混入した）。
    """
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        for key, value in cat.items():
            assert "`" not in value, f"{lang}/{key}: バッククォートは <code> にする"
            assert "**" not in value, f"{lang}/{key}: 強調は <b> にする"


def test_訳の対はファイル内でそろっている():
    """**分けた単位ごとに JA と EN の鍵が一致する。**

    全体の抜けは起動時に落ちるが、それは最後の砦であって最初の砦ではない。
    画面ごとに揃えておけば、片方だけ足したことが**その差分の中で**分かる。
    """
    from arkhe.api import i18n

    for part in i18n._PARTS:
        only_ja = sorted(set(part.JA) - set(part.EN))
        only_en = sorted(set(part.EN) - set(part.JA))
        assert not only_ja and not only_en, (
            f"{part.__name__}: 日本語だけ={only_ja} 英語だけ={only_en}"
        )


def test_迎える時点で制限を掛けられる(db, world, principal_of, as_principal):
    """**後から掛け直す運用にすると、必ず掛け忘れが残る。**"""
    from arkhe.db.models import Manager

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/manager/new", data={
        "naan": "99999", "name": "新設の組織", "shoulder": "/n1",
        "commitment": "permanent-stable", "quota": "",
        "policy": "1", "allowed_auth": ["oidc"], "self_register": "",
        "max_scopes": ["ark:mint"],
    })
    assert r.status_code == 303
    m = db.scalar(db.query(Manager).filter_by(name="新設の組織").statement)
    assert m.allowed_auth == "oidc"
    assert not m.may_self_register
    assert m.max_scopes == "ark:mint"


def test_制限の欄は組織管理者には出さない(world, principal_of, as_principal):
    """**自分の裁量ではないことが分かるほうがよい。** 見せて押せないより。"""
    from arkhe.api import i18n

    page = as_principal(principal_of(manager=world["a"])).get(
        f"/admin/manager/{world['a'].id}").text
    assert i18n.JA["op.title"] not in page
    # 約束の水準（組織自身のもの）は出る
    assert i18n.JA["manager.f.commitment"] in page


# ------------------------- 名前空間の決まりと、組織ごとの狭め


def test_名前空間の決まりが配下すべてにかかる(db, world, root):
    """**原則は NAAN。** 組織が増えると 1 つずつ掛けるのは現実的でない。"""
    from arkhe.domain.authz import Invalid

    ops.set_naan_policy(db, root, naan="99999", max_scopes=["ark:mint"])
    db.commit()
    # 組織側は何も設定していないのに、上限が効く
    with pytest.raises(Invalid):
        ops.register_client(db, root, client_id="over-naan", naan="99999",
                            manager_id=world["a"].id, scopes="ark:tombstone")


def test_組織は狭められるが広げられない(db, world, root):
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    ops.set_naan_policy(db, root, naan="99999", max_scopes=["ark:mint", "ark:update"])
    ops.set_org_policy(db, root, manager_id=world["a"].id, max_scopes=["ark:mint"])
    ops.set_org_policy(db, root, manager_id=world["b"].id,
                       max_scopes=["ark:mint", "ark:update", "ark:tombstone"])
    db.commit()
    naan = db.get(Naan, "99999")
    # 狭めたほうは効く
    assert policy_for(naan, world["a"]).max_scopes == "ark:mint"
    # 広げようとしても、NAAN の外には出られない
    assert set(policy_for(naan, world["b"]).max_scopes.split()) == {"ark:mint", "ark:update"}


def test_自己登録はNAANが許していなければ組織でも許されない(db, world, root):
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    ops.set_naan_policy(db, root, naan="99999", may_self_register=False)
    ops.set_org_policy(db, root, manager_id=world["a"].id, may_self_register=True)
    db.commit()
    assert not policy_for(db.get(Naan, "99999"), world["a"]).may_self_register


def test_名前空間の決まりは認証時にも効く(db, world, root):
    """組織側だけを見ると、名前空間の既定が効かない。"""
    from arkhe.auth import apikey
    from arkhe.auth.errors import AuthError

    c = ops.register_client(db, root, client_id="naan-wide-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert apikey.authenticate(db, issued.secret).client_id == "naan-wide-stop"

    ops.set_naan_policy(db, root, naan="99999", mechanisms=["oidc"])
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, issued.secret)


def test_NAAN画面から決まりを掛けられる(db, world, principal_of, as_principal):
    from arkhe.db.models import Naan

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/naan/99999", data={
        "policy": "NP | NR", "minter": "", "rules": "1",
        "allowed_auth": ["oidc"], "self_register": "", "max_scopes": ["ark:mint"],
    })
    assert r.status_code == 303
    db.expire_all()
    n = db.get(Naan, "99999")
    assert n.allowed_auth == "oidc" and not n.may_self_register
    assert n.max_scopes == "ark:mint" and n.na_policy == "NP | NR"
