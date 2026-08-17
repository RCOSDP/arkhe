"""機関の離脱（`ark_succession.md` §5）。組織は存続するが JC2 を離れる。"""

from django.core.management.base import BaseCommand, CommandError

from jc2ark.ark.models import Manager
from jc2ark.ark.onboarding import depart


class Command(BaseCommand):
    help = "機関の離脱。新規採番を止め、解決は続ける"

    def add_arguments(self, p):
        p.add_argument("manager")
        p.add_argument(
            "--resolver",
            default="",
            help="転送先を機関のリゾルバに一括で向け直す。"
            "例 'https://repo.univ.ac.jp/ark/${blade}'（推奨）",
        )
        p.add_argument(
            "--keep-update",
            default="",
            help="更新権限だけのクライアントを残す（--resolver を使わない場合）",
        )

    def handle(self, *a, **o):
        m = Manager.objects.filter(name=o["manager"]).first()
        if m is None:
            raise CommandError(f"機関 {o['manager']!r} が見つからない")
        if not o["resolver"] and not o["keep_update"]:
            self.stdout.write(
                self.style.WARNING(
                    "  ⚠ --resolver も --keep-update も無い場合、以後**誰も転送先を"
                    "更新できません**。リンク切れになったら url を空にして記述を返す形"
                    "（descriptive-only）に降格させてください。"
                )
            )
        r = depart(manager=m, resolver_template=o["resolver"], keep_update_label=o["keep_update"])
        self.stdout.write(self.style.SUCCESS(f"{m.name} の離脱を記録した"))
        self.stdout.write(f"  新規採番を停止した shoulder: {', '.join(r['shoulders']) or '(なし)'}")
        self.stdout.write(f"  転送先を書き換えた ARK      : {r['urls_rewritten']} 件")
        self.stdout.write(f"  失効した資格情報            : {r['revoked']} 件")
        if r["update_client"]:
            c, sec = r["update_client"]
            self.stdout.write(f"  更新用クライアント          : {c.client_id}")
            self.stdout.write(self.style.WARNING(f"  secret                      : {sec}"))
        self.stdout.write("  **解決は NII が続ける。これは離脱しても消えない義務（NR）。**")
