"""Spotify Web API client. Endpoints verified against the live reference (2026-09):

  GET  /v1/search                 limit max 10, filters isrc: track: artist:
  GET  /v1/me/playlists
  GET  /v1/playlists/{id}/items   (was /tracks; rows carry `item`, formerly `track`)
  POST /v1/me/playlists           (POST /users/{id}/playlists was removed)
  POST /v1/playlists/{id}/items   max 100 uris per request
  GET  /v1/me                     (dj analyze, read-only)
  GET  /v1/me/tracks              Liked Songs, limit max 50
  GET  /v1/me/albums              limit max 50
  GET  /v1/me/following?type=artist   cursor paging, page sits under "artists"
  GET  /v1/me/top/{artists|tracks}    time_range short|medium|long_term
  GET  /v1/artists?ids=           max 50 ids; answers 403 to this app (2026-09), single
                                  GET /v1/artists/{id} still works but carries no genres.
                                  Track popularity comes back empty as well.

Credentials come from .env and are never printed. The token cache lives in .cache/.
"""

from __future__ import annotations

import http.server
import json
import secrets
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Iterator

import httpx

from dj.safety import REPO_ROOT

API = "https://api.spotify.com/v1"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT = "http://127.0.0.1:8888/callback"  # must be 127.0.0.1, not localhost
READ_SCOPES = ("playlist-read-private", "playlist-read-collaborative")
WRITE_SCOPES = READ_SCOPES + ("playlist-modify-private",)
# dj analyze only. All read-only; approved by the user on 2026-09-22.
LIBRARY_SCOPES = READ_SCOPES + ("user-library-read", "user-follow-read", "user-top-read")
TOKEN_CACHE = REPO_ROOT / ".cache" / "spotify_token.json"
LOGIN_TIMEOUT_S = 180
MAX_RETRY_WAIT_S = 30


class SpotifyError(RuntimeError):
    pass


def load_env(path: Path | None = None) -> dict[str, str]:
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        raise SpotifyError(f"{path.name} not found. Copy examples/.env.example to .env and fill it in.")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if not env.get(key):
            raise SpotifyError(f"{key} is empty in {path.name}.")
    return env


# -- auth --------------------------------------------------------------------------------


