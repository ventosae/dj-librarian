import json
import os
import stat
import time

import httpx
import pytest

from dj import spotify
from dj.spotify import API, Spotify, SpotifyError

SECRET = "s3cr3t-value-never-print"


def client(handler):
    return Spotify("tok", httpx.Client(transport=httpx.MockTransport(handler)))


def test_bearer_token_is_sent_and_search_limit_is_capped():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["limit"] = request.url.params["limit"]
        return httpx.Response(200, json={"tracks": {"items": [{"uri": "u"}, None]}})

    assert client(handler).search_tracks("isrc:X", limit=50) == [{"uri": "u"}]
    assert seen == {"auth": "Bearer tok", "limit": "10"}


def test_pagination_follows_next_and_accepts_item_or_track():
    pages = {
        f"{API}/playlists/p/items?limit=50": {"items": [{"item": {"uri": "u1"}}], "next": f"{API}/playlists/p/items?offset=50"},
        f"{API}/playlists/p/items?offset=50": {"items": [{"track": {"uri": "u2"}}, {"item": None}], "next": None},
    }
    api = client(lambda r: httpx.Response(200, json=pages[str(r.url)]))
    assert api.playlist_item_uris("p") == ["u1", "u2"]


def test_token_is_never_sent_to_a_foreign_next_link():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"items": [], "next": "https://evil.example/v1/steal"})

    with pytest.raises(SpotifyError, match="non-Spotify"):
        list(client(handler).my_playlists())
    assert calls == ["api.spotify.com"]


def test_add_items_in_chunks_of_100_and_playlist_is_private():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "pl", "snapshot_id": "s"})

    api = client(handler)
    api.create_playlist("name")
    api.add_items("pl", [f"u{i}" for i in range(250)])
    assert bodies[0]["public"] is False
    assert [len(b["uris"]) for b in bodies[1:]] == [100, 100, 50]


def test_rate_limit_is_retried_then_errors_are_raised(monkeypatch):
    waits, replies = [], [httpx.Response(429, headers={"Retry-After": "900"}), httpx.Response(200, json={"items": []})]
    monkeypatch.setattr(time, "sleep", waits.append)
    assert list(client(lambda r: replies.pop(0)).my_playlists()) == []
    assert waits == [spotify.MAX_RETRY_WAIT_S]
    with pytest.raises(SpotifyError, match="404"):
        client(lambda r: httpx.Response(404, json={"error": "x"})).playlist_item_uris("gone")


def test_network_error_message_holds_no_token():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(SpotifyError) as info:
        client(handler).search_tracks("q")
    assert "tok" not in str(info.value) and info.value.__cause__ is None


# -- credentials and the token cache -----------------------------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "REPO_ROOT", tmp_path)
    (tmp_path / ".env").write_text(f'# c\nSPOTIFY_CLIENT_ID=cid\nSPOTIFY_CLIENT_SECRET="{SECRET}"\n')
    return tmp_path / ".cache" / "token.json"


def save(cache, **token):
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(token))


def test_env_errors_do_not_echo_values(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "REPO_ROOT", tmp_path)
    with pytest.raises(SpotifyError, match="not found"):
        spotify.load_env()
    (tmp_path / ".env").write_text(f"SPOTIFY_CLIENT_ID=\nSPOTIFY_CLIENT_SECRET={SECRET}\n")
    with pytest.raises(SpotifyError) as info:
        spotify.load_env()
    assert SECRET not in str(info.value)


def test_valid_cached_token_needs_no_network(env):
    save(env, access_token="A", scope="playlist-read-private playlist-read-collaborative", expires_at=time.time() + 600)
    assert spotify.get_token(spotify.READ_SCOPES, env) == "A"


