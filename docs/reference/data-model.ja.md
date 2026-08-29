# データモデル

`Naan → Manager → Shoulder → Ark` の 1 本で全 NAAN を扱う。**個別 NAAN を持つ組織でも
shoulder を必ず使う**——使わないと NAAN ごとにモデルが分岐し、first-digit 規約が NAAN に
よって成立したりしなかったりする。

```mermaid
erDiagram
    NAAN ||--o{ MANAGER : "名前空間を委譲する"
    NAAN ||--o{ SHOULDER : "配下に持つ"
    NAAN ||--o{ ARK : "権威を持つ"
    NAAN ||--o{ CLIENT : ""

    MANAGER ||--o{ SHOULDER : "預かる"
    MANAGER |o--|| SHOULDER : "既定の採番先"
    MANAGER |o--o{ MANAGER : "統廃合で承継する"
    MANAGER ||--o{ CLIENT : ""

    SHOULDER ||--o{ ARK : "この名前空間で採番された"
    SHOULDER |o--o{ CLIENT : "固定する（任意）"

    CLIENT ||--o{ CREDENTIAL : "持つ"
    ARK ||--o{ MINT_RECEIPT : "控え"

    NAAN {
        string naan PK "N2: 文字列。099999 と 99999 は別の NAAN"
        string name
        bool   is_authoritative "D3: 未知名を 404 と言えるか"
        string redirect "権威を持たないときの委譲先"
        string na_policy "永続性宣言（NP | NR, OP, CC | 2026 | URL）"
        string minter "採番を外に委ねている場合の案内先"
    }

    MANAGER {
        int    id PK
        string naan FK
        string name "内部専用。公開しない"
        int    default_shoulder_id FK "shoulder 省略時の採番先"
        string commitment_level "NLM の permanence ratings"
        int    quota_per_day "R3: null は無制限"
        bool   active
        int    succeeded_by_id FK "承継先。識別子は壊さない"
    }

    SHOULDER {
        int    id PK
        string shoulder "例 /x9"
        string naan FK
        int    manager_id FK "null は組織未割当"
        string redirect "N2T: 解決の委譲（$id / ${blade} / 303）"
        string minter "N2T: 採番の委譲先"
        string status "active / reserved / delegated / retired"
        string note
    }

    ARK {
        string ark PK "naan/name。**削除しない**"
        string naan FK
        int    shoulder_id FK
        string assigned_name
        string url "空なら記述を返す（D6）"
        string commitment "この対象への約束"
        string metadata
        string who "ERC"
        string what_title "ERC: title 列"
        string when "ERC"
        string created_by "R2: 監査証跡"
        string updated_by
    }

    CLIENT {
        int    id PK
        string client_id UK "外部に見せる識別子。OIDC の azp と突き合わせる"
        string naan FK
        int    manager_id FK
        string subject_type "machine / person"
        string authority "system / naan / manager"
        int    shoulder_id FK "1 つに固定する（任意）"
        string allowed_scopes "ark:mint ark:update ..."
        bool   active "無効化でトークンが即座に効かなくなる"
        date   expires_at "authority=naan では必須"
    }

    CREDENTIAL {
        int    id PK
        int    client_pk FK
        string kind "api_key / client_secret / password"
        string prefix "照合を O(1) にする前置き。秘密ではない"
        string hashed "Argon2。**平文は保存しない**"
        bool   active "失効させても行は消さない"
        int    failed_attempts "総当たり対策"
        date   locked_until
    }

    MINT_RECEIPT {
        int    id PK
        string client_id "主体ごとに独立"
        string request_id "F4: 冪等鍵"
        string ark FK
    }

    AUDIT_EVENT {
        int    id PK
        date   at
        string client_id
        string authority
        string action "mint / update / succeed / depart ..."
        string target
        json   detail
    }
```

`AUDIT_EVENT` は他の表と外部キーで結ばない。**記録は対象が消えても残るべき**もので、
参照整合性で縛ると「消せないから記録も消す」という逆の力が働く。

## 図に描けないこと

ER 図は形しか示さない。**arkhe の設計の中身は制約のほうにある。**

| | |
| --- | --- |
| **ARK は削除できない** | 行を消すと解決が止まる＝識別子が壊れる。`before_delete` で拒否する。対象が失われたら tombstone にするか `url` を空にして記述を返す |
| **shoulder も削除できない** | 乱数割当が同じ文字列を再び当てうる＝NR 違反の芽。`status=retired` にする |
| **retired からは戻せない** | 引退した名前空間の再開は、その間に外部が同じ名前を使った可能性を否定できない |
| **採番は UPDATE に化けない** | 主キー衝突は必ず失敗させる。arklet で最重大の欠陥がこれだった |
| **到達範囲は登録属性** | `authority` / `manager_id` / `shoulder_id` / `allowed_scopes` はクライアント登録の属性で、リクエストやトークン要求では広がらない |
| **人と機械を分ける** | `subject_type=machine` は外部ログインで名乗れず、`person` は API キーを持てない |
| **循環参照** | `manager.default_shoulder_id ⇄ shoulder.manager_id`。PostgreSQL は CREATE TABLE の時点で参照先を要求するので、`use_alter` で後付けにしてある |

## 容量について

**子リソースは採番しない。** `ark:/99999/x9abc/page/3` のような深い参照は suffix
passthrough が賄うので、**1 レコード 1 採番**で足りる。ここが容量設計でいちばん効く。
