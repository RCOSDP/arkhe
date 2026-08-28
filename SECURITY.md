# Security

## Reporting

Please report suspected vulnerabilities through **GitHub's private vulnerability
reporting** on this repository (Security → Report a vulnerability), not as a public
issue.

Include what you did, what happened, and what you expected. A proof of concept helps
but is not required.

## What we consider serious here

arkhe holds a ledger of identifiers that **cannot be reissued**. That shapes the
severity of a report:

- **Anything that lets one institution reach another's namespace.** Minting into a
  namespace you were not delegated is worse than it looks: the name cannot be
  reclaimed afterwards.
- **Anything that rewrites where an existing ARK points**, without the reach to do so.
  This is identifier hijacking.
- **Anything that deletes an ARK or a namespace.** The code refuses; a way around the
  refusal is a vulnerability.
- **Privilege escalation across the three tiers** (`manager` → `naan` → `system`), or
  a machine subject reachable through an external login.

## Known operational hazards

These are documented rather than fixed, because they are properties of a configuration
rather than defects:

- **`ARKHE_ADMIN_LOGIN=proxy` trusts a header.** If anything can reach arkhe without
  passing the proxy, that header can be forged. Close the direct path.
- **`ARKHE_AUTH=oauth2` signs with a shared secret (HS256).** Every replica holds the
  signing key, and rotating it invalidates all tokens at once. Prefer `oidc` where an
  authorization server exists.
- **The compose stacks under `compose/` carry secrets in the clear.** They are for
  demonstration.