def test_expired_token_is_refreshed_and_keeps_its_refresh_token(env, monkeypatch):
    save(env, access_token="old", refresh_token="R", scope=" ".join(spotify.READ_SCOPES), expires_at=0)
    asked = []
    monkeypatch.setattr(spotify, "_token_request", lambda e, body: asked.append(body) or {"access_token": "new", "expires_in": 3600})
    assert spotify.get_token(spotify.READ_SCOPES, env) == "new"
    assert asked == [{"grant_type": "refresh_token", "refresh_token": "R"}]
    assert json.loads(env.read_text())["refresh_token"] == "R"


def test_the_token_cache_is_rewritten_in_full(env, monkeypatch):
    save(env, access_token="old", refresh_token="R", scope=" ".join(spotify.READ_SCOPES), expires_at=0,
         padding="x" * 500)  # a longer old file must not leave a tail behind
    monkeypatch.setattr(spotify, "_token_request", lambda e, body: {"access_token": "new", "expires_in": 3600})
    assert spotify.get_token(spotify.READ_SCOPES, env) == "new"
    saved = json.loads(env.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new" and saved["refresh_token"] == "R" and "padding" not in saved


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes; Windows keeps the profile's ACLs")
@pytest.mark.parametrize("old_mode", [None, 0o644])
def test_the_token_cache_is_readable_by_its_owner_only_on_posix(env, monkeypatch, old_mode):
    """macOS/Linux: the cache holds the refresh token; under a 0755 home a 0644 file is readable
    by every local account. New folder 0700, file 0600, also over an older, wider file."""
    old_umask = os.umask(0o022)  # the usual umask, restored below
    try:
        if old_mode is not None:
            save(env, access_token="old", refresh_token="R", scope=" ".join(spotify.READ_SCOPES), expires_at=0)
            env.chmod(old_mode)
        monkeypatch.setattr(spotify, "_token_request", lambda e, body: {"access_token": "new", "expires_in": 3600})
        monkeypatch.setattr(spotify, "_login", lambda e, scopes: {"access_token": "new", "scope": " ".join(scopes)})
        assert spotify.get_token(spotify.READ_SCOPES, env) == "new"
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    if old_mode is None:
        assert stat.S_IMODE(env.parent.stat().st_mode) == 0o700


def test_a_wider_scope_forces_a_new_login_never_a_silent_upgrade(env, monkeypatch):
    save(env, access_token="A", refresh_token="R", scope=" ".join(spotify.READ_SCOPES), expires_at=time.time() + 600)
    logins = []
    monkeypatch.setattr(spotify, "_login", lambda e, scopes: logins.append(scopes) or {"access_token": "W", "scope": " ".join(scopes)})
    assert spotify.get_token(spotify.WRITE_SCOPES, env) == "W"
    assert logins == [spotify.WRITE_SCOPES]


def test_token_endpoint_failure_does_not_leak_the_secret(env, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(SpotifyError) as info:
        spotify._token_request(spotify.load_env(), {"grant_type": "refresh_token"})
    assert SECRET not in str(info.value) and "invalid_client" in str(info.value)


def test_only_the_scopes_in_the_spec_are_ever_requested():
    assert set(spotify.WRITE_SCOPES) == {"playlist-read-private", "playlist-read-collaborative", "playlist-modify-private"}


def test_library_scopes_are_read_only():
    assert all("modify" not in s for s in spotify.LIBRARY_SCOPES)
    assert set(spotify.READ_SCOPES) <= set(spotify.LIBRARY_SCOPES)


def test_followed_artists_pages_under_artists_key_and_artists_batch_by_50():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if "/me/following" in str(request.url):
            if "after=" in str(request.url):
                return httpx.Response(200, json={"artists": {"items": [{"id": "b"}], "next": None}})
            return httpx.Response(200, json={"artists": {"items": [{"id": "a"}, None],
                                                         "next": f"{API}/me/following?type=artist&after=a"}})
        return httpx.Response(200, json={"artists": [{"id": i} for i in request.url.params["ids"].split(",")]})

    api = client(handler)
    assert [a["id"] for a in api.followed_artists()] == ["a", "b"]
    assert len(api.artists([f"x{i}" for i in range(120)])) == 120
    assert len([u for u in urls if "/artists?" in u]) == 3
