---
name: chaos
description: kind クラスタの arkhe に Chaos Mesh で障害を注入し、可用性を測る。「カオステスト」「障害試験」「落としてみて」のときに使う。
---

# 壊して確かめる

**表に「落ちても続く」と書いたなら、落として確かめる。** 書いたまま試していなかった
ところに、実際に穴があった（`/readyz` が**読まない DB** を見ていた）。

## 先に確かめること

1. **どの版が動いているか。** クラスタは古いことがある——`kubectl exec … python -c
   "import importlib.metadata as m; print(m.version('arkhe'))"`。**直した修正を試すなら、
   焼き直して入れる**（下記）。
2. **共用しているものは何か。** `postgres` は InvenioRDM や Keycloak と共用のことが
   ある。**壊してよいか先に確かめる**——arkhe の pod と arkhe→DB の通信だけなら安全。

## 新しいイメージを入れる

**以下の `jc2`（クラスタ名・名前空間）はこの環境のもの。** 置き場ごとに違うので、
自分のものに読み替える。

```bash
docker build -f arkhe/Dockerfile -t arkhe:chaos arkhe
kind load docker-image arkhe:chaos --name jc2
# 移行を先に流す（版が上がっていれば必須）
kubectl run … --image=arkhe:chaos --command -- sh -c 'alembic upgrade head'
kubectl set image -n jc2 deploy/arkhe-resolver arkhe=arkhe:chaos   # minter / admin も
```

## 測りながら壊す

**壊す前にプローブを回し始める。** 後から見ても、途切れの長さは分からない。

```sh
while :; do echo "$(date +%s) $(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$URL")"; sleep 0.2; done
```

| 実験 | 期待 | 実測（0.10.0・2 レプリカ） |
| --- | --- | --- |
| resolver を 1 つ殺す | 途切れない | **212/212 が 302** |
| resolver を全滅 | 数十秒で復帰 | **約 12 秒** |
| resolver → DB を遮断 | 自分を Service から外す | **16 秒で 0/1・endpoints 0**、明けて自動復帰 |

## 罠

**`kubectl apply` は期限切れの chaos を再実行しない。** 同じ名前のオブジェクトが
残っていると、`apply` が no-op になり**何も起きていないのに観察してしまう**
（実際にそれで「効いていない」と誤読した）。`delete` してから `create` する。

**`--rm` のコンテナを `stop` すると消える。** 主系を止めて戻す試験は、
`--rm` を付けずに作る。

**プローブが Service 経由なら、`000` は「宛先が無い」。** pod が自分を外した結果
かもしれないので、**`kubectl get endpoints` と pod の Ready を必ず併せて見る**。

## 片付け

```bash
kubectl delete networkchaos,podchaos -n jc2 --all
kubectl delete pod -n jc2 arkhe-probe
```
