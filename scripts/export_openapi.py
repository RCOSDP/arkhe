"""OpenAPI をドキュメントへ書き出す。**API 仕様を手で二重に書かないため。**

minter と resolver は役割ごとに口が違うので、両方を出す。
mkdocs のビルド前に走らせる（CI がそうしている）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "assets"


def dump(name: str, **env: str) -> None:
    os.environ.update(env)
    for mod in [m for m in list(sys.modules) if m.startswith("arkhe")]:
        del sys.modules[mod]
    from arkhe.app import create_app
    from arkhe.settings import Settings

    spec = create_app(Settings()).openapi()
    path = OUT / f"openapi-{name}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  {path.name}: {len(spec['paths'])} paths")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    dump("minter", ARKHE_RESOLVER="0", ARKHE_AUTH="apikey,oauth2",
         ARKHE_TOKEN_SECRET="x" * 48, ARKHE_ADMIN_LOGIN="bearer")
    dump("resolver", ARKHE_RESOLVER="1", ARKHE_AUTH="apikey")
