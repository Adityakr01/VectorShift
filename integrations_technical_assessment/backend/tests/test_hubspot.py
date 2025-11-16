
import pytest
from unittest.mock import patch
from integrations import hubspot

@pytest.fixture
def expired_token():
    return {
        "access_token": "expired",
        "refresh_token": "refresh-token-123",
        "expires_at": 0
    }

def test_refresh_access_token(monkeypatch, expired_token):
    def mock_post(url, data=None, headers=None):
        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600
                }
        return MockResp()
    monkeypatch.setattr(hubspot.requests, "post", mock_post)
    refreshed = hubspot._refresh_access_token_if_needed(expired_token)
    assert refreshed["access_token"] == "new-access-token"
    assert refreshed["refresh_token"] == "new-refresh-token"
    assert refreshed["expires_at"] > 0

def test_fetch_all_objects(monkeypatch):
    # mock _call_hubspot_api returning two pages
    responses = [
        {"results": [{"id": "1"}, {"id": "2"}], "paging": {"next": {"after": "cursor1"}}},
        {"results": [{"id": "3"}], "paging": {}}
    ]
    def mock_call(path, access_token, params=None):
        return responses.pop(0)
    monkeypatch.setattr(hubspot, "_call_hubspot_api", mock_call)
    items = hubspot._fetch_all_objects("/crm/v3/objects/contacts", "token", properties="email", limit=2, max_pages=5)
    assert len(items) == 3

def test_get_items_hubspot_handles_missing_creds(monkeypatch):
    # Ensure missing credentials raise
    with pytest.raises(Exception):
        hubspot.get_hubspot_credentials_for_user(user_id="nonexistent_user")

