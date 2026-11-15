from test_foundation import system
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

from clueshelf.youtube_auth import CALLBACK, SCOPE, Settings


def test_youtube_routes_use_local_write_guard_and_no_store(system, monkeypatch, tmp_path):
    client, _ = system
    monkeypatch.setenv("CLUESHELF_GOOGLE_CLIENT_FILE", str(tmp_path / "missing-client.json"))
    status = client.get("/api/v1/youtube/status")
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["configured"] is False
    assert status.json()["connection"] is None
    assert client.post("/api/v1/youtube/oauth/start").status_code == 503
    for endpoint in ("oauth/start", "sync", "sync/cancel", "disconnect"):
        response = client.post(f"/api/v1/youtube/{endpoint}", headers={"Origin": "https://external.example", "Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403


def test_invalid_callback_redirects_without_forwarding_secrets(system):
    client, _ = system
    response = client.get("/api/v1/youtube/oauth/callback?state=invalid&code=must-not-forward", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["location"] == "http://127.0.0.1:3000/?youtube=error"
    assert "must-not-forward" not in response.text


def test_official_oauth_library_emits_readonly_s256_pkce(tmp_path, monkeypatch):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"web": {
        "client_id": "test.apps.googleusercontent.com", "client_secret": "fixture-only",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [CALLBACK],
    }}), encoding="utf-8")
    monkeypatch.setenv("CLUESHELF_GOOGLE_CLIENT_FILE", str(path))
    flow = Settings.load().flow(state="one-time-state")
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == [SCOPE]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["code_challenge_method"] == ["S256"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(flow.code_verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert query["state"] == ["one-time-state"]
