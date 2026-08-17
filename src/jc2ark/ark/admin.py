"""Django admin。**P2 の出口条件（オンボーディングを手で 1 通り通せる）を担う。**

break-glass（`authority=naan`）の発行もここから行う（§10.3）。
"""

from django.contrib import admin
from oauth2_provider.admin import ApplicationAdmin

from .models import Ark, AuditEvent, Client, Manager, Naan, Shoulder

# DOT が Application（＝我々の Client）を先に登録しているので差し替える。
admin.site.unregister(Client)


@admin.register(Naan)
class NaanAdmin(admin.ModelAdmin):
    list_display = ("naan", "name", "is_authoritative", "redirect", "minter", "na_policy")
    list_filter = ("is_authoritative",)
    search_fields = ("naan", "name")


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "naan",
        "default_shoulder",
        "commitment_level",
        "active",
        "succeeded_by",
        "quota_per_day",
    )
    list_filter = ("naan", "commitment_level", "active")
    search_fields = ("name",)
    autocomplete_fields = ("default_shoulder", "succeeded_by")


@admin.register(Shoulder)
class ShoulderAdmin(admin.ModelAdmin):
    """**状態がひと目で分かるようにする。** active / reserved / delegated / retired
    は運用の中心（リザーブ枠・採番の委譲・離脱・統廃合）。"""

    list_display = ("__str__", "status", "manager", "minter", "redirect", "note")
    list_filter = ("status", "naan")
    search_fields = ("shoulder", "name", "note")
    readonly_fields = ("shoulder", "naan")  # 名前空間は作り直さない

    def has_delete_permission(self, request, obj=None):
        # **shoulder は消さない**（名前空間の再利用は NR 違反）。
        return False


@admin.register(Client)
class ClientAdmin(ApplicationAdmin):
    """**同一 shoulder に複数のクライアントが並ぶのは正常**（鍵を共有しないため）。
    どれを失効させるかは `label` で見分ける。"""

    list_display = (
        "label",
        "manager",
        "shoulder",
        "authority",
        "allowed_scopes",
        "active",
        "expires_at",
    )
    list_filter = ("authority", "active", "naan", "allowed_scopes")
    search_fields = ("label", "client_id", "name")


@admin.register(Ark)
class ArkAdmin(admin.ModelAdmin):
    list_display = ("ark", "title", "url", "shoulder", "created_at", "created_by")
    list_filter = ("naan", "shoulder__status", "shoulder")
    search_fields = ("ark", "url", "title", "created_by")
    readonly_fields = ("ark", "naan", "shoulder", "assigned_name", "created_at", "updated_at")
    date_hierarchy = "created_at"

    def has_delete_permission(self, request, obj=None):
        # **ARK は消さない**（解決が止まる＝識別子が壊れる）。墓碑化は url の
        # 付け替えで行う。
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("at", "action", "authority", "client_id", "target")
    list_filter = ("action", "authority")
    search_fields = ("client_id", "target")
    readonly_fields = tuple(f.name for f in AuditEvent._meta.fields)
