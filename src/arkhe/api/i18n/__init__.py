"""Localisation of the screens, with Japanese and English built in.

Both the admin interface and ?info, the page that shows a resolution to a person, take
their wording from here.

These are dictionaries rather than gettext, for two reasons: compiling .mo files would
add a step to the image build, which is not worth it at this size; and adding a language
takes one module, with any gap failing at startup.

If they ever have to go to a translator, .po files can be produced from these
dictionaries.

The language is chosen as ?lang=, then the cookie, then Accept-Language, then the
default. An explicit choice is remembered, so it holds on later pages.

Split by screen

Several hundred entries in one file would mean reading all of it to find the wording to
change. The split is by screen rather than by language: separate files per language
would put a pair far apart, and adding to only one would not show in the diff. The check
at startup is the last line of defence, not the first.

  _shell    wording on every screen: headings, states, common form labels
  _ledger   organisations and namespaces: the structure of delegation and building it
  _clients  registering principals, credentials, how they get in, and scopes
  _arks     minting, and the minted ARKs
  _signin   the login page and the pages that lead back to it
  _audit    the audit log
  _info     ?info, which is public rather than part of the admin interface
"""

from __future__ import annotations

from fastapi import Request

from arkhe.api.i18n import _arks, _audit, _clients, _info, _ledger, _shell, _signin, _stats

DEFAULT = "ja"
LANGS = {"ja": "日本語", "en": "English"}
COOKIE = "arkhe_lang"

#: Merge the per-screen catalogues into one. A key in two places fails at startup: if
#: the later one won silently, wording someone had fixed would stay unfixed.
_PARTS = (_shell, _ledger, _clients, _arks, _signin, _audit, _info, _stats)


def _merge(attr: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in _PARTS:
        cat = getattr(part, attr)
        clash = out.keys() & cat.keys()
        if clash:  # pragma: no cover - only happens during development
            raise RuntimeError(f"duplicate keys in {part.__name__}: {sorted(clash)}")
        out |= cat
    return out


JA: dict[str, str] = _merge("JA")
EN: dict[str, str] = _merge("EN")

CATALOGS = {"ja": JA, "en": EN}

#: A missing translation fails at startup, so adding to one language only is noticed.
_missing = {lang: sorted(set(JA) - set(cat)) for lang, cat in CATALOGS.items()}
if any(_missing.values()):  # pragma: no cover - only happens during development
    raise RuntimeError(f"missing translations: { {k: v for k, v in _missing.items() if v} }")


def pick(request: Request) -> str:
    """Choose a language: ?lang=, then the cookie, then Accept-Language, then the
    default."""
    q = request.query_params.get("lang")
    if q in CATALOGS:
        return q
    c = request.cookies.get(COOKIE)
    if c in CATALOGS:
        return c
    for part in request.headers.get("accept-language", "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in CATALOGS:
            return tag[:2]
    return DEFAULT


def translator(lang: str):
    cat = CATALOGS.get(lang, JA)

    def t(key: str) -> str:
        return cat.get(key, key)

    return t
