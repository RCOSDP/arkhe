"""設定。**エントリポイントをドメインから分離する**（I9）。

`RESOLVER=1` で resolver として起動する。minter と resolver は同じイメージだが、
**URL も DB ロールも分ける**（M8・SC2）。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

SECRET_KEY = os.environ.get("JC2ARK_SECRET_KEY", "dev-only-insecure")
DEBUG = os.environ.get("JC2ARK_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("JC2ARK_ALLOWED_HOSTS", "*").split(",")

#: resolver として動くか。SC2 のルータと URL 構成がこれを見る。
IS_RESOLVER = os.environ.get("RESOLVER", "0") == "1"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "oauth2_provider",
    "rest_framework",
    "drf_spectacular",
    "jc2ark.ark",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # 管理画面の静的ファイルを gunicorn 単体で配れるようにする。
    # DEBUG=False では Django が /static/ を配らないので、これが無いと
    # admin が素の HTML になる。
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "jc2ark.entrypoints.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": os.environ.get("JC2ARK_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("JC2ARK_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("JC2ARK_DB_USER", ""),
        "PASSWORD": os.environ.get("JC2ARK_DB_PASSWORD", ""),
        "HOST": os.environ.get("JC2ARK_DB_HOST", ""),
        "PORT": os.environ.get("JC2ARK_DB_PORT", ""),
    }
}
# SC2: レプリカが設定されていれば resolver はそちらを読む。
if os.environ.get("JC2ARK_REPLICA_HOST"):
    DATABASES["replica"] = {
        **DATABASES["default"],
        "HOST": os.environ["JC2ARK_REPLICA_HOST"],
        # M8: resolver は**読み取り専用ロール**で接続する。
        "USER": os.environ.get("JC2ARK_REPLICA_USER", DATABASES["default"]["USER"]),
        "PASSWORD": os.environ.get("JC2ARK_REPLICA_PASSWORD", DATABASES["default"]["PASSWORD"]),
    }
DATABASE_ROUTERS = ["jc2ark.entrypoints.routers.PrimaryReplicaRouter"]

AUTH_PASSWORD_VALIDATORS = []
STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("JC2ARK_STATIC_ROOT", str(BASE_DIR / "static"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ---- OAuth2（S1 の結果を反映） ----
OAUTH2_PROVIDER_APPLICATION_MODEL = "ark.Client"
OAUTH2_PROVIDER = {
    # **発行・更新・墓碑化・読み取りを分ける。**
    # 「発行はさせないが更新はさせる」は実際に起きる（離脱した機関の転送先維持）。
    # 墓碑化を update と分けるのは、**それが「対象が失われた」という宣言**であり、
    # 転送先の付け替えとは意味も影響も違うから。投入バッチには絶対に渡さない。
    "SCOPES": {
        "ark:mint": "ARK を採番する",
        "ark:update": "転送先とメタデータを更新する",
        "ark:tombstone": "対象が失われたと宣言する（墓碑化）",
        "ark:read": "ARK のメタデータを読む",
    },
    "ACCESS_TOKEN_EXPIRE_SECONDS": int(os.environ.get("JC2ARK_TOKEN_TTL", "3600")),
    # S1-2: **これが無いと、クライアント登録に無い scope をトークン要求で取れる
    # ＝権限昇格。** 拡張点は validator ではなく scopes backend。
    "SCOPES_BACKEND_CLASS": "jc2ark.ark.scopes.PerClientScopes",
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "JC2 ARK API",
    "DESCRIPTION": "ARK の採番・更新 API。解決は認証不要で別系統。",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
