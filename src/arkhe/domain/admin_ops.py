"""The administrative operations. The screens and the CLI both call them.

This is why the admin interface is not row editing. What means something in arkhe is an
operation: onboarding an organisation, retiring a shoulder, setting up a delegation.
Editing fields is not. With row editing, things like these happen simply because a
screen allows them:

  - moving Shoulder.status from retired back to active, reopening a retired namespace,
    which is how an NR violation starts
  - rewriting Ark.ark, turning it into a different identifier
  - clearing Naan.is_authoritative while leaving redirect empty, so nothing resolves

Defined as operations, none of them can even be expressed.

Each operation states who may call it. The decision uses the principal's three tiers,
system, naan and manager, and the screens show or hide controls by the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from arkhe import errors
from arkhe.arkspec.naming import compact_ark
from arkhe.auth import apikey, oauth2
from arkhe.auth import password as pw
from arkhe.auth.errors import Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    ArkChange,
    Authority,
    Client,
    CommitmentLevel,
    Credential,
    CredentialKind,
    Manager,
    MintReceipt,
    Naan,
    Shoulder,
    ShoulderStatus,
    Subject,
    WithdrawnName,
    sanctioned_purge,
)
from arkhe.domain.authz import Conflict, Invalid, NotFound, audit


def _require_system(p: Principal) -> None:
    if not p.is_system:
        raise Forbidden("only the system administrator may do this")


def _require_naan(p: Principal, naan: str) -> None:
    """Whether it reaches that NAAN. The system administrator reaches every one."""
    if not p.reaches_naan(naan):
        raise Forbidden(f"NAAN {naan} is out of this principal's reach")


def require_manager(session: Session, p: Principal, manager: Manager) -> None:
    """Whether it reaches that organisation: everything under the NAAN at NAAN level
    and above, its own organisation at manager level.

    The name is public because the screens call it too. A screen writing its own decision
    would leave the hole where the button is hidden but the POST still works.
    """
    _require_naan(p, manager.naan)
    if p.is_naan_wide:
        return
    if p.manager_id != manager.id:
        raise Forbidden("this organisation is out of this principal's reach")


# --------------------------------------------------------------------- NAAN


def create_naan(session: Session, p: Principal, *, naan: str, name: str, **fields) -> Naan:
    """Only the system administrator registers a NAAN. It is an operation of the side
    that hands namespaces out."""
    _require_system(p)
    if session.get(Naan, naan) is not None:
        raise Invalid({"naan": f"NAAN {naan} is already registered"})
    obj = Naan(naan=naan, name=name, **fields)
    session.add(obj)
    audit(session, p, "create_naan", naan)
    return obj


def set_na_policy(session: Session, p: Principal, *, naan: str, policy: str) -> Naan:
    """Set the persistence statement, the NAA policy.

    ARK takes the position that persistence is a promise rather than a property, so
    nobody claims a guarantee; they state which level of promise they are making.

    Only a principal holding the NAAN may change it. The statement covers every
    organisation under that NAAN, so one organisation's administrator must not rewrite it
    for the others. What an organisation says about itself is set_commitment: the NAA
    policy is declared by the side handing the namespace out, the commitment by the side
    receiving it, which is ARK's delegation written down.
    """
    obj = session.get(Naan, naan)
    if obj is None:
        raise NotFound({"naan": naan})
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("declaring the NAA policy needs NAAN level or above")
    obj.na_policy = policy
    audit(session, p, "set_na_policy", naan, policy=policy)
    return obj


# ------------------------------------------------------------------ Manager


def _commitment(level: str) -> str:
    """Check the commitment vocabulary.

    An unknown word is refused. The value is published as it stands by ??, so a typo
    that got through would announce, in the organisation's name, a level it never
    stated.
    """
    try:
        return CommitmentLevel(level).value
    except ValueError:
        raise Invalid(
            {
                "commitment_level": f"{level!r} is not a known level",
                "choices": [c.value for c in CommitmentLevel],
            }
        ) from None


def set_commitment(session: Session, p: Principal, *, manager_id: int, level: str) -> Manager:
    """Restate an organisation's commitment level.

    It exists so that nobody is left on the default. Without it, every organisation runs
    as permanent-dynamic and ?? publishes a software default as if the organisation had
    declared it. Presenting something undeclared as a declaration is worse than saying
    nothing.

    Lowering the level is a legitimate operation. Restating it honestly beats keeping a
    promise that cannot be kept, and it keeps ?? worth asking.
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide and manager.id != p.manager_id:
        raise Forbidden("only your own organisation's commitment can be changed")
    before = manager.commitment_level
    manager.commitment_level = _commitment(level)
    audit(
        session, p, "set_commitment", str(manager_id),
        before=before, after=manager.commitment_level,
    )
    return manager


#: The authentication mechanisms, using the same vocabulary as settings.ARKHE_AUTH; a
#: separate copy would drift.
MECHANISMS = ("apikey", "oauth2", "oidc")


def _narrow(outer: str, inner: str) -> str:
    """The inner rule narrows the outer one and never widens it.

    Both are space separated, and empty means no restriction, so an intersection with an
    empty one returns the other unchanged. Reading empty as "nothing is allowed" would
    make the default forbid everything.
    """
    if not outer:
        return inner
    if not inner:
        return outer
    return " ".join(x for x in outer.split() if x in set(inner.split()))


@dataclass(frozen=True)
class OrgPolicy:
    """The rules actually in force for an organisation: the NAAN default with the
    organisation's settings applied on top."""

    allowed_auth: str
    may_self_register: bool
    max_scopes: str


def policy_for(naan: Naan | None, manager: Manager | None) -> OrgPolicy:
    """The rule belongs to the NAAN; an organisation records the exception. It can
    narrow but never widen.

    The default lives on the NAAN because applying it per organisation does not scale.
    may_self_register is an and: without the NAAN allowing it, no organisation setting
    can.
    """
    n_auth = naan.allowed_auth if naan else ""
    n_self = naan.may_self_register if naan else True
    n_max = naan.max_scopes if naan else ""
    if manager is None:
        return OrgPolicy(n_auth, n_self, n_max)
    return OrgPolicy(
        _narrow(n_auth, manager.allowed_auth),
        n_self and manager.may_self_register,
        _narrow(n_max, manager.max_scopes),
    )


