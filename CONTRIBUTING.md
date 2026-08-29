# Contributing

Full guide: **<https://rcosdp.github.io/arkhe/project/contributing/>**
（日本語: <https://rcosdp.github.io/arkhe/ja/project/contributing/>）

```bash
uv sync --frozen --all-extras   # install exactly what the lock says
uv run pytest -q
uv run ruff check src tests
```

Changing the code? [`AGENTS.md`](AGENTS.md) carries the working procedure and the traps
actually hit during development — the same document is handed to people and to coding
agents.

Three things a review will ask:

1. **Does an invariant still hold?** Most of this design is refusals — an ARK cannot be
   deleted, a retired namespace cannot be revived, minting cannot become an update.
   Turning one of them from something the code enforces into something people are
   expected to remember will be sent back.
2. **Is the reasoning in the code?** Comments explain *why*. What the line does is
   already visible.
3. **Were migrations checked on PostgreSQL?** SQLite accepts schemas PostgreSQL
   rejects. That difference hid two real bugs during development.

Issues and pull requests are welcome, including "the documentation is wrong here" —
that is a defect like any other.
