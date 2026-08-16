"""URL 構成。**minter と resolver で出す口を変える。**

arklet は combined で minter も 302 を返していたが、ここでは分ける（M8 の
読み取り専用ロール分離と、SC2 のレプリカ振り分けが意味を持つようにするため）。
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from jc2ark.ark import views_resolve

minter_patterns = [
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    path("admin/", admin.site.urls),
]

resolver_patterns = [
    path(".well-known/ark", views_resolve.well_known_ark, name="well_known_ark"),
    re_path(
        r"^(?:resolve/)?(?P<ark>[aA][rR][kK]:/?.*$)",
        views_resolve.resolve_ark,
        name="resolve_ark",
    ),
]

urlpatterns = resolver_patterns if settings.IS_RESOLVER else minter_patterns
