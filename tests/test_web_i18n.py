"""i18n HTTP API: /api/i18n/locales + /api/i18n/{locale}."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")
    from lyrebird.web import app as app_mod
    monkeypatch.setattr(app_mod, "ARTIFACTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(app_mod, "RUNS_ROOT", tmp_path / "runs")
    app = app_mod.create_app()
    with TestClient(app) as c:
        yield c


def test_locales_list_returns_zh_and_en(client):
    r = client.get("/api/i18n/locales")
    assert r.status_code == 200
    body = r.json()
    codes = [l["code"] for l in body["locales"]]
    assert "zh" in codes
    assert "en" in codes
    assert body["default"] == "zh"
    # current is one of available
    assert body["current"] in codes


def test_locales_includes_native_and_html_lang(client):
    body = client.get("/api/i18n/locales").json()
    by_code = {l["code"]: l for l in body["locales"]}
    assert by_code["zh"]["native"] == "中文"
    assert by_code["en"]["native"] == "English"
    assert by_code["zh"]["html_lang"] == "zh-Hans"
    assert by_code["en"]["html_lang"] == "en"


def test_i18n_strings_zh(client):
    r = client.get("/api/i18n/zh")
    assert r.status_code == 200
    body = r.json()
    assert body["locale"] == "zh"
    assert body["strings"]["form.start"] == "开始萃取"
    assert body["strings"]["nav.about"] == "关于"


def test_i18n_strings_en(client):
    r = client.get("/api/i18n/en")
    body = r.json()
    assert body["locale"] == "en"
    assert body["strings"]["form.start"] == "Start extraction"
    assert body["strings"]["nav.about"] == "About"


def test_i18n_unknown_locale_falls_back_with_header(client):
    r = client.get("/api/i18n/zz")
    assert r.status_code == 200
    assert r.headers.get("x-lyrebird-fallback") == "true"
    body = r.json()
    assert body["locale"] == "zh"  # default


def test_i18n_sets_cookie(client):
    r = client.get("/api/i18n/en")
    cookie = r.cookies.get("lyrebird_lang")
    assert cookie == "en"


def test_index_sets_cookie_based_on_accept_language(client):
    r = client.get("/", headers={"accept-language": "en-US,en;q=0.9,zh;q=0.5"})
    assert r.status_code == 200
    assert r.cookies.get("lyrebird_lang") == "en"


def test_index_query_overrides_accept_language(client):
    r = client.get("/?lang=zh", headers={"accept-language": "en"})
    assert r.cookies.get("lyrebird_lang") == "zh"


def test_index_cookie_persists_choice(client):
    # First visit forces en
    client.get("/?lang=en")
    # Cookie is now set on the test client; revisit without query
    r = client.get("/", headers={"accept-language": "zh"})
    # Cookie should win over Accept-Language
    assert r.cookies.get("lyrebird_lang") == "en"


def test_default_when_no_signals(client):
    # TestClient may carry cookies from prior tests; ensure clean
    client.cookies.clear()
    r = client.get("/")
    # No query, no cookie, no accept-language → default zh
    assert r.cookies.get("lyrebird_lang") == "zh"
