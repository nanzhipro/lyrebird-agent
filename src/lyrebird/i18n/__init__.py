"""Internationalization.

Three-tier negotiation:
    query ?lang=  >  cookie lyrebird_lang  >  Accept-Language  >  default

Three-tier fallback inside a locale lookup:
    requested locale  >  default locale  >  literal key

Locale data lives in `locales/<locale>.json` as a (possibly nested) JSON file.
We flatten dotted-paths once at load time, so lookup is O(1).

Add a new language: drop `locales/xx.json`, hot-restart server. Add a new
string: add the key in every locale file. CI/lint can catch missing keys
(see scripts/check_i18n_coverage.py if you write one later).
"""
from lyrebird.i18n.loader import I18nRegistry, negotiate_locale

__all__ = ["I18nRegistry", "negotiate_locale"]
