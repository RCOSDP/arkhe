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
    list_display = ("naan", "name", "is_authoritative", "redirect", "na_policy")
    list_filter = ("is_authoritative",)
    search_fields = ("naan", "name")


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ("name", "naan", "default_shoulder", "commitment_level", "active")
    list_filter = ("naan", "commitment_level", "active")
    search_fields = ("name",)


@admin.register(Shoulder)
class ShoulderAdmin(admin.ModelAdmin):
    list_display = ("__str__", "manager", "redirect", "minter")
    list_filter = ("naan",)
    search_fields = ("shoulder", "name")


@admin.register(Client)
class ClientAdmin(ApplicationAdmin):
    list_display = ("label", "manager", "authority", "allowed_scopes", "active", "expires_at")
    list_filter = ("authority", "active", "naan")
    search_fields = ("label", "client_id")


@admin.register(Ark)
class ArkAdmin(admin.ModelAdmin):
    list_display = ("ark", "url", "shoulder", "created_at", "created_by")
    list_filter = ("naan", "shoulder")
    search_fields = ("ark", "url", "title")
    readonly_fields = ("ark", "naan", "shoulder", "assigned_name", "created_at", "updated_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("at", "action", "authority", "client_id", "target")
    list_filter = ("action", "authority")
    search_fields = ("client_id", "target")
    readonly_fields = tuple(f.name for f in AuditEvent._meta.fields)