def _token_request(env: dict[str, str], body: dict[str, str]) -> dict[str, Any]:
    auth = (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"])
    try:
        response = httpx.post(TOKEN_URL, data=body, auth=auth, timeout=30)
    except httpx.HTTPError as exc:
        raise SpotifyError(f"Spotify token request failed: {type(exc).__name__}") from None
    if response.status_code != 200:
        # The body of a token error holds no secret, only an error code.
        raise SpotifyError(f"Spotify token request failed: {response.status_code} {response.text}")
    return response.json()


def _login(env: dict[str, str], scopes: tuple[str, ...]) -> dict[str, Any]:
    """Authorization Code flow. Opens one browser tab, waits for the redirect."""
    state, got = secrets.token_urlsafe(16), {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"dj-librarian: done. You can close this tab.")

        def log_message(self, *args: Any) -> None:
            pass

    query = urllib.parse.urlencode(
        {
            "client_id": env["SPOTIFY_CLIENT_ID"],
            "response_type": "code",
            "redirect_uri": REDIRECT,
            "scope": " ".join(scopes),
            "state": state,
        }
    )
    server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
    server.timeout = LOGIN_TIMEOUT_S
    try:
        if not webbrowser.open(f"{AUTHORIZE_URL}?{query}"):
            raise SpotifyError("Could not open a browser for the Spotify login.")
        server.handle_request()
    finally:
        server.server_close()
    if "error" in got:
        raise SpotifyError(f"Spotify login refused: {got['error'][0]}")
    if "code" not in got:
        raise SpotifyError(f"No Spotify login within {LOGIN_TIMEOUT_S}s.")
    if got.get("state", [""])[0] != state:
        raise SpotifyError("Spotify login: state mismatch.")
    body = {"grant_type": "authorization_code", "code": got["code"][0], "redirect_uri": REDIRECT}
    return _token_request(env, body)


def get_token(scopes: tuple[str, ...], cache: Path | None = None) -> str:
    """A valid access token with at least `scopes`: cache -> refresh -> browser login."""
    cache = cache or TOKEN_CACHE
    env = load_env()
    saved: dict[str, Any] = {}
    if cache.is_file():
        saved = json.loads(cache.read_text(encoding="utf-8"))
    covered = set(scopes) <= set(saved.get("scope", "").split())

    if covered and saved.get("expires_at", 0) > time.time() + 60:
        return saved["access_token"]
    if covered and saved.get("refresh_token"):
        fresh = _token_request(
            env, {"grant_type": "refresh_token", "refresh_token": saved["refresh_token"]}
        )
        fresh.setdefault("refresh_token", saved["refresh_token"])
        fresh.setdefault("scope", saved["scope"])
    else:
        fresh = _login(env, scopes)
    fresh["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(fresh), encoding="utf-8")
    return fresh["access_token"]


# -- api ---------------------------------------------------------------------------------


class Spotify:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self._http = client or httpx.Client(timeout=30)
        self._headers = {"Authorization": f"Bearer {token}"}

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if not url.startswith("http"):
            url = API + url
        if not url.startswith(API + "/"):
            # `next` links come from the response body: never send the token elsewhere.
            raise SpotifyError(f"Refusing to call a non-Spotify URL: {url.split('?')[0]}")
        for _ in range(4):
            try:
                response = self._http.request(method, url, headers=self._headers, **kwargs)
            except httpx.HTTPError as exc:
                raise SpotifyError(f"{method} {url.split('?')[0]} failed: {type(exc).__name__}") from None
            if response.status_code != 429:
                break
            time.sleep(min(int(response.headers.get("Retry-After", "2")) + 1, MAX_RETRY_WAIT_S))
        if response.status_code >= 400:
            raise SpotifyError(f"{method} {url.split('?')[0]} -> {response.status_code} {response.text[:300]}")
        return response.json() if response.content else {}

    def _pages(self, url: str, **params: Any) -> Iterator[dict[str, Any]]:
        while url:
            page = self._request("GET", url, params=params or None)
            yield from page.get("items") or []
            url, params = page.get("next"), {}

    def search_tracks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        params = {"q": query, "type": "track", "limit": min(limit, 10)}
        page = self._request("GET", "/search", params=params)
        return [t for t in (page.get("tracks") or {}).get("items") or [] if t]

    def my_playlists(self) -> Iterator[dict[str, Any]]:
        return (p for p in self._pages("/me/playlists", limit=50) if p)

    def playlist_items(self, playlist_id: str) -> Iterator[dict[str, Any]]:
        return self._pages(f"/playlists/{playlist_id}/items", limit=50)

    def playlist_item_uris(self, playlist_id: str) -> list[str]:
        uris = []
        for row in self.playlist_items(playlist_id):
            item = row.get("item") or row.get("track")  # Feb 2026 rename: track -> item
            if item and item.get("uri"):
                uris.append(item["uri"])
        return uris

    # -- read-only library views for `dj analyze` ------------------------------------

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def saved_tracks(self) -> Iterator[dict[str, Any]]:
        """Liked Songs rows: {added_at, track}."""
        return self._pages("/me/tracks", limit=50)

    def saved_albums(self) -> Iterator[dict[str, Any]]:
        """Saved album rows: {added_at, album}."""
        return self._pages("/me/albums", limit=50)

    def followed_artists(self) -> Iterator[dict[str, Any]]:
        url: str | None = "/me/following"
        params: dict[str, Any] = {"type": "artist", "limit": 50}
        while url:
            page = self._request("GET", url, params=params or None).get("artists") or {}
            yield from (a for a in page.get("items") or [] if a)
            url, params = page.get("next"), {}

    def top_items(self, kind: str, time_range: str) -> list[dict[str, Any]]:
        """kind: artists|tracks. time_range: short_term|medium_term|long_term. One page of 50."""
        params = {"time_range": time_range, "limit": 50}
        page = self._request("GET", f"/me/top/{kind}", params=params)
        return [x for x in page.get("items") or [] if x]

    def artists(self, ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for start in range(0, len(ids), 50):
            params = {"ids": ",".join(ids[start : start + 50])}
            page = self._request("GET", "/artists", params=params)
            out.extend(a for a in page.get("artists") or [] if a)
        return out

    def create_playlist(self, name: str, description: str = "") -> dict[str, Any]:
        body = {"name": name, "public": False, "description": description}
        return self._request("POST", "/me/playlists", json=body)

    def add_items(self, playlist_id: str, uris: list[str]) -> None:
        for start in range(0, len(uris), 100):
            body = {"uris": uris[start : start + 100]}
            self._request("POST", f"/playlists/{playlist_id}/items", json=body)
