"""URL 構成。**minter と resolver で出す口を変える**（arklet と同じ考え方だが、
minter に resolve を残さない点が違う——arklet は combined で minter も 302 を
返していた）。"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

minter_patterns = [
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    path("admin/", admin.site.urls),
]

resolver_patterns: list = []

urlpatterns = resolver_patterns if settings.IS_RESOLVER else minter_patterns
