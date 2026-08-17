"""統廃合の承継（`ark_succession.md`）。"""

from django.core.management.base import BaseCommand, CommandError

from jc2ark.ark.models import Manager
from jc2ark.ark.onboarding import succeed


class Command(BaseCommand):
    help = "旧機関の名前空間を承継先に移す（識別子は壊さない）"

    def add_arguments(self, p):
        p.add_argument("predecessor", help="承継元の機関名")
        p.add_argument("successor", help="承継先の機関名")
        p.add_argument(
            "--retire",
            action="store_true",
            help="移した shoulder の新規採番を止める（既存 ARK は解決し続ける）",
        )

    def handle(self, *a, **o):
        def find(name):
            m = Manager.objects.filter(name=name).first()
            if m is None:
                raise CommandError(f"機関 {name!r} が見つからない")
            return m

        pre, suc = find(o["predecessor"]), find(o["successor"])
        try:
            r = succeed(predecessor=pre, successor=suc, retire_shoulders=o["retire"])
        except ValueError as e:
            raise CommandError(str(e)) from None
        self.stdout.write(self.style.SUCCESS(f"{pre.name} → {suc.name} の承継を記録した"))
        self.stdout.write(f"  移した shoulder : {', '.join(r['shoulders']) or '(なし)'}")
        self.stdout.write(f"  失効した資格情報: {r['revoked']} 件")
        self.stdout.write("  **既存 ARK は 1 本も変わらない。解決先も変わらない。**")
        if not o["retire"]:
            self.stdout.write("  （--retire を付けると、移した shoulder の新規採番を止める）")
