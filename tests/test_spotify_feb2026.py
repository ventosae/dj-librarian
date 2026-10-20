"""R-804, R-805, C-06: every Spotify flow on the February 2026 endpoints, through the real
client and a MockTransport; and `dj build` / `dj push` dry-runs for any DJ with their own app.

The fake server answers only the endpoints docs/spotify-audit.md lists as in use. A removed
endpoint (batch fetches, other users' endpoints, /playlists/{id}/tracks, audio features), a
search limit over 10, another host or a missing bearer token fails the test. No network.
"""

from __future__ import annotations

import importlib.util
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner
from xml_fixtures import fake_db

from dj import analyze, cli, intake, push, safety, spotify
from dj import build as build_mod
from dj.spotify import API, Spotify, SpotifyError

runner = CliRunner()
REAL_SPOTIFY = spotify.Spotify
TOKEN = "tok-any-dj"
SECRET = "invented-secret-never-printed"
OWN_PLAYLIST = "0wnPl4yl1st0fTheDJ00aa"  # 22 characters, invented

# Spotify's copies of fixture tracks 8, 9, 10 and 11 (tests/xml_fixtures.py); 21 is not on Spotify.
CATALOG = [
    {"uri": "spotify:track:s8", "name": "Hallway Light", "artists": ["Marlo Venn"], "ms": 476_000},
    {"uri": "spotify:track:s9", "name": "Open Plan", "artists": ["Tessa Quorum"], "ms": 213_000, "isrc": "ZZA011700009"},
    {"uri": "spotify:track:s10", "name": "Concrete Garden", "artists": ["Dub Atelier"], "ms": 250_000},
    {"uri": "spotify:track:s11", "name": "Stairwell Echo", "artists": ["Marlo Venn"], "ms": 287_000},
]
# path templates the code may call (docs/spotify-audit.md, status ok / degraded)
ALLOWED = {
    ("GET", "/v1/search"), ("GET", "/v1/me"), ("GET", "/v1/me/playlists"), ("POST", "/v1/me/playlists"),
    ("GET", "/v1/playlists/{id}/items"), ("POST", "/v1/playlists/{id}/items"), ("GET", "/v1/me/tracks"),
    ("GET", "/v1/me/albums"), ("GET", "/v1/me/following"), ("GET", "/v1/me/top/{kind}"),
}


def removed_endpoint(path: str) -> str | None:
    if path in ("/v1/tracks", "/v1/artists", "/v1/albums"):
        return "batch fetch (removed Feb 2026)"
    if path.startswith("/v1/users/"):
        return "another user's endpoint (removed Feb 2026)"
    if re.fullmatch(r"/v1/playlists/[^/]+/tracks", path):
        return "/playlists/{id}/tracks (renamed /items Feb 2026)"
    if path.startswith(("/v1/audio-features", "/v1/audio-analysis", "/v1/recommendations")):
        return "closed to new apps (Nov 2024)"
    if path.endswith(("/related-artists", "/top-tracks")):
        return "closed to new apps"
    return None


def template(path: str) -> str:
    path = re.sub(r"^/v1/playlists/[^/]+/", "/v1/playlists/{id}/", path)
    return re.sub(r"^/v1/me/top/(artists|tracks)$", "/v1/me/top/{kind}", path)


def track_json(t: dict) -> dict:
    out = {"type": "track", "uri": t["uri"], "id": t["uri"].rsplit(":", 1)[-1], "name": t["name"],
           "duration_ms": t["ms"], "artists": [{"id": f"a_{a}", "name": a} for a in t["artists"]],
           "album": {"id": "al", "name": "Album", "release_date": "2020"},
           "external_urls": {"spotify": "https://open.spotify.com/track/" + t["uri"].rsplit(":", 1)[-1]}}
    if t.get("isrc"):
        out["external_ids"] = {"isrc": t["isrc"]}
    return out


