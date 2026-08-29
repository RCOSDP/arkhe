# ARK とは何か

**ARK**（Archival Resource Key）は、こういう形の永続識別子である。

```
ark:/99999/x9abc1234
    └──┬─┘ └────┬───┘
     NAAN     name
```

**HTTP と DNS の上に直接建っている。** この一点が DOI や Handle との違いを生み、
以下のほとんどはそこから出てくる。

## ARK は DOI や Handle と横並びではない

ここが誤解されやすいので、はっきり書いておく。

```mermaid
flowchart TB
    subgraph H["Handle System（CNRI / DONA）"]
        DOI["10.xxxx — DOI<br/><small>登録組織が名前空間を管理し、<br/>レコードは RA 側に置かれる</small>"]
        HDL["20.500.xxxxx — CNRI Handle<br/><small>組織が購入する prefix</small>"]
    end
    ARK["ark:/99999/…<br/><small>HTTP と DNS の上に直接。下部構造を持たない。</small>"]
```

**DOI は Handle の上に建っている。** `doi.org` は Handle のリゾルバであり、DOI は
Handle の `10.x` 名前空間の名前である。**ARK だけが別系統**で、購入したり加入したり
誰かに運用してもらったりする土台を、下に持たない。

## 効いてくる違いは 3 つ

**無償で、名前空間も無償。** NAAN は ARK Alliance から無償で交付される。支払う登録組織も、
維持する会員資格も無い。

**誰も代わりに永続性を保証しない。** DOI では登録組織が約束の一部だが、ARK では
**約束はあなたのもので、その中身も自分で述べる**。だからこそ**尋ねる手段**が用意されている。

```bash
curl "https://example.org/ark:/99999/x9abc1234??"
```

```
erc:
who: 山田太郎
what: あるデータセット
when: 2026
where: https://repo.example.ac.jp/records/1
policy: NP | NR, OP, CC | 2026 | https://example.org/policy
commitment-level: permanent-dynamic
```

何も名乗らない識別子より、**何を名乗っているかが言える識別子**のほうが価値がある。
ARK は、ロゴで匂わせるのではなく、**主張を明示して検証可能にする**。

**何でも、どの粒度でも指せる。** データセット、写本の 1 ページ、実物の標本、概念。
オンラインである必要も、**今も存在している必要もない**——対象が失われても、リゾルバは
記述を返せる（[FAIR A2](invariants.md)）。

## 設計の軸になっている約束

ARK は **NR（No Re-assignment、再割当てしない）** を宣言する。一度配った名前が、
別のものを指すようになることはない。

この 1 つの約束のために、arkhe は:

- ARK にも名前空間にも**削除を持たない**、
- `retired` にした shoulder を**元に戻さない**、
- 主キーの衝突を UPDATE に化けさせず**必ず失敗させる**、
- 統合・分割・離脱を跨いで**解決し続ける**。

それぞれを規律ではなくコードでどう守っているかは[壊さないもの](invariants.md)に書いた。

## 用語

| | |
| --- | --- |
| **NAAN** | Name Assigning Authority Number。`99999` の部分。組織に交付される |
| **shoulder** | NAAN の下位名前空間（`/x9` など）。**組織に委譲される単位** |
| **blade** | shoulder より後ろ。対象を識別する部分 |
| **inflection** | `?` や `??` の接尾。**対象へ行く**のではなく、**識別子について尋ねる** |
| **suffix passthrough** | `…/x9abc/page/3` は `…/x9abc` のレコードで解決される。子に識別子を振らなくてよい |
| **NMA** | Name Mapping Authority。その識別子を解決するとき、実際に答える主体 |
