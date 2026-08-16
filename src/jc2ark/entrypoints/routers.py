"""SC2: resolver は read replica、minter はプライマリを読む。

`ark_scale_availability.md` §7。**解決（読み取り）と採番（書き込み）は非対称**で、
解決は圧倒的に多く、止まると世界中の参照が切れる。resolver をレプリカに向けて
水平に増やせるようにしておく。

第1期はレプリカを立てない（決定レジスタ F3）が、**ルータだけ先に入れておけば
後から向き先を変えるだけで済む**。`replica` が未設定なら `default` に落ちる。
"""

from django.conf import settings

REPLICA = "replica"


def _has_replica() -> bool:
    return REPLICA in settings.DATABASES


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        # RESOLVER=1 のプロセスだけレプリカを読む。minter は自分の書き込みを
        # 読み返すのでプライマリのまま（read-your-writes）。
        if getattr(settings, "IS_RESOLVER", False) and _has_replica():
            return REPLICA
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"
