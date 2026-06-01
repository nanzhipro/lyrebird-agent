"""i18n: loader, flatten, fallback, locale negotiation."""
import json
from pathlib import Path

import pytest

from lyrebird.i18n import I18nRegistry, negotiate_locale


@pytest.fixture
def locales_root(tmp_path: Path) -> Path:
    root = tmp_path / "locales"
    root.mkdir()
    (root / "zh.json").write_text(json.dumps({
        "nav": {"about": "关于", "run": "运行"},
        "hero": {"title": "看见简历背后的机制", "lead": "六个智能体..."},
        "form": {"start": "启动萃取"},
        "missing_only_in_zh": "仅中文",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "en.json").write_text(json.dumps({
        "nav": {"about": "About", "run": "Run"},
        "hero": {"title": "See the mechanisms behind the resume", "lead": "Six agents..."},
        "form": {"start": "Start extraction"},
    }, ensure_ascii=False), encoding="utf-8")
    return root


def test_available_lists_loaded_locales(locales_root):
    r = I18nRegistry(root=locales_root)
    assert set(r.available()) == {"zh", "en"}


def test_get_returns_flat_dict(locales_root):
    r = I18nRegistry(root=locales_root)
    zh = r.get("zh")
    assert zh["nav.about"] == "关于"
    assert zh["hero.title"] == "看见简历背后的机制"


def test_t_returns_translated_string(locales_root):
    r = I18nRegistry(root=locales_root)
    assert r.t("zh", "nav.about") == "关于"
    assert r.t("en", "nav.about") == "About"


def test_t_falls_back_to_default_when_key_missing(locales_root):
    """If en is missing a key, fall back to zh (the default), then the key itself."""
    r = I18nRegistry(root=locales_root, default="zh")
    # missing_only_in_zh exists in zh but not en
    assert r.t("en", "missing_only_in_zh") == "仅中文"


def test_t_returns_key_when_truly_missing(locales_root):
    r = I18nRegistry(root=locales_root)
    assert r.t("zh", "not.a.real.key") == "not.a.real.key"


def test_t_interpolates_variables(locales_root):
    (locales_root / "zh.json").write_text(json.dumps({
        "greet": "你好, {name}, 还剩 {n} 步."
    }, ensure_ascii=False), encoding="utf-8")
    r = I18nRegistry(root=locales_root)
    assert r.t("zh", "greet", name="L", n=3) == "你好, L, 还剩 3 步."


def test_unknown_locale_uses_default(locales_root):
    r = I18nRegistry(root=locales_root, default="zh")
    assert r.t("xx-YY", "nav.about") == "关于"


def test_default_locale_property(locales_root):
    r = I18nRegistry(root=locales_root, default="zh")
    assert r.default == "zh"


# ---------- locale negotiation ----------

def test_negotiate_prefers_explicit_query():
    locale = negotiate_locale(
        query="en", cookie="zh", accept_language="zh-CN",
        available={"zh", "en"}, default="zh",
    )
    assert locale == "en"


def test_negotiate_falls_back_to_cookie():
    locale = negotiate_locale(
        query=None, cookie="en", accept_language="zh-CN",
        available={"zh", "en"}, default="zh",
    )
    assert locale == "en"


def test_negotiate_uses_accept_language_when_no_query_or_cookie():
    locale = negotiate_locale(
        query=None, cookie=None, accept_language="fr-FR,en-US;q=0.8,zh;q=0.5",
        available={"zh", "en"}, default="zh",
    )
    # en-US is highest-q available
    assert locale == "en"


def test_negotiate_matches_language_tag_prefix():
    locale = negotiate_locale(
        query=None, cookie=None, accept_language="zh-CN,zh-Hans;q=0.9",
        available={"zh", "en"}, default="en",
    )
    assert locale == "zh"


def test_negotiate_falls_back_to_default_when_nothing_matches():
    locale = negotiate_locale(
        query=None, cookie=None, accept_language="fr-FR",
        available={"zh", "en"}, default="zh",
    )
    assert locale == "zh"


def test_negotiate_rejects_unavailable_query():
    locale = negotiate_locale(
        query="fr", cookie=None, accept_language=None,
        available={"zh", "en"}, default="zh",
    )
    assert locale == "zh"


def test_negotiate_rejects_unavailable_cookie():
    locale = negotiate_locale(
        query=None, cookie="zz", accept_language=None,
        available={"zh", "en"}, default="zh",
    )
    assert locale == "zh"


def test_negotiate_handles_empty_accept_language():
    locale = negotiate_locale(
        query=None, cookie=None, accept_language="",
        available={"zh", "en"}, default="zh",
    )
    assert locale == "zh"


def test_negotiate_with_quality_ordering():
    """Higher q wins."""
    locale = negotiate_locale(
        query=None, cookie=None,
        accept_language="zh;q=0.3,en;q=0.9",
        available={"zh", "en"}, default="zh",
    )
    assert locale == "en"


# ---------- key-coverage parity (real project locales) ----------

PROJECT_LOCALES = Path(__file__).resolve().parent.parent / "src" / "lyrebird" / "i18n" / "locales"


def test_project_locales_load():
    """Real locale files in the repo must load without errors."""
    r = I18nRegistry(root=PROJECT_LOCALES, default="zh")
    assert "zh" in r.available()
    assert "en" in r.available()


def test_project_locales_have_matching_keys():
    """zh and en must share the same key set. Catches drift when adding strings."""
    r = I18nRegistry(root=PROJECT_LOCALES, default="zh")
    zh_keys = set(r._cache["zh"].keys())
    en_keys = set(r._cache["en"].keys())
    only_in_zh = zh_keys - en_keys
    only_in_en = en_keys - zh_keys
    assert not only_in_zh, f"keys missing from en.json: {sorted(only_in_zh)}"
    assert not only_in_en, f"keys missing from zh.json: {sorted(only_in_en)}"


def test_project_locales_no_empty_strings():
    r = I18nRegistry(root=PROJECT_LOCALES, default="zh")
    for locale in r.available():
        for key, value in r._cache[locale].items():
            assert value.strip(), f"{locale}.{key} is empty"
