"""The admin interface: screens for operations, not row editing.

The screens call domain.admin_ops and domain.minting rather than touching the database,
so they go through the same functions as the CLI and cannot break an invariant.

What is shown is narrowed by the principal's tier, system, naan or manager. Display and
authorisation use the same decision: keeping them apart leaves the hole where the button
is hidden but the URL still works.

There is a module per screen. The import order does not matter, since they all register
on the same router from _common, except that arks has /arks/{ark:path}, so more specific
routes have to be registered first.
"""

# Importing these registers them on the router. See the note above about order.
from arkhe.api.admin import (  # noqa: E402,F401
    arks,
    audit,
    clients,
    ledger,
    minting,
    signin,
    stats,
)
from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    NeedsLogin,
    admin_principal,
    router,
)

__all__ = ["PAGE", "AdminPrincipal", "NeedsLogin", "admin_principal", "router"]
