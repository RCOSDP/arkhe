# Contributing

Full guide: **<https://rcosdp.github.io/arkhe/project/contributing/>**
（日本語: <https://rcosdp.github.io/arkhe/ja/project/contributing/>）

```bash
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q
python -m ruff check src tests
```

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
