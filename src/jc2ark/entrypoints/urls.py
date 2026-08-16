"""URL 構成。**minter と resolver で出す口を変える。**

arklet は combined で minter も 302 を返していたが、ここでは分ける（M8 の
読み取り専用ロール分離と、SC2 のレプリカ振り分けが意味を持つようにするため）。
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from jc2ark.ark import views_api, views_resolve

minter_patterns = [
    # OAuth2: /o/token/ ・ revoke ・ introspect ・ .well-known
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    path("mint", views_api.MintView.as_view(), name="mint"),
    path("update", views_api.UpdateView.as_view(), name="update"),
    path("bulk_mint", views_api.BulkMintView.as_view(), name="bulk_mint"),
    path("bulk_update", views_api.BulkUpdateView.as_view(), name="bulk_update"),
    path("bulk_query", views_api.BulkQueryView.as_view(), name="bulk_query"),
    # OpenAPI（外部機関が既製のクライアントで繋げるように出す）
    path("openapi.json", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
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
