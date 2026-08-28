# Data model

One chain — `Naan → Manager → Shoulder → Ark` — carries every NAAN. **Even an
institution with a NAAN of its own goes through a shoulder.** Skip that and the model
forks per NAAN, and the first-digit convention holds for some NAANs and not others.

```mermaid
erDiagram
    NAAN ||--o{ MANAGER : "delegates a namespace to"
    NAAN ||--o{ SHOULDER : "contains"
    NAAN ||--o{ ARK : "is authoritative for"
    NAAN ||--o{ CLIENT : ""

    MANAGER ||--o{ SHOULDER : "holds"
    MANAGER |o--|| SHOULDER : "default mint target"
    MANAGER |o--o{ MANAGER : "is succeeded by"
    MANAGER ||--o{ CLIENT : ""

    SHOULDER ||--o{ ARK : "minted in"
    SHOULDER |o--o{ CLIENT : "pinned to (optional)"

    CLIENT ||--o{ CREDENTIAL : "holds"
    ARK ||--o{ MINT_RECEIPT : "receipt for"

    NAAN {
        string naan PK "N2: a string. 099999 is not 99999"
        string name
        bool   is_authoritative "D3: may answer 404 for an unknown name"
        string redirect "where to forward when not authoritative"
        string na_policy "persistence statement"
        string minter "where minting happens, if elsewhere"
    }

    MANAGER {
        int    id PK
        string naan FK
        string name "internal only; never published"
        int    default_shoulder_id FK "used when shoulder is omitted"
        string commitment_level "NLM permanence ratings"
        int    quota_per_day "R3: null means no limit"
        bool   active
        int    succeeded_by_id FK "successor; identifiers survive"
    }

    SHOULDER {
        int    id PK
        string shoulder "e.g. /x9"
        string naan FK
        int    manager_id FK "null: no institution yet"
        string redirect "N2T: delegated resolution"
        string minter "N2T: delegated minting"
        string status "active / reserved / delegated / retired"
        string note
    }

    ARK {
        string ark PK "naan/name. never deleted"
        string naan FK
        int    shoulder_id FK
        string assigned_name
        string url "empty: return a description (D6)"
        string commitment "commitment to this object"
        string metadata
        string who "ERC"
        string what_title "ERC: title 列"
        string when "ERC"
        string created_by "R2: audit trail"
        string updated_by
    }

    CLIENT {
        int    id PK
        string client_id UK "public identifier; matched against OIDC azp"
        string naan FK
        int    manager_id FK
        string subject_type "machine / person"
        string authority "system / naan / manager"
        int    shoulder_id FK "pin to a single shoulder (optional)"
        string allowed_scopes "ark:mint ark:update ..."
        bool   active "deactivating kills tokens at once"
        date   expires_at "required when authority=naan"
    }

    CREDENTIAL {
        int    id PK
        int    client_pk FK
        string kind "api_key / client_secret / password"
        string prefix "lookup prefix; not a secret"
        string hashed "Argon2; the clear text is never stored"
        bool   active "revoked rows are kept"
        int    failed_attempts "brute-force guard"
        date   locked_until
    }

    MINT_RECEIPT {
        int    id PK
        string client_id "scoped to one principal"
        string request_id "F4: idempotency key"
        string ark FK
    }

    AUDIT_EVENT {
        int    id PK
        date   at
        string client_id
        string authority
        string action "mint / update / succeed / depart …"
        string target
        json   detail
    }
```

`AUDIT_EVENT` has no foreign keys into the rest. **A record should outlive what it
describes**, and referential integrity would push the other way: it makes deleting the
record the easy way out.

## What the diagram cannot show

An ER diagram shows shape. **In arkhe the design lives in the constraints.**

| | |
| --- | --- |
| **An ARK is never deleted** | Deleting the row stops resolution — the identifier breaks. `before_delete` refuses. When a target is lost you tombstone it, or empty `url` so a description is returned |
| **A shoulder is never deleted either** | Random assignment could hand out the same string again — the seed of an NR violation. Set `status=retired` |
| **`retired` is one-way** | Reviving a retired namespace cannot rule out that something outside used the name meanwhile |
| **Minting never becomes an update** | A primary key collision must fail. This was the worst defect in arklet |
| **Reach is a registration attribute** | `authority`, `manager_id`, `shoulder_id` and `allowed_scopes` come from the client registration; no request or token grant widens them |
| **People and machines are separate** | `machine` subjects cannot be named through external login; `person` subjects cannot hold API keys |
| **A circular reference** | `manager.default_shoulder_id ⇄ shoulder.manager_id`. PostgreSQL wants the target to exist at `CREATE TABLE`, so the constraint is added afterwards with `use_alter` |

## On capacity

**Child resources are never minted.** Suffix passthrough covers a reference of any
depth — `ark:/99999/x9abc/page/3` needs no row of its own — so **one record per
minting** is enough. Nothing else matters as much for capacity.
