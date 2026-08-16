"""機関オンボーディング（1 系統で完結）。"""

from django.core.management.base import BaseCommand, CommandError

from jc2ark.ark.models import CommitmentLevel, Naan
from jc2ark.ark.onboarding import onboard


class Command(BaseCommand):
    help = "機関を登録し、shoulder と資格情報を 1 度に発行する"

    def add_arguments(self, p):
        p.add_argument("naan")
        p.add_argument("name", help="機関名（内部専用。公開しない）")
        p.add_argument("--label", default="ingest", help="資格情報の用途")
        p.add_argument("--scopes", default="ark:mint")
        p.add_argument(
            "--commitment",
            default=CommitmentLevel.PERMANENT_DYNAMIC,
            choices=[c for c, _ in CommitmentLevel.choices],
        )
        p.add_argument("--quota", type=int, default=None)

    def handle(self, *a, **o):
        naan = Naan.objects.filter(pk=o["naan"]).first()
        if naan is None:
            raise CommandError(f"NAAN {o['naan']} が登録されていない")
        r = onboard(
            naan=naan,
            name=o["name"],
            label=o["label"],
            scopes=o["scopes"],
            commitment_level=o["commitment"],
            quota_per_day=o["quota"],
        )
        self.stdout.write(self.style.SUCCESS("オンボーディング完了"))
        self.stdout.write(f"  NAAN            {naan.pk}")
        self.stdout.write(f"  機関            {r.manager.name} (id={r.manager.pk})")
        self.stdout.write(
            f"  shoulder        {r.shoulder.shoulder}   ← 内部 lookup のみが対応を持つ"
        )
        self.stdout.write(f"  commitment      {r.manager.commitment_level}")
        self.stdout.write(f"  client_id       {r.client.client_id}")
        self.stdout.write(self.style.WARNING(f"  client_secret   {r.client_secret}"))
        self.stdout.write(self.style.WARNING("  ↑ 再表示できない。紛失時は再発行のみ。"))