def allowed_auth_for(
    naan: Naan | None, manager: Manager | None, enabled: tuple[str, ...] | list[str]
) -> list[str]:
    """The mechanisms actually usable: the rules intersected with what the deployment
    has enabled."""
    allowed = policy_for(naan, manager).allowed_auth
    if not allowed:
        return list(enabled)
    return [m for m in enabled if m in set(allowed.split())]


def set_naan_policy(
    session: Session,
    p: Principal,
    *,
    naan: str,
    mechanisms: list[str] | None = None,
    may_self_register: bool | None = None,
    max_scopes: list[str] | None = None,
) -> Naan:
    """The rules for this namespace: the default for every organisation under it.

    An organisation may narrow them and nothing more. The rule lives here because
    applying it per organisation does not scale.
    """
    from arkhe.domain.authz import SCOPES

    obj = session.get(Naan, naan)
    if obj is None:
        raise NotFound({"naan": naan})
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("setting the rules for a namespace needs NAAN level or above")

    before = {"allowed_auth": obj.allowed_auth, "may_self_register": obj.may_self_register,
              "max_scopes": obj.max_scopes}
    if mechanisms is not None:
        unknown = [m for m in mechanisms if m not in MECHANISMS]
        if unknown:
            raise Invalid({"mechanisms": f"unknown mechanism: {', '.join(unknown)}"})
        obj.allowed_auth = " ".join(m for m in MECHANISMS if m in mechanisms)
    if may_self_register is not None:
        obj.may_self_register = may_self_register
    if max_scopes is not None:
        unknown = [x for x in max_scopes if x not in SCOPES]
        if unknown:
            raise Invalid({"max_scopes": f"unknown scope: {', '.join(unknown)}"})
        obj.max_scopes = " ".join(x for x in SCOPES if x in max_scopes)

    audit(session, p, "set_naan_policy", naan, before=before,
          after={"allowed_auth": obj.allowed_auth,
                 "may_self_register": obj.may_self_register,
                 "max_scopes": obj.max_scopes})
    return obj


def set_org_policy(
    session: Session,
    p: Principal,
    *,
    manager_id: int,
    mechanisms: list[str] | None = None,
    may_self_register: bool | None = None,
    max_scopes: list[str] | None = None,
) -> Manager:
    """Decide what an organisation is trusted with and what is limited. The
    organisation cannot change it.

    A limit the limited party can lift is not a limit, as with set_quota. Anything left
    as None is untouched, and an empty list means no restriction.

      mechanisms         how principals get in (apikey, oauth2, oidc)
      may_self_register  whether the organisation may register principals itself
      max_scopes         the ceiling on the scopes its principals may hold
    """
    from arkhe.domain.authz import SCOPES

    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide:
        raise Forbidden("changing an organisation's restrictions needs NAAN level or above")

    before = {
        "allowed_auth": manager.allowed_auth,
        "may_self_register": manager.may_self_register,
        "max_scopes": manager.max_scopes,
    }
    if mechanisms is not None:
        unknown = [m for m in mechanisms if m not in MECHANISMS]
        if unknown:
            raise Invalid({"mechanisms": f"unknown mechanism: {', '.join(unknown)}",
                           "choices": list(MECHANISMS)})
        manager.allowed_auth = " ".join(m for m in MECHANISMS if m in mechanisms)
    if may_self_register is not None:
        manager.may_self_register = may_self_register
    if max_scopes is not None:
        unknown = [x for x in max_scopes if x not in SCOPES]
        if unknown:
            raise Invalid({"max_scopes": f"unknown scope: {', '.join(unknown)}",
                           "choices": list(SCOPES)})
        manager.max_scopes = " ".join(x for x in SCOPES if x in max_scopes)

    audit(session, p, "set_org_policy", str(manager_id), before=before,
          after={"allowed_auth": manager.allowed_auth,
                 "may_self_register": manager.may_self_register,
                 "max_scopes": manager.max_scopes})
    return manager


