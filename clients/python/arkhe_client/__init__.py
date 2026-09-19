"""arkhe-client: talk to an arkhe minter and resolver from Python.

    from arkhe_client import Arkhe, Resolver

    with Arkhe("https://mint.example.org", token="...") as arkhe:
        ark = arkhe.mint(url="https://repo.example.ac.jp/records/42", title="A dataset")

    with Resolver("https://ark.example.org") as resolver:
        print(resolver.resolve(ark.ark).target)

The version here is the library's own. It does not follow the server's: the API is what
both sides agree on, and this client works with any arkhe that still serves it.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .client import Arkhe, new_request_id
from .errors import (
    ArkheError,
    BadRequest,
    Conflict,
    Delegated,
    Forbidden,
    NotFound,
    ServerError,
    Throttled,
    TransportError,
    Unauthorized,
)
from .models import Ark, BulkMint, Withdrawn
from .resolver import Resolution, Resolver

__all__ = [
    "Ark",
    "ArkheError",
    "Arkhe",
    "BadRequest",
    "BulkMint",
    "Conflict",
    "Delegated",
    "Forbidden",
    "NotFound",
    "Resolution",
    "Resolver",
    "ServerError",
    "Throttled",
    "TransportError",
    "Unauthorized",
    "Withdrawn",
    "new_request_id",
]
