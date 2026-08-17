"""DRF シリアライザ。OpenAPI のスキーマもここから生成される。"""

from __future__ import annotations

from rest_framework import serializers

from .models import Ark

#: 呼び出し側が設定できる項目。**`shoulder` はここに無い**——クライアントから引く。
WRITABLE = (
    "url",
    "title",
    "type",
    "identifier",
    "format",
    "relation",
    "source",
    "commitment",
    "metadata",
    "who",
    "when",
)


class ArkOutSerializer(serializers.ModelSerializer):
    ark = serializers.SerializerMethodField()

    class Meta:
        model = Ark
        fields = ("ark", *WRITABLE, "created_at", "updated_at")

    def get_ark(self, obj) -> str:
        return f"ark:/{obj.pk}"


class MintSerializer(serializers.Serializer):
    """採番の入力。

    **`shoulder` は任意。** 省略すると機関の `default_shoulder` が使われる。
    指定した場合も**範囲を広げる手段にはならない**（登録された到達範囲内かを
    検証するだけ）。`naan` は受け取らない——クライアントが決めるものだから。
    """

    shoulder = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField(required=False, allow_blank=True, default="")
    title = serializers.CharField(required=False, allow_blank=True, default="")
    type = serializers.CharField(required=False, allow_blank=True, default="")
    identifier = serializers.CharField(required=False, allow_blank=True, default="")
    format = serializers.CharField(required=False, allow_blank=True, default="")
    relation = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.CharField(required=False, allow_blank=True, default="")
    commitment = serializers.CharField(required=False, allow_blank=True, default="")
    metadata = serializers.CharField(required=False, allow_blank=True, default="")
    who = serializers.CharField(required=False, allow_blank=True, default="")
    when = serializers.CharField(required=False, allow_blank=True, default="")

    def fields_for_mint(self) -> dict:
        d = dict(self.validated_data)
        d.pop("shoulder", None)
        return d


class BulkMintSerializer(serializers.Serializer):
    data = MintSerializer(many=True)


class UpdateSerializer(serializers.Serializer):
    ark = serializers.CharField()
    url = serializers.URLField(required=False, allow_blank=True)
    title = serializers.CharField(required=False, allow_blank=True)
    type = serializers.CharField(required=False, allow_blank=True)
    identifier = serializers.CharField(required=False, allow_blank=True)
    format = serializers.CharField(required=False, allow_blank=True)
    relation = serializers.CharField(required=False, allow_blank=True)
    source = serializers.CharField(required=False, allow_blank=True)
    commitment = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.CharField(required=False, allow_blank=True)
    who = serializers.CharField(required=False, allow_blank=True)
    when = serializers.CharField(required=False, allow_blank=True)


class BulkUpdateSerializer(serializers.Serializer):
    data = UpdateSerializer(many=True)


class TombstoneSerializer(serializers.Serializer):
    """墓碑化の入力。

    **ARK は削除できない**（`NR` を宣言している）。消せるのは対象への到達性だけで、
    識別子とメタデータは残る。`url` を渡せばそこへ、渡さなければ**リゾルバ自身が
    記述を返す**（FAIR A2。物理オブジェクトと同じ経路）。
    """

    ark = serializers.CharField()
    url = serializers.URLField(required=False, allow_blank=True, default="")
    commitment = serializers.CharField(required=False, allow_blank=True, default="")


class BulkQuerySerializer(serializers.Serializer):
    data = serializers.ListField(child=serializers.CharField(), allow_empty=False)
