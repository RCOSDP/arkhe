"""break-glass クライアントの発行（§10.3）。"""

from django.core.management.base import BaseCommand, CommandError

from jc2ark.ark.models import Client, Naan
from jc2ark.ark.onboarding import issue_break_glass


class Command(BaseCommand):
    help = "authority=naan の一時クライアントを発行する（平時は発行しない）"

    def add_arguments(self, p):
        p.add_argument("naan")
        p.add_argument("label", help="発行理由。必須")
        p.add_argument("--hours", type=int, default=72)
        p.add_argument("--list", action="store_true", help="有効な break-glass を棚卸しする")

    def handle(self, *a, **o):
        naan = Naan.objects.filter(pk=o["naan"]).first()
        if naan is None:
            raise CommandError(f"NAAN {o['naan']} が登録されていない")
        if o["list"]:
            qs = Client.objects.filter(naan=naan, authority=Client.Authority.NAAN, active=True)
            self.stdout.write(f"有効な break-glass: {qs.count()} 件（平時は 0 であること）")
            for c in qs:
                self.stdout.write(f"  {c.client_id}  {c.label}  expires={c.expires_at}")
            return
        client, secret = issue_break_glass(naan=naan, label=o["label"], hours=o["hours"])
        self.stdout.write(self.style.SUCCESS("break-glass を発行した"))
        self.stdout.write(f"  client_id   {client.client_id}")
        self.stdout.write(self.style.WARNING(f"  secret      {secret}"))
        self.stdout.write(f"  expires_at  {client.expires_at}")
        self.stdout.write(self.style.WARNING("  ↑ Secret に常設しないこと。作業後は即失効させる。"))