def set_quota(
    session: Session, p: Principal, *, manager_id: int, quota_per_day: int | None
) -> Manager:
    """Change the daily minting quota. None means no limit.

    An organisation cannot change its own, which is where this differs from
    set_commitment: the quota is imposed by the side that handed out the namespace, and a
    limit the limited party can lift is not a limit.
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    _require_naan(p, manager.naan)
    if not p.is_naan_wide:
        raise Forbidden("changing the minting quota needs NAAN level or above")
    if quota_per_day is not None and quota_per_day < 0:
        raise Invalid({"quota_per_day": "a quota cannot be negative; leave it empty for no limit"})
    before = manager.quota_per_day
    manager.quota_per_day = quota_per_day
    audit(session, p, "set_quota", str(manager_id), before=before, after=quota_per_day)
    return manager


def onboard_manager(
    session: Session,
    p: Principal,
    *,
    naan: str,
    name: str,
    shoulder: str,
    commitment_level: str = "",
    quota_per_day: int | None = None,
) -> tuple[Manager, Shoulder]:
    """Onboard an organisation and delegate one namespace to it. The two always happen
    together.

    An organisation with no shoulder is an organisation that cannot mint, which is
    useless. default_shoulder is set here too; without it, minting without naming a
    shoulder fails.
    """
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("onboarding an organisation needs NAAN level or above")
    if session.get(Naan, naan) is None:
        raise NotFound({"naan": naan})
    if session.scalar(select(Manager).where(Manager.naan == naan, Manager.name == name)):
        raise Invalid({"name": f"{naan} already has an organisation called {name}"})

    manager = Manager(naan=naan, name=name)
    if commitment_level:
        manager.commitment_level = _commitment(commitment_level)
    manager.quota_per_day = quota_per_day
    session.add(manager)
    session.flush()

    sh = _add_shoulder(session, naan=naan, shoulder=shoulder, manager=manager)
    manager.default_shoulder_id = sh.id
    audit(session, p, "onboard_manager", f"{naan}{shoulder}", manager=name)
    return manager, sh


def set_succession(
    session: Session, p: Principal, *, manager_id: int, successor_id: int | None
) -> Manager:
    """Record the successor after a merger.

    Identifiers are not broken. Having declared NR, resolution continues through a change
    of custodian. The old organisation's row stays and points at the successor, so the
    lineage can be followed.
    """
    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    require_manager(session, p, manager)
    if successor_id is not None:
        succ = session.get(Manager, successor_id)
        if succ is None:
            raise NotFound({"successor": successor_id})
        if succ.id == manager.id:
            raise Invalid({"successor": "an organisation cannot succeed itself"})
        _require_naan(p, succ.naan)
    manager.succeeded_by_id = successor_id
    audit(session, p, "set_succession", str(manager_id), successor=successor_id)
    return manager


# ----------------------------------------------------------------- Shoulder


def _add_shoulder(
    session: Session,
    *,
    naan: str,
    shoulder: str,
    manager: Manager | None,
    status: str = ShoulderStatus.ACTIVE.value,
) -> Shoulder:
    if not shoulder.startswith("/"):
        shoulder = "/" + shoulder
    if session.scalar(
        select(Shoulder).where(Shoulder.naan == naan, Shoulder.shoulder == shoulder)
    ):
        raise Invalid({"shoulder": f"{naan}{shoulder} already exists"})
    sh = Shoulder(
        shoulder=shoulder,
        naan=naan,
        manager_id=manager.id if manager else None,
        status=status,
    )
    session.add(sh)
    session.flush()
    return sh


def add_shoulder(
    session: Session,
    p: Principal,
    *,
    naan: str,
    shoulder: str,
    manager_id: int | None = None,
    status: str = ShoulderStatus.ACTIVE.value,
    note: str = "",
) -> Shoulder:
    """Carve out a namespace. It needs NAAN level or above, since it belongs to the side
    handing them out.

    With status=reserved it is created held but unusable. Reserved can only be set at
    creation, because there is no transition from active back to reserved: a namespace
    that has been mintable cannot later be called unused.
    """
    _require_naan(p, naan)
    if not p.is_naan_wide:
        raise Forbidden("adding a shoulder needs NAAN level or above")
    manager = session.get(Manager, manager_id) if manager_id else None
    if manager_id and manager is None:
        raise NotFound({"manager": manager_id})
    if status not in (ShoulderStatus.ACTIVE, ShoulderStatus.RESERVED):
        raise Invalid({"status": "only active or reserved may be set at creation"})
    sh = _add_shoulder(
        session, naan=naan, shoulder=shoulder, manager=manager, status=status
    )
    if note:
        sh.note = note
    audit(session, p, "add_shoulder", f"{naan}{shoulder}", status=status)
    return sh


#: Some transitions can be reversed and some cannot. Moving from retired back to active
#: reopens a retired namespace, and we cannot rule out that the same name was used
#: elsewhere in the meantime, which is how an NR violation starts. So it is refused.
ALLOWED_TRANSITIONS = {
    ShoulderStatus.RESERVED: {ShoulderStatus.ACTIVE, ShoulderStatus.DELEGATED},
    ShoulderStatus.ACTIVE: {ShoulderStatus.DELEGATED, ShoulderStatus.RETIRED},
    ShoulderStatus.DELEGATED: {ShoulderStatus.ACTIVE, ShoulderStatus.RETIRED},
    ShoulderStatus.RETIRED: set(),  # there is no way back
}


def set_shoulder_status(
    session: Session,
    p: Principal,
    *,
    shoulder_id: int,
    status: str,
    minter: str = "",
    about: str = "",
    note: str = "",
) -> Shoulder:
    """Change the state of a shoulder. The transitions are bound by a table."""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise NotFound({"shoulder": shoulder_id})
    _require_naan(p, sh.naan)
    if not p.is_naan_wide:
        raise Forbidden("changing a shoulder's state needs NAAN level or above")

    cur, new = ShoulderStatus(sh.status), ShoulderStatus(status)
    if new != cur and new not in ALLOWED_TRANSITIONS[cur]:
        raise Invalid(
            {
                "status": f"{cur} to {new} is not an allowed transition",
                "reason": (
                    "there is no way back from retired: reopening a retired namespace "
                    "is how an NR violation starts"
                    if cur is ShoulderStatus.RETIRED
                    else "allowed: " + ", ".join(sorted(ALLOWED_TRANSITIONS[cur]))
                ),
            }
        )
    # A delegation needs no target. Delegating records in the ledger that we no longer
    # mint in this namespace; it does not announce where minting happens. On a closed
    # network there is nothing to announce, and forbidding such a delegation would only
    # push invented values into minter: an internal host name, or a page for people.
    #
    # With a minter, a request is pointed there with 307; with an about, it appears in
    # the body of a 403; with neither, the answer is simply that we do not mint here.
    sh.status = new.value
    if minter:
        sh.minter = minter
    if about:
        sh.about = about
    if note:
        sh.note = note
    audit(session, p, "set_shoulder_status", f"{sh.naan}{sh.shoulder}", status=new.value)
    return sh


def set_shoulder_redirect(
    session: Session, p: Principal, *, shoulder_id: int, redirect: str
) -> Shoulder:
    """Resolution delegated per shoulder, as in n2t's data model. It supports $id,
    ${blade} and a leading 303."""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise NotFound({"shoulder": shoulder_id})
    _require_naan(p, sh.naan)
    if not p.is_naan_wide:
        raise Forbidden("delegating resolution needs NAAN level or above")
    sh.redirect = redirect
    audit(session, p, "set_shoulder_redirect", f"{sh.naan}{sh.shoulder}", redirect=redirect)
    return sh


# ------------------------------------------------------------- Credentials


@dataclass
class IssuedCredential:
    """The plaintext exists only here. It is not stored, and it is shown once."""

    credential: Credential
    secret: str


def register_client(
    session: Session,
    p: Principal,
    *,
    client_id: str,
    naan: str,
    manager_id: int | None = None,
    authority: str = Authority.MANAGER.value,
    shoulder_id: int | None = None,
    scopes: str = "ark:mint",
    label: str = "",
    expires_at: datetime | None = None,
    subject_type: str = Subject.MACHINE.value,
) -> Client:
    """Register a principal. Nobody grants a wider reach than their own.

    subject_type decides which routes can be used to identify as it:

      machine  identifies with a credential, an API key or a client secret, and cannot
               sign in from outside
      person   vouched for by an external authorisation server or proxy, and holds no
               credential

    They are separate so that a header from a proxy cannot be used to become a machine
    principal. For a person, client_id holds the identifier the authorisation server
    returns, such as an email address or an eppn.
    """
    _require_naan(p, naan)
    if shoulder_id is not None:
        # A shoulder already determines the organisation. Requiring both separately
        # produces principals with only one filled in, which are refused at the door,
        # where the organisation is checked, in the confusing form of "the shoulder is
        # right but it still does not work".
        sh = session.get(Shoulder, shoulder_id)
        if sh is None or sh.naan != naan:
            raise Invalid(
                {"shoulder_id": f"shoulder {shoulder_id} does not belong to NAAN {naan}"}
            )
        if manager_id is None:
            manager_id = sh.manager_id
        elif manager_id != sh.manager_id:
            raise Invalid(
                {"shoulder_id": "the shoulder's organisation and the manager disagree"}
            )
    target = Authority(authority)
    if target is Authority.SYSTEM:
        _require_system(p)
    elif target is Authority.NAAN and not p.is_naan_wide:
        raise Forbidden("creating an authority=naan principal needs NAAN level or above")
    if not p.is_naan_wide and manager_id != p.manager_id:
        raise Forbidden("a principal cannot be created for another organisation")
    org = session.get(Manager, manager_id) if manager_id else None
    policy = policy_for(session.get(Naan, naan), org)
    # Where it is not delegated, it goes through the side handing out the namespace,
    # which decides whether an organisation may add principals itself.
    if not p.is_naan_wide and not policy.may_self_register:
        raise Forbidden(
            "this organisation may not register principals; ask the NAAN administrator"
        )
    # The ceiling applies whoever creates the principal. To make an exception, move the
    # ceiling; otherwise the ledger fills with principals above what was declared.
    if policy.max_scopes:
        over = set(scopes.split()) - set(policy.max_scopes.split())
        if over:
            raise Invalid(
                {"scopes": f"above the ceiling: {' '.join(sorted(over))}",
                 "max_scopes": policy.max_scopes}
            )
    if session.scalar(select(Client).where(Client.client_id == client_id)):
        raise Invalid({"client_id": f"{client_id} is already registered"})
    if target is Authority.NAAN and expires_at is None:
        # A break-glass principal must have an expiry: no permanent master key.
        raise Invalid({"expires_at": "an authority=naan principal needs an expiry"})

    client = Client(
        client_id=client_id,
        subject_type=Subject(subject_type).value,
        naan=naan,
        manager_id=manager_id,
        authority=target.value,
        shoulder_id=shoulder_id,
        allowed_scopes=scopes,
        label=label,
        expires_at=expires_at,
    )
    session.add(client)
    session.flush()
    audit(
        session, p, "register_client", client_id,
        authority=target.value, subject_type=subject_type,
    )
    return client


def issue_credential(
    session: Session,
    p: Principal,
    *,
    client_pk: int,
    kind: str = CredentialKind.API_KEY.value,
    label: str = "",
    expires_at: datetime | None = None,
) -> IssuedCredential:
    """Issue a credential. Older ones are not revoked automatically, so that a switch
    can happen with both in use."""
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("this principal is out of this administrator's reach")
    if client.subject_type != Subject.MACHINE:
        # A person's identity is vouched for elsewhere. A credential held here would
        # still work after the account was disabled there.
        raise Invalid(
            {"subject_type": "a person is issued no credential; identity is vouched for "
                             "elsewhere"}
        )
    # Only a credential for an allowed mechanism is issued; otherwise the restriction
    # would be a statement and nothing more.
    manager = session.get(Manager, client.manager_id) if client.manager_id else None
    policy = policy_for(session.get(Naan, client.naan), manager)
    if policy.allowed_auth:
        need = "apikey" if kind == CredentialKind.API_KEY else "oauth2"
        if need not in policy.allowed_auth.split():
            raise Invalid(
                {"kind": f"{need} is not allowed here (allowed: {policy.allowed_auth})"}
            )

    gen = apikey.generate_key if kind == CredentialKind.API_KEY else oauth2.generate_secret
    raw, prefix, hashed = gen()
    cred = Credential(
        client_pk=client.id,
        kind=kind,
        prefix=prefix,
        hashed=hashed,
        label=label,
        expires_at=expires_at,
    )
    session.add(cred)
    session.flush()
    audit(session, p, "issue_credential", client.client_id, kind=kind)
    return IssuedCredential(credential=cred, secret=raw)


def set_password(session: Session, p: Principal, *, client_pk: int, password: str) -> Credential:
    """Set a password on a person, replacing one that is already there.

    Only a person gets one. A machine does not remember a password, and giving it one
    only adds another secret written down somewhere.

    Replacing disables the old row and adds a new one, so when it changed is still
    known.
    """
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("this principal is out of this administrator's reach")
    if client.subject_type != Subject.PERSON:
        raise Invalid({"subject_type": "only a person can have a password"})

    try:
        hashed = pw.hash_password(password)
    except pw.WeakPassword as exc:
        raise Invalid({"password": str(exc)}) from exc

    for old in session.scalars(
        select(Credential).where(
            Credential.client_pk == client.id,
            Credential.kind == CredentialKind.PASSWORD,
            Credential.active.is_(True),
        )
    ):
        old.active = False

    cred = Credential(
        client_pk=client.id, kind=CredentialKind.PASSWORD.value,
        prefix="", hashed=hashed, label="password",
    )
    session.add(cred)
    session.flush()
    audit(session, p, "set_password", client.client_id)
    return cred


def set_client_active(
    session: Session, p: Principal, *, client_pk: int, active: bool
) -> Client:
    """Stop a principal, or start it again. The row is not deleted.

    Where an authorisation server is used, this is the only lever arkhe has: with oidc it
    holds no credential, so revoke_credential does nothing, and without this the tokens
    that server keeps issuing keep working.

    Having two places to stop something is a strength rather than a weakness:

      the authorisation server  stops issuing tokens, which affects every resource
      arkhe                     stops it entering this namespace, and nothing else

    It can only be started again while its organisation is alive. Restoring a principal
    that a departure or a merger stopped would hollow out the decision that minting has
    stopped.
    """
    client = session.get(Client, client_pk)
    if client is None:
        raise NotFound({"client": client_pk})
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("this principal is out of this administrator's reach")
    if active and client.manager_id is not None:
        manager = session.get(Manager, client.manager_id)
        if manager is not None and not manager.active:
            raise Invalid(
                {"active": "a principal of a departed organisation cannot be restored; "
                           "undo the succession or departure first"}
            )
    client.active = active
    audit(session, p, "enable_client" if active else "disable_client", client.client_id)
    return client


def revoke_credential(session: Session, p: Principal, *, credential_id: int) -> Credential:
    """Revoke it. The row is not deleted, so when it was revoked is still known."""
    cred = session.get(Credential, credential_id)
    if cred is None:
        raise NotFound({"credential": credential_id})
    client = cred.client
    _require_naan(p, client.naan)
    if not p.is_naan_wide and client.manager_id != p.manager_id:
        raise Forbidden("this credential is out of this administrator's reach")
    cred.active = False
    cred.expires_at = cred.expires_at or datetime.now(UTC)
    audit(session, p, "revoke_credential", client.client_id, credential=credential_id)
    return cred


# ------------------------------------------------- Succession and departure
#
# This is where ARK's thinking shows most: identifiers survive any change of custodian.
# Having declared NR, a name already handed out as ark:<NAAN>/... cannot be reassigned,
# because reassigning it kills the original identifier. So resolution continues, and what
# changes is only who mints new names and where they redirect.


def succeed(
    session: Session,
    p: Principal,
    *,
    predecessor_id: int,
    successor_id: int,
    retire: bool = True,
) -> dict:
    """A merger: move the old organisation's namespaces to its successor.

    Whole shoulders move, so the shoulder_id of an existing ARK does not change and
    neither the identifiers nor where they resolve are touched. What changes is who holds
    that namespace from now on.

    With retire=True the moved shoulders stop minting while existing ARKs keep resolving:
    the successor mints in its own shoulder and the old namespace becomes read-only.
    """
    pre = session.get(Manager, predecessor_id)
    suc = session.get(Manager, successor_id)
    if pre is None or suc is None:
        raise NotFound({"manager": [predecessor_id, successor_id]})
    require_manager(session, p, pre)
    _require_naan(p, suc.naan)
    if pre.id == suc.id:
        raise Invalid({"successor": "an organisation cannot succeed itself"})
    if pre.naan != suc.naan:
        # Succession across NAANs cannot be expressed by moving shoulders: the
        # namespaces are different things.
        raise Invalid(
            {"successor": "succession cannot cross NAANs: the shape of the identifier "
                          "would change"}
        )

    moved = []
    for sh in list(pre.shoulders):
        sh.manager_id = suc.id
        if retire:
            sh.status = ShoulderStatus.RETIRED.value
            sh.note = (sh.note + " / ").lstrip(" /") + f"succeeded from {pre.name}"
        moved.append(f"{sh.naan}{sh.shoulder}")
    pre.succeeded_by_id = suc.id
    pre.active = False
    # The old organisation's credentials are stopped. The rows stay, so whose they
    # were is still known.
    revoked = [c.client_id for c in session.scalars(
        select(Client).where(Client.manager_id == pre.id, Client.active.is_(True))
    )]
    for c in session.scalars(select(Client).where(Client.manager_id == pre.id)):
        c.active = False

    audit(session, p, "succeed", pre.name, successor=suc.name, shoulders=moved, revoked=revoked)
    return {"moved": moved, "revoked": revoked, "successor": suc.name}


def depart(
    session: Session,
    p: Principal,
    *,
    manager_id: int,
    resolver_template: str = "",
    keep_update_label: str = "",
) -> dict:
    """An organisation leaves. It continues to exist; this is not a merger.

    One thing matters: minting stops and resolution continues for ever. Names handed out
    as ark:<this NAAN>/... cannot be reassigned, so whoever holds the NAAN goes on
    answering 302.

    Passing resolver_template is recommended. It repoints every existing ARK at the
    organisation's own resolver and sets the same delegation on the shoulder, so that
    everything afterwards stays on their side. Without it, the organisation that left
    would have to send us an update every time something moves, and anything that needs
    ongoing work gets forgotten, leaving dead links.

    The template uses the same notation as Shoulder.redirect ($id and ${blade}), for
    example https://repo.univ.ac.jp/ark/${blade}.
    """
    from arkhe.domain.resolution import expand_redirect

    manager = session.get(Manager, manager_id)
    if manager is None:
        raise NotFound({"manager": manager_id})
    require_manager(session, p, manager)

    shoulders = list(manager.shoulders)
    rewritten = 0
    if resolver_template:
        ids = [sh.id for sh in shoulders]
        for sh in shoulders:
            sh.redirect = resolver_template  # unregistered names go there too
        for ark in session.scalars(select(Ark).where(Ark.shoulder_id.in_(ids))):
            _, ark.url = expand_redirect(resolver_template, ark.naan, ark.assigned_name)
            rewritten += 1

    for sh in shoulders:
        sh.status = ShoulderStatus.RETIRED.value
        sh.note = (sh.note + " / ").lstrip(" /") + "minting stopped on departure"

    revoked = [c.client_id for c in session.scalars(
        select(Client).where(Client.manager_id == manager.id, Client.active.is_(True))
    )]
    for c in session.scalars(select(Client).where(Client.manager_id == manager.id)):
        c.active = False

    issued = None
    if keep_update_label:
        # Only the right to update is left. Separate scopes pay off here: the
        # organisation can no longer mint, but it can repoint its own targets.
        client = register_client(
            session, p, client_id=f"{manager.name}-{keep_update_label}",
            naan=manager.naan, manager_id=manager.id, scopes="ark:update",
            label=keep_update_label,
        )
        issued = issue_credential(session, p, client_pk=client.id).secret

    manager.active = False
    audit(
        session, p, "depart", manager.name,
        shoulders=[f"{s.naan}{s.shoulder}" for s in shoulders],
        rewritten=rewritten, revoked=revoked,
    )
    return {
        "shoulders": [f"{s.naan}{s.shoulder}" for s in shoulders],
        "rewritten": rewritten,
        "revoked": revoked,
        "update_secret": issued,
    }


# ------------------------------------------------------- Holding redirection


#: The levels a hold can be set at, narrowest first, which is also the order they are
#: checked in.
HOLD_KINDS = ("ark", "shoulder", "naan")


def _hold_deadline(until: datetime, max_days: int, now: datetime | None = None) -> datetime:
    """Check the expiry. Neither the past nor beyond the ceiling is accepted.

    There is a ceiling because requiring an expiry is not enough on its own: "in a year"
    is no different from permanent. Extending means setting it again, which the audit log
    records.
    """
    now = now or datetime.now(UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if until <= now:
        raise Invalid({"until": "the expiry is in the past; a hold has to end in the future"})
    if (until - now).days > max_days:
        raise Invalid(
            {
                "until": f"the expiry is beyond the ceiling of {max_days} days",
                "reason": "a long hold is no different from a permanent one; set it again "
                          "to extend it",
            }
        )
    return until


def _hold_row(session: Session, p: Principal, kind: str, key):
    """Fetch the row a hold applies to, and check that this principal may set it.

    An organisation's administrator can hold an ARK, since it is inside their own
    shoulder. Holding a shoulder or a NAAN stops the namespace itself, so it takes NAAN
    level or above: one organisation's decision must not take another organisation's
    identifiers with it.
    """
    if kind == "ark":
        row = session.get(Ark, key)
        if row is None:
            raise NotFound({"ark": key})
        from arkhe.domain import authz  # imported here to avoid a cycle

        authz.assert_may_touch(session, p, row)
        return row, row.ark
    if kind == "shoulder":
        row = session.get(Shoulder, key)
        if row is None:
            raise NotFound({"shoulder": key})
        _require_naan(p, row.naan)
        if not p.is_naan_wide:
            raise Forbidden("holding a namespace needs NAAN level or above")
        return row, f"{row.naan}{row.shoulder}"
    if kind == "naan":
        row = session.get(Naan, key)
        if row is None:
            raise NotFound({"naan": key})
        _require_naan(p, row.naan)
        if not p.is_naan_wide:
            raise Forbidden("holding a NAAN needs NAAN level or above")
        return row, row.naan
    raise Invalid({"kind": f"{kind} cannot be held ({', '.join(HOLD_KINDS)})"})


def set_hold(
    session: Session,
    p: Principal,
    *,
    kind: str,
    key,
    until: datetime,
    reason: str,
    max_days: int = 90,
):
    """Hold redirection for a while. Resolution is not stopped; the description keeps
    coming back.

    A reason is required. It is published at ?info, and a hold with no reason cannot be
    lifted by anyone but whoever set it, so it sits there until it expires.
    """
    if not reason.strip():
        raise Invalid(
            {"reason": "a reason is required: it is published, and lifting the hold "
                       "needs it"}
        )
    row, target = _hold_row(session, p, kind, key)
    row.hold_until = _hold_deadline(until, max_days)
    row.hold_reason = reason.strip()
    row.hold_by = p.client_id
    audit(
        session, p, "hold", f"{kind}:{target}",
        until=row.hold_until.isoformat(), reason=row.hold_reason,
    )
    if kind == "ark":
        # Recorded in the identifier's own history. The audit log keeps only NAAN
        # level and above, and an organisation may be the one holding it; to whoever
        # follows the ARK, this is the same as the target changing.
        from arkhe.domain import authz

        authz.record_change(session, p, row, action="hold", before_url=row.url)
    return row


def release_hold(session: Session, p: Principal, *, kind: str, key):
    """Lift a hold before its expiry.

    An expiry stops applying against the clock on its own (resolution.hold_of), so this
    is only ever early. The row stays; only hold_until is cleared.
    """
    row, target = _hold_row(session, p, kind, key)
    row.hold_until = None
    row.hold_reason = ""
    row.hold_by = ""
    audit(session, p, "release_hold", f"{kind}:{target}")
    if kind == "ark":
        from arkhe.domain import authz

        authz.record_change(session, p, row, action="release_hold", before_url=row.url)
    return row


def held(session: Session, p: Principal, now: datetime | None = None) -> list[dict]:
    """List the holds in force. Even with an expiry, a hold nobody can see becomes
    permanent.

    It is narrowed by reach: a hold on a namespace that is not visible is not shown.
    """
    now = now or datetime.now(UTC)
    out: list[dict] = []
    for kind, model, label in (
        ("naan", Naan, lambda r: r.naan),
        ("shoulder", Shoulder, lambda r: f"{r.naan}{r.shoulder}"),
        ("ark", Ark, lambda r: r.ark),
    ):
        for row in session.scalars(select(model).where(model.hold_until > now)):
            if not p.reaches_naan(row.naan):
                continue
            out.append(
                {
                    "kind": kind,
                    "target": label(row),
                    "until": row.hold_until,
                    "reason": row.hold_reason,
                    "by": row.hold_by,
                }
            )
    return out


# ------------------------------------------- Publishing and withdrawing
#
# NR binds names that went out. It does not bind from the moment of minting: giving a
# draft a number in advance and then deciding not to publish it, leaving that number in
# the ledger naming nothing, is not keeping the promise either.
#
# So a reserved state exists (Ark.published_at). There is one boundary:
#
#   reserved   does not resolve, and can be deleted. The name moves to WithdrawnName and
#              is never minted again
#   published  as before. It is never deleted; tombstone it or empty the url
#
# Note: since 0.4.0 a publication can be withdrawn, which is reversible, while deleting a
# name that was ever published takes a reason and the ARK typed again.


def publish_ark(session: Session, p: Principal, *, ark: str) -> Ark:
    """Publish to the world. From then on the ARK resolves, and it cannot be deleted.

    Calling it twice is not an error. Publishing is a request from across a network and
    the response can be lost; answering 409 would send the caller off to check somewhere
    else whether it worked. If it is already published, the row is returned as it is.
    """
    row = _ark_in_reach(session, p, ark)
    if row.published_at is not None:
        return row  # a resend gets the same answer, as with the receipts in F4
    now = datetime.now(UTC)
    # Publishing again, or for the first time. The first is putting back something
    # that was taken down, and what matters to a reader is that there was a period when
    # it did not resolve.
    again = row.first_published_at is not None
    row.published_at = now
    if not again:
        # One-way: once set it is never cleared, because having been public cannot be
        # undone.
        row.first_published_at = now
    row.updated_by = p.client_id
    from arkhe.domain import authz  # imported here to avoid a cycle

    # Recorded in the identifier's own history. The audit log keeps only NAAN level
    # and above, while publishing is done by organisations, and when something went out
    # is always needed later.
    action = "republish" if again else "publish"
    authz.record_change(session, p, row, action=action, before_url=row.url)
    audit(session, p, action, row.ark)
    return row


def _exposed_guards(row: Ark, *, reason: str, confirm: str) -> None:
    """The ceremony for touching a name that was ever public.

    The weight follows the name's history rather than the caller's tier, because what
    matters is what is being lost, not who is deleting it. The RA operator deleting a
    reservation is light; an organisation's administrator taking down a name that has
    been cited for three years is heavy. Deciding by tier would get those the wrong way
    round.

    Two things are required, the same as for a purge:

    1. a reason, which is all that will be left to say about the name afterwards
    2. the ARK typed again (confirm), so that a script walking a list cannot take
       everything down by accident
    """
    if not row.was_ever_public:
        return
    if not reason.strip():
        raise Invalid(errors.EXPOSED_NEEDS_REASON)
    if _key_of(confirm) != row.ark:
        raise Invalid(errors.EXPOSED_NOT_CONFIRMED, ark=compact_ark(row.ark))


def unpublish_ark(
    session: Session, p: Principal, *, ark: str, reason: str, confirm: str = ""
) -> Ark:
    """Withdraw a publication. The row stays, and the ARK stops resolving on a public
    resolver.

    0.3.0 decided there would be no way to undo publication. That was reversed because
    the decision to take something down belongs to the organisation that holds the
    object: whoever notices that something should never have been published is the
    depositor rather than the RA, and until a request travels to the RA and back, it
    stays out. The reach is the same three tiers as before (_ark_in_reach).

    NR is not broken. After a withdrawal the name belongs to nobody, and there is no path
    anywhere that points it at another object. An old reference simply gets 404: what
    breaks is "it keeps resolving", not "it never names something else".

    The row is not deleted. Deleting is a separate operation (withdraw_ark), which also
    requires that nothing hangs off it. Taking down and deleting are not one step: the
    first can be undone and the second cannot.
    """
    row = _ark_in_reach(session, p, ark)
    if row.published_at is None:
        raise Conflict(errors.ARK_NOT_PUBLIC, ark=compact_ark(row.ark))
    _exposed_guards(row, reason=reason, confirm=confirm)
    row.published_at = None
    row.updated_by = p.client_id
    from arkhe.domain import authz  # imported here to avoid a cycle

    authz.record_change(session, p, row, action="unpublish", before_url=row.url)
    audit(session, p, "unpublish", row.ark, reason=reason.strip()[:500])
    return row


def withdraw_ark(
    session: Session, p: Principal, *, ark: str, reason: str = "", confirm: str = ""
) -> WithdrawnName:
    """Delete an ARK that is not published. The row goes and the name remains, unused.

    Two conditions have to hold:

    1. it is not published right now. Something published goes through unpublish_ark
       first: taking down and deleting are not one step, since the first can be undone
       and the second cannot. purge_ark exists for doing both at once
    2. no qualified name hangs off it. Removing only the parent would leave part
       references with nothing to inherit from, so work upwards

    If the name was ever published, a reason and the ARK typed again are required
    (_exposed_guards): deleting a reservation that was never published loses less.

    The name moves to WithdrawnName. Deleting the row is not deleting the record: a
    reserved string may already be in someone's hands, and pointing it at another object
    would be indistinguishable, from outside, from an NR violation.

    ArkChange and MintReceipt reference this ARK and go with it. Deleting history is not
    pleasant, but this is the history of an identifier that was never published, and
    keeping it would leave rows alive only to satisfy a foreign key. That it was
    withdrawn remains in WithdrawnName and in the audit log.
    """
    row = _ark_in_reach(session, p, ark)
    if row.published_at is not None:
        raise Conflict(errors.ARK_ALREADY_PUBLIC, ark=compact_ark(row.ark))
    _exposed_guards(row, reason=reason, confirm=confirm)
    action = "withdraw_exposed" if row.was_ever_public else "withdraw"
    return _remove_ark(session, p, row, reason=reason, action=action)


def withdraw_bulk(
    session: Session, p: Principal, *, arks: list[str], reason: str = ""
) -> list[WithdrawnName]:
    """Delete several ARKs that were never public, in one request.

    This exists because reserving in bulk is a real way of working: numbers are handed to
    objects that are still under review, sometimes for years, and when a batch of those
    is abandoned there has to be a way to throw it away that is as cheap as minting it
    was. Deleting them one at a time is not that.

    What makes it safe to be cheap is that **nothing here has ever been seen**. Every row
    must be unpublished now and never have been published; one that has been out is
    refused, and the whole request with it. That name goes through the single-ARK path,
    which asks for a reason and the ARK typed again. The weight still follows the name's
    history rather than the size of the request.

    It is all or nothing, like the other bulk operations: every row is checked before
    anything is deleted, so a batch cannot be half gone. Each name still moves to
    WithdrawnName and is never assigned again, and one audit event records the count.
    """
    from arkhe.domain import authz

    found = authz.fetch_for_update(session, p, arks)  # one missing row fails it all
    rows = [found[k] for k in arks]
    for row in rows:
        authz.assert_may_touch(session, p, row)
        if row.published_at is not None:
            raise Conflict(errors.ARK_ALREADY_PUBLIC, ark=compact_ark(row.ark))
        if row.was_ever_public:
            raise Conflict(errors.BULK_EXPOSED, ark=compact_ark(row.ark))

    gone = [
        _remove_ark(session, p, row, reason=reason, action="bulk_withdraw") for row in rows
    ]
    audit(session, p, "bulk_withdraw", count=len(gone))
    return gone


def purge_ark(
    session: Session, p: Principal, *, ark: str, reason: str, confirm: str = ""
) -> WithdrawnName:
    """Purge a published ARK: withdrawal and deletion in one step, within the caller's
    reach.

    This system exists so that a name once handed out never points at something else, and
    a published ARK not being deletable is at the centre of that promise. The route
    exists anyway because real operations sometimes bring a demand that outweighs an
    identifier: a court removal order, personal information that should never have been
    published, a mass of rows loaded by mistake. With no way out, someone edits the
    database directly, and a deletion that leaves no trace is the worst kind.

    So rather than saying it cannot be done, there is one path, and it leaves a trace:

      1. within the caller's reach (_ark_in_reach): an organisation its own shoulder,
         a NAAN administrator its own NAAN, the RA everything
      2. a reason is required. Empty is refused: a purge that leaves no record is the
         same as one that never happened
      3. the ARK is typed again, in confirm, so that a script walking a list cannot
         empty the ledger by accident
      4. the name is not returned to use. It moves to WithdrawnName and is never minted
         again
      5. it is recorded in the audit log

    0.4.0 stopped restricting this to authority=system. Once publication could be
    withdrawn, unpublish followed by withdraw reached the same result in two steps, so
    restricting only the one-step version by tier protected nothing. What binds is reach
    and ceremony, not tier.

    Point 4 is what holds. The target and the description go, but that name never points
    at something else: an old reference simply gets 404, and NR itself is not broken.
    What breaks is "it keeps resolving".
    """
    if not reason.strip():
        raise Invalid(errors.PURGE_NEEDS_REASON)
    row = _ark_in_reach(session, p, ark)
    # The ARK is typed again. Either spelling is fine, with or without ark:, but a
    # different ARK is refused.
    if _key_of(confirm) != row.ark:
        raise Invalid(errors.PURGE_NOT_CONFIRMED, ark=compact_ark(row.ark))
    if row.published_at is None:
        # A reserved ARK belongs to withdraw. One operation does not get two
        # entrances.
        return _remove_ark(session, p, row, reason=reason, action="withdraw")
    return _remove_ark(session, p, row, reason=reason, action="purge")


def _remove_ark(
    session: Session, p: Principal, row: Ark, *, reason: str, action: str
) -> WithdrawnName:
    """Remove the row and record the name as withdrawn. Both withdrawal and purging go
    through here.

    Only the conditions at the entrance differ; there is one exit. That the name is never
    minted again, and that a trace remains, has to hold whichever way it was reached.
    """
    parts = session.scalar(
        select(func.count(Ark.ark))
        .select_from(Ark)
        .where(Ark.ark.like(_like_prefix(row.ark), escape="\\"), Ark.ark != row.ark)
    )
    if parts:
        # Work upwards: removing only the parent leaves part references with nothing
        # to inherit from.
        raise Conflict(errors.ARK_HAS_PARTS, ark=compact_ark(row.ark), count=parts)

    gone = WithdrawnName(
        ark=row.ark,
        naan=row.naan,
        assigned_name=row.assigned_name,
        shoulder_id=row.shoulder_id,
        minted_at=row.created_at,
        minted_by=row.created_by,
        # Record whether it was ever public, from first_published_at rather than
        # published_at. After a withdrawal the latter is null, which would turn the
        # record of a name that went out into one of a mere reservation.
        published_at=row.first_published_at or row.published_at,
        withdrawn_by=p.client_id,
        reason=reason.strip()[:500],
        ip=p.ip,
    )
    session.add(gone)
    # The references go first: both point at this ARK through a foreign key.
    session.execute(delete(ArkChange).where(ArkChange.ark == row.ark))
    session.execute(delete(MintReceipt).where(MintReceipt.ark == row.ark))
    with sanctioned_purge(session, row.ark):
        # A published row can only be removed here (models._no_published_ark_delete).
        session.delete(row)
        session.flush()
    audit(session, p, action, gone.ark, reason=gone.reason, published=bool(row.published_at))
    return gone


def _ark_in_reach(session: Session, p: Principal, ark: str) -> Ark:
    """Fetch the row and check that this principal may touch it.

    The decision is authz.assert_may_touch, the same one update and tombstone use.
    Publishing and withdrawing are both ways of touching an existing ARK, and there is no
    reason for their reach to differ.
    """
    row = session.get(Ark, ark)
    if row is None:
        raise NotFound(errors.ARK_NOT_FOUND, missing=[ark], count=1)
    from arkhe.domain import authz

    authz.assert_may_touch(session, p, row)
    return row


def _key_of(raw: str) -> str:
    """Turn ark:99999/x9... or a bare 99999/x9... into the ledger key, or an empty
    string when it cannot be read.

    No exception is raised here, because confirm is a comparison against what was typed
    rather than input validation: a string that cannot be read simply did not match.
    """
    from arkhe.domain.queries import ark_key_from_input

    try:
        return ark_key_from_input(raw)
    except ValueError:
        return ""


def _like_prefix(key: str) -> str:
    """Build a prefix LIKE pattern. Names arrive containing % and _, such as %2F.

    Passed as they are, the % in x9...%2Fa becomes a wildcard and other ARKs would be
    counted as children, so the characters are escaped first.
    """
    return key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
