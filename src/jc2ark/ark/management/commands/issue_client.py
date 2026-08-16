"""既存の機関に**追加のクライアント**を発行する。

**同一 shoulder に対して採番する主体は複数いるのが普通**——InvenioRDM の
web-api / worker、一括投入バッチ、外部システム。**それぞれに別の資格情報を出し、
鍵を共有させない。** 共有すると (1) どれが採番したか追えない、(2) 1 つ漏れたら
全部を失効させるしかない、(3) 用途ごとに scope を絞れない。
"""

from django.core.management.base import BaseCommand, CommandError

from jc2ark.ark.models import Manager, Shoulder
from jc2ark.ark.onboarding import issue_client


class Command(BaseCommand):
    help = "既存の機関に追加のクライアント資格情報を発行する（鍵は共有しない）"

    def add_arguments(self, p):
        p.add_argument("manager", help="機関名（内部名）または id")
        p.add_argument("label", help="用途。有効なものは (機関, label) で一意")
        p.add_argument("--scopes", default="ark:mint")
        p.add_argument(
            "--shoulder", default=None, help="この shoulder に固定する（既定は機関の全 shoulder）"
        )
        p.add_argument("--list", action="store_true", help="その機関の有効なクライアントを一覧する")

    def handle(self, *a, **o):
        key = o["manager"]
        m = Manager.objects.filter(pk=key).first() if key.isdigit() else None
        m = m or Manager.objects.filter(name=key).first()
        if m is None:
            raise CommandError(f"機関 {key!r} が見つからない")

        if o["list"]:
            self.stdout.write(f"{m.name} の有効なクライアント:")
            for c in m.clients.filter(active=True):
                sh = c.shoulder.shoulder if c.shoulder_id else "(機関の全 shoulder)"
                self.stdout.write(
                    f"  {c.label:<20} {c.client_id}  scopes={c.allowed_scopes}  shoulder={sh}"
                )
            return

        shoulder = None
        if o["shoulder"]:
            shoulder = Shoulder.objects.filter(
                naan=m.naan, shoulder=o["shoulder"], manager=m
            ).first()
            if shoulder is None:
                raise CommandError(f"shoulder {o['shoulder']} はこの機関のものではない")

        client, secret = issue_client(
            manager=m, label=o["label"], scopes=o["scopes"], shoulder=shoulder
        )
        self.stdout.write(self.style.SUCCESS(f"{m.name} に追加クライアントを発行した"))
        self.stdout.write(f"  label         {client.label}")
        self.stdout.write(
            f"  shoulder      {shoulder.shoulder if shoulder else '(機関の全 shoulder)'}"
        )
        self.stdout.write(f"  scopes        {client.allowed_scopes}")
        self.stdout.write(f"  client_id     {client.client_id}")
        self.stdout.write(self.style.WARNING(f"  client_secret {secret}"))
        self.stdout.write(
            self.style.WARNING("  ↑ 再表示できない。**他のクライアントと共有しないこと。**")
        )