class Server:
    """A Spotify that knows the endpoints in use and nothing else."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.items: dict[str, list[str]] = {OWN_PLAYLIST: ["spotify:track:s9", "spotify:track:s10"]}
        self.created = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url, method, path = request.url, request.method, request.url.path
        assert (url.scheme, url.host) == ("https", "api.spotify.com"), "token sent off api.spotify.com"
        assert request.headers.get("Authorization") == f"Bearer {TOKEN}"
        assert removed_endpoint(path) is None, f"{method} {path}: {removed_endpoint(path)}"
        assert (method, template(path)) in ALLOWED, f"{method} {path} is not in the audit"
        if path == "/v1/search":
            assert int(url.params["limit"]) <= 10, "search limit over 10 (C-06)"
            q = url.params["q"].casefold()
            hits = [track_json(t) for t in CATALOG if t["name"].casefold() in q or (t.get("isrc") or "?").casefold() in q]
            return httpx.Response(200, json={"tracks": {"items": hits[: int(url.params["limit"])]}})
        if path == "/v1/me":
            return httpx.Response(200, json={"id": "dj_user", "display_name": "A DJ"})
        if path == "/v1/me/playlists" and method == "GET":
            return httpx.Response(200, json={"items": [{"id": OWN_PLAYLIST, "name": "my_inbox",
                                                        "owner": {"id": "dj_user"}}], "next": None})
        if path == "/v1/me/playlists":
            body = json.loads(request.content)
            assert body["public"] is False, "playlists are created private"
            self.created += 1
            pid = f"new{self.created:019d}"
            self.items[pid] = []
            return httpx.Response(201, json={"id": pid, "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}})
        found = re.fullmatch(r"/v1/playlists/([^/]+)/items", path)
        if found and method == "GET":
            by_uri = {t["uri"]: t for t in CATALOG}
            rows = [{"added_at": "2026-10-01T00:00:00Z", "item": track_json(by_uri[u])}
                    for u in self.items[found.group(1)]]
            return httpx.Response(200, json={"items": rows, "next": None})
        if found:
            self.items[found.group(1)] += json.loads(request.content)["uris"]
            return httpx.Response(201, json={"snapshot_id": "s"})
        if path in ("/v1/me/tracks", "/v1/me/albums"):
            return httpx.Response(200, json={"items": [], "next": None})
        if path == "/v1/me/following":
            return httpx.Response(200, json={"artists": {"items": [], "next": None}})
        return httpx.Response(200, json={"items": []})  # /v1/me/top/{kind}

    def used(self) -> set[tuple[str, str]]:
        return {(r.method, template(r.url.path)) for r in self.requests}

    def writes(self) -> list[tuple[str, str]]:
        return [(r.method, template(r.url.path)) for r in self.requests if r.method != "GET"]


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def api(server):
    return Spotify(TOKEN, httpx.Client(transport=httpx.MockTransport(server)))


def crate_db():
    """The synthetic library with Content on every playlist entry (what `dj push` reads)."""
    db = fake_db(deleted=False)
    by_id = {c.ID: c for c in db.contents}
    for row in db.playlists:
        for song in row.Songs:
            song.Content = by_id[song.ContentID]
    return db


# -- R-804: the flows on the Feb 2026 endpoints ----------------------------------------------


def test_search_limit_is_capped_at_10(server, api):
    assert api.search_tracks("track:open plan artist:tessa quorum", limit=50)
    assert [r.url.params["limit"] for r in server.requests] == ["10"]


def test_playlist_items_come_from_items_rows_with_item(server, api, tmp_path):
    link = intake.Link("my_inbox", "House/1.1_warm_up")
    pulled = intake.pull(api, link, intake.Paths(tmp_path))
    assert pulled["tracks"] == 2
    inbox = json.loads((tmp_path / "inbox" / f"{link.slug}.json").read_text(encoding="utf-8"))
    assert [t["uri"] for t in inbox["tracks"]] == ["spotify:track:s9", "spotify:track:s10"]
    assert inbox["tracks"][0]["isrc"] == "ZZA011700009" and inbox["tracks"][1]["isrc"] is None
    paths = [r.url.path for r in server.requests]
    assert paths == ["/v1/me/playlists", f"/v1/playlists/{OWN_PLAYLIST}/items"]


def test_normal_flows_call_no_removed_endpoint(server, api, tmp_path):
    # dj pull
    intake.pull(api, intake.Link("my_inbox", "House/1.1_warm_up"), intake.Paths(tmp_path))
    # dj push, twice: create once, then add only what is missing
    row = push.find_playlist(crate_db(), "House/1.1_warm_up")
    results = [push.match_track(api, t) for t in push.local_tracks(row)]
    uris = push.selected_uris(results, include_ambiguous=False)
    assert [r.status for r in results] == ["MATCH", "MISSING", "MATCH", "MATCH"]  # 8, 21, 10, 11
    state = tmp_path / "state" / "push.json"
    first = push.apply(api, str(row.ID), "warm up", uris, state)
    again = push.apply(api, str(row.ID), "warm up", uris, state)
    assert (first["created"], first["added"], again["created"], again["added"]) == (True, 3, False, 0)
    # dj build
    tracks, _ = build_mod.parse_tracklist("Marlo Venn - Hallway Light\nNobody Here - Not On Spotify\n")
    built = build_mod.match_all(api, tracks)
    assert [r.status for r in built] == ["MATCH", "MISSING"]
    build_mod.apply(api, "saturday", push.selected_uris(built, False), tmp_path / "state" / "build.json")
    # dj analyze
    analyze.pull(api, tmp_path / "library")

    assert server.used() <= ALLOWED  # every call is one the audit lists (the server checks each)
    assert ("GET", "/v1/playlists/{id}/items") in server.used()
    # Spotify side: create (private) and add only. Never PUT or DELETE (hard rule 1).
    assert set(server.writes()) == {("POST", "/v1/me/playlists"), ("POST", "/v1/playlists/{id}/items")}


def test_an_old_track_row_still_reads_but_item_wins(api):
    rows = [{"item": {"uri": "u1", "type": "track", "name": "A"}, "track": {"uri": "old"}},
            {"track": {"uri": "u2", "name": "B"}}]
    assert [t["uri"] for t in intake.flatten(rows)] == ["u1", "u2"]


def test_a_refused_playlist_is_a_plain_intake_error(tmp_path):
    def handler(request):
        if request.url.path == "/v1/me/playlists":
            return httpx.Response(200, json={"items": [{"id": OWN_PLAYLIST, "name": "theirs"}]})
        return httpx.Response(403, json={"error": {"status": 403}})

    api = Spotify(TOKEN, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(intake.IntakeError, match="own or collaborate on") as info:
        intake.pull(api, intake.Link("theirs", "x"), intake.Paths(tmp_path))
    assert TOKEN not in str(info.value)
    # other errors are not dressed up
    api = Spotify(TOKEN, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="x"))))
    with pytest.raises(SpotifyError, match="500"):
        intake.pull(api, intake.Link(OWN_PLAYLIST, "x"), intake.Paths(tmp_path))


def test_a_404_playlist_names_both_causes_and_both_fixes(tmp_path):
    # a 22-character ID is taken as given: a deleted or mistyped one answers 404, and so may
    # a playlist the app may not read. The message must not claim it is "not yours".
    api = Spotify(TOKEN, httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(404, json={"error": {"status": 404}}))))
    with pytest.raises(intake.IntakeError) as info:
        intake.pull(api, intake.Link(OWN_PLAYLIST, "x"), intake.Paths(tmp_path))
    message = str(info.value)
    assert "(404)" in message and "does not exist" in message and "not read" in message
    assert "fix the link in links.yaml" in message and "own or collaborate on" in message
    assert "will not let this app read" not in message  # that is the 403 wording
    assert not (tmp_path / "inbox").exists()


@pytest.mark.parametrize(("text", "code"), [
    ("GET https://api.spotify.com/v1/playlists/x/items -> 403 Forbidden", 403),
    ("GET https://api.spotify.com/v1/playlists/x/items -> 404 x", 404),
    ("GET https://api.spotify.com/v1/playlists/x/items -> 500 x", None),
    ("GET https://api.spotify.com/v1/playlists/x403/items failed: ConnectError", None),
    ("GET https://api.spotify.com/v1/playlists/x/items -> 4040 x", None),
])
def test_one_refusal_test_for_pull_and_analyze(text, code):
    assert spotify.refused_status(SpotifyError(text)) == code
    assert spotify.refused_status(RuntimeError("-> 403")) is None  # only the client's errors


def test_the_client_has_no_method_for_a_removed_endpoint():
    assert not any(hasattr(Spotify, name) for name in ("artists", "tracks", "albums", "audio_features",
                                                      "user_playlists"))
    assert API == "https://api.spotify.com/v1"


def test_the_bootstrap_script_keeps_the_token_on_api_spotify_com(monkeypatch):
    # pull_spotify.py (stdlib bootstrap) follows `next` links from the response body: rule 6
    path = Path(__file__).resolve().parents[1] / "pull_spotify.py"
    spec = importlib.util.spec_from_file_location("pull_spotify_bootstrap", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)  # top level only: no login, no request
    seen = []

    def call(url, token=None, data=None, basic=None):
        seen.append(url)
        return {"items": [{"id": "a"}], "next": "https://elsewhere.example/v1/me/playlists?offset=50"}

    monkeypatch.setattr(script, "call", call)
    with pytest.raises(SystemExit, match="Refusing to send the token to https://elsewhere.example"):
        list(script.pages(f"{script.API}/me/playlists?limit=50", TOKEN))
    assert seen == [f"{script.API}/me/playlists?limit=50"]
    assert script.API == API


# -- R-805: dj build and dj push for any DJ with their own app --------------------------------


@pytest.fixture
def own_app(tmp_path, monkeypatch, server):
    """A DJ's own .env and a cached read-scope token in a tmp folder. No login, no refresh."""
    (tmp_path / ".env").write_text(f"SPOTIFY_CLIENT_ID=invented-client-id\nSPOTIFY_CLIENT_SECRET={SECRET}\n",
                                   encoding="utf-8")
    cache = tmp_path / ".cache" / "spotify_token.json"
    cache.parent.mkdir()
    cache.write_text(json.dumps({"access_token": TOKEN, "scope": " ".join(spotify.READ_SCOPES),
                                 "expires_at": time.time() + 600}), encoding="utf-8")
    monkeypatch.setattr(spotify, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(spotify, "TOKEN_CACHE", cache)
    logins = []

    def login(env, scopes):
        logins.append(scopes)
        raise SpotifyError("Spotify login refused: access_denied")  # the DJ closed the consent tab

    monkeypatch.setattr(spotify, "_login", login)
    monkeypatch.setattr(spotify, "_token_request", lambda *a: pytest.fail("no refresh expected"))
    client = httpx.Client(transport=httpx.MockTransport(server))
    monkeypatch.setattr(spotify, "Spotify", lambda token: REAL_SPOTIFY(token, client))
    monkeypatch.setattr(build_mod, "STATE_FILE", tmp_path / "state" / "build.json")
    monkeypatch.setattr(push, "STATE_FILE", tmp_path / "state" / "push.json")
    monkeypatch.setattr(push, "REPORT_DIR", tmp_path / "reports")
    return logins


@pytest.fixture
def tracklist(tmp_path):
    path = tmp_path / "saturday.txt"
    path.write_text("Tracklisting\n01. Marlo Venn - Hallway Light\n02. Tessa Quorum - Open Plan\n"
                    "03. Nobody Here - Not On Spotify\n", encoding="utf-8")
    return path


def test_build_dry_run_works_with_the_djs_own_app(own_app, server, tracklist, tmp_path):
    result = runner.invoke(cli.app, ["build", str(tracklist), "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert (out["applied"], out["selected"]) == (False, 2)
    assert out["counts"] == {"MATCH": 2, "AMBIGUOUS": 0, "MISSING": 1}
    assert server.writes() == [] and own_app == []  # nothing written, no new consent needed
    assert not (tmp_path / "state").exists() and not (tmp_path / "reports").exists()
    assert SECRET not in result.output and TOKEN not in result.output


def test_push_dry_run_works_with_the_djs_own_app(own_app, server, monkeypatch, tmp_path):
    sessions = []

    @contextmanager
    def fake_open_db(write=False, db_path=None):
        sessions.append(write)
        yield crate_db()

    monkeypatch.setattr(safety, "open_db", fake_open_db)
    result = runner.invoke(cli.app, ["push", "House/1.1_warm_up", "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert (out["applied"], out["selected"]) == (False, 3)
    assert out["counts"] == {"MATCH": 3, "AMBIGUOUS": 0, "MISSING": 1}
    assert sessions == [False] and server.writes() == [] and own_app == []
    assert SECRET not in result.output and TOKEN not in result.output


def test_a_real_write_needs_the_write_scope_consent_first(own_app, server, tracklist, tmp_path):
    dry = runner.invoke(cli.app, ["build", str(tracklist), "--json"])  # the preview (W-21 gate)
    assert dry.exit_code == 0, dry.output
    pid = json.loads(dry.output)["preview_id"]
    result = runner.invoke(cli.app, ["build", str(tracklist), "--apply", "--preview-id", pid, "--json"])
    assert result.exit_code == cli.EXIT_ERROR and "access_denied" in result.output
    assert own_app == [spotify.WRITE_SCOPES]  # the browser consent for playlist-modify-private
    # matching ran with the read scopes (W-21); the consent tab came before any write request
    assert server.writes() == [] and not (tmp_path / "state").exists()


# -- R-801: the guided setup card in plugin/skills/dj-spotify/SKILL.md --------------------------

SPOTIFY_SKILL = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "dj-spotify" / "SKILL.md"


def test_the_setup_card_matches_what_the_code_needs():
    """R-801: Premium, their own app, the redirect URI the login uses, the two .env keys the code
    reads (only in .env, never in the chat), and `dj pull` as the proof; scopes as the code asks."""
    text = SPOTIFY_SKILL.read_text(encoding="utf-8").replace("\r\n", "\n")
    card = re.search(r"^## Setup card: about \d+ minutes\n(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL).group(1)
    steps = re.findall(r"^(\d)\. \*\*(.+?)\*\*", card, re.MULTILINE)
    assert [n for n, _ in steps] == ["1", "2", "3", "4", "5"]
    titles = [title for _, title in steps]
    assert titles[0].startswith("Premium") and titles[1].startswith("Your own app")
    assert titles[2].startswith("Two keys into `.env`") and titles[4].startswith("Proof")
    assert f"`{spotify.REDIRECT}`" in card and "not `localhost`" in card
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        assert f"`{key}=`" in card
        assert f"{key}=" in (SPOTIFY_SKILL.parents[3] / "examples" / ".env.example").read_text(encoding="utf-8")
    assert "Never into the chat" in card and "treat it as leaked" in card
    assert "`dj pull <link>`" in card and "`dj_pull(link)`" in card
    scopes = text.split("## Permissions (scopes)", 1)[1].split("\n## ", 1)[0]
    read = set(re.findall(r"`(playlist-read-[a-z]+)`", scopes))
    assert read == set(spotify.READ_SCOPES) and "the first pull asks for these two" in scopes
    assert set(spotify.WRITE_SCOPES) - set(spotify.READ_SCOPES) == {"playlist-modify-private"}
    assert "`playlist-modify-private`: only for `dj push --apply` and `dj build --apply`" in scopes
