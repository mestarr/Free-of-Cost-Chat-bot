import pytest

from backend.accounts import create_api_key, init_db, usage_summary, verify_api_key


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "acct.sqlite"
    monkeypatch.setenv("CCP_ACCOUNTS_DB", str(path))
    init_db()
    yield str(path)


def test_create_verify_usage(isolated_db):
    kid, raw = create_api_key(label="pytest")
    assert kid
    assert raw.startswith("ccp_sk_")
    assert verify_api_key(raw) == kid
    assert verify_api_key("wrong") is None
    s = usage_summary(kid, last_days=7)
    assert s["key_id"] == kid
    assert s["label"] == "pytest"
    assert isinstance(s["by_day"], dict)
