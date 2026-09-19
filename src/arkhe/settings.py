"""Settings. The authentication mechanisms are not exclusive; each can be enabled on
its own.

Whatever ARKHE_AUTH lists is tried in order. During a migration, accepting both an API
key and OIDC is ordinary, so this is not a single mode.

  apikey  API keys as arklet did them, with no external dependency
  oauth2  arkhe issues its own tokens with client_credentials, again on its own
  oidc    a JWT from an external authorisation server, such as Keycloak, is verified

oauth2 is limited to client_credentials because minting is machine to machine from an
organisation's system, and nothing here needs the authorization code flow, where a
person grants a third-party application access in a browser. Where people have to sign
in, that is delegated with oidc.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Mechanism = Literal["apikey", "oauth2", "oidc"]
AdminLogin = Literal["bearer", "password", "oidc", "proxy"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARKHE_", env_file=".env", extra="ignore")

    # ----------------------------------------------------------------- Role
    #: Start as a resolver. The minter has no resolution route and a resolver has no
    #: minting route, so they can be scaled separately and a resolver can be pointed at
    #: a read-only role and a replica.
    resolver: bool = False

    debug: bool = False
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # ---------------------------------------------------------------- DB
    database_url: str = "postgresql+psycopg://arkhe@localhost/arkhe"
    #: How many connections one process keeps open. This multiplies by the number of
    #: workers.
    #:
    #: On the defaults one process may open 5 + 10 = 15, so two resolvers with four
    #: workers each reach 120, past PostgreSQL's default max_connections of 100, or 97
    #: once the reserve is taken out: the recommended shape jams there on the defaults.
    #: Resolution is one short query, so two or three per worker is usually enough.
    db_pool_size: int = 5
    #: How many more may be opened under load. This is added to db_pool_size.
    db_max_overflow: int = 10
    #: Check a connection is alive before lending it out (SELECT 1).
    #:
    #: Turning it off roughly halves the database round trips per resolution: 1.60
    #: against 0.82 when measured over a million rows, counting xact_commit plus
    #: xact_rollback. Resolution reads one index, so the check costs a lot in relative
    #: terms.
    #:
    #: It stays on by default. Turning it off suits a deployment where the database is
    #: close and a dropped connection surfacing as an exception is acceptable. Where
    #: something in front drops connections silently, set db_pool_recycle first.
    db_pre_ping: bool = True

    #: Seconds before a connection is replaced. 0, the default, never replaces one.
    #: Behind anything that drops idle connections silently, a NAT, a load balancer or
    #: a firewall, set it below that timeout. pool_pre_ping catches it, but every catch
    #: costs a round trip.
    db_pool_recycle: int = 0

    #: The read-only connection for a resolver. Unset, database_url is used.
    read_database_url: str = ""

    # --------------------------------------------------------- Authentication
    #: NoDecode is needed because pydantic-settings would read a list from the
    #: environment as JSON. This allows ARKHE_AUTH=apikey,oidc.
    auth: Annotated[list[Mechanism], NoDecode] = Field(
        default_factory=lambda: ["apikey", "oidc"]
    )

    #: For oauth2, where we issue tokens: the signing key and how long they live.
    token_secret: str = ""
    token_ttl: int = 3600
    token_issuer: str = ""

    #: For oidc, where it is delegated: the issuer, and the audience required of an
    #: access token for the API.
    #:
    #: The aud of the ID token verified when signing in to the admin interface is always
    #: admin_client_id, so this value is not used there; mixing them breaks one of the
    #: two.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    #: Where to fetch the JWKS. Unset, it is found through the issuer's discovery
    #: document.
    oidc_jwks_url: str = ""

    # ------------------------------------------ Ways in to the admin interface
    #: A browser cannot set an Authorization header. Bearer is enough for the API, but
    #: people need another way in.
    #:
    #:   bearer    the default. No login page; for automation and curl
    #:   password  arkhe holds the usernames and passwords, so it runs without an
    #:             identity provider
    #:   oidc      arkhe acts as an OIDC client and runs the authorization code flow
    #:   proxy     an authenticating proxy in front has done the work, and its header
    #:             is trusted
    #:
    #: Where oidc or proxy is available they are better: identities stay in one place,
    #: and someone leaving is handled entirely on that side. password is for
    #: organisations without one.
    admin_login: AdminLogin = "bearer"

    #: The signing key and lifetime of the session cookie. There is no default.
    session_secret: str = ""
    session_ttl: int = 28800  # eight hours: a day of intermittent use
    #: Whether the cookie is marked Secure. Leave it true when served over HTTPS.
    session_secure: bool = True

    #: arkhe's own client registration, for admin_login=oidc.
    admin_client_id: str = ""
    admin_client_secret: str = ""
    admin_scope: str = "openid profile email"

    #: The header the identity is read from, for admin_login=proxy.
    proxy_user_header: str = "X-Forwarded-User"

    # ----------------------------------------------------------- Resolution
    #: D2: where an unknown NAAN is forwarded.
    #: How many proxies in front to trust.
    #:
    #: Anyone can set X-Forwarded-For, so by default (0) it is ignored. Recording the
    #: direct peer is better than recording a forged value: an audit log full of
    #: strings an attacker chose is the worst outcome.
    #:
    #: With n proxies in front, set n. The nth entry from the right is used; the
    #: rightmost was written by the proxy immediately in front, which can be trusted.
    #: The leftmost must never be used: the client wrote it.
    trusted_proxies: int = 0

    #: How much is logged: DEBUG, INFO or WARNING.
    log_level: str = "INFO"

    global_resolver: str = "https://n2t.net"

    #: This resolver serves reserved ARKs as well, for use inside a closed network.
    #:
    #: Reserved means not published to the world, not that nothing can look it up. An
    #: ARK minted inside a closed network is pointless if the resolver on that network
    #: cannot resolve it, and giving closed objects the same kind of identifier is the
    #: point of the design.
    #:
    #: So whether something resolves does not follow from the state of the ARK alone; it
    #: follows from which resolver is answering:
    #:
    #:   a closed resolver  serves its own reserved ARKs (1)
    #:   a public resolver  serves only what has been published (the default)
    #:
    #: The default is false. The public endpoints (?info and ??) need no credentials, so
    #: a mistake should not expose anything; a closed deployment opens it explicitly.
    resolve_unpublished: bool = False

    # -------------------------------------------------------------- Minting
    bulk_limit: int = 1000

    # ---------------------------------------------------------------- Holds
    #: The longest a hold may run. Requiring an expiry is not enough on its own: "in a
    #: year" is no different from permanent, so there is a ceiling. Extending means
    #: setting it again, which the audit log records and which makes a forgotten hold
    #: visible.
    hold_max_days: int = 90

    @field_validator("auth", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    def check(self) -> None:
        """Stop on a setting that was forgotten. There is no default secret.

        A resolver is the exception. Resolution needs no authentication and carries no
        admin interface, so nothing about authentication is required: requiring it would
        mean distributing an unused session key to every resolver.
        """
        if self.resolver:
            return
        if not self.auth:
            raise ValueError(
                "ARKHE_AUTH is empty. Choose from apikey / oauth2 / oidc."
            )
        if "oauth2" in self.auth:
            if not self.token_secret:
                raise ValueError(
                    "ARKHE_AUTH includes oauth2, so ARKHE_TOKEN_SECRET is required "
                    "(the signing key for tokens arkhe issues itself; there is no "
                    "default)."
                )
            # RFC 7518 3.2: a key for HS256 must be at least the hash length, 32
            # bytes. PyJWT only warns about a short key and carries on, so it is
            # stopped here.
            if len(self.token_secret.encode()) < 32:
                raise ValueError(
                    "ARKHE_TOKEN_SECRET is too short (32 bytes or more, RFC 7518 "
                    "§3.2). For example: "
                    "python -c \"import secrets;print(secrets.token_urlsafe(48))\""
                )
        if self.admin_login != "bearer" and not self.session_secret:
            raise ValueError(
                f"ARKHE_ADMIN_LOGIN={self.admin_login} requires ARKHE_SESSION_SECRET "
                "(the signing key for the session cookie; there is no default)."
            )
        if self.admin_login != "bearer" and len(self.session_secret.encode()) < 32:
            raise ValueError("ARKHE_SESSION_SECRET is too short (32 bytes or more).")
        if self.admin_login == "oidc":
            if not self.oidc_issuer:
                raise ValueError(
                    "ARKHE_ADMIN_LOGIN=oidc requires ARKHE_OIDC_ISSUER."
                )
            if not self.admin_client_id:
                raise ValueError(
                    "ARKHE_ADMIN_LOGIN=oidc requires ARKHE_ADMIN_CLIENT_ID "
                    "(arkhe's own client, as registered with the authorisation "
                    "server)."
                )
        if "oidc" in self.auth and not self.oidc_issuer:
            raise ValueError(
                "ARKHE_AUTH includes oidc, so ARKHE_OIDC_ISSUER is required (the "
                "authorisation server it delegates to, e.g. "
                "https://keycloak.example.org/realms/arkhe)."
            )

    @property
    def read_url(self) -> str:
        return self.read_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
