"""Bootstrap: dump one of MY Spotify playlists to inbox/<name>.json (read-only).
Usage:  python pull_spotify.py "funk_109_bpm"      (or a playlist URL / ID)
Needs:  .env with SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. Stdlib only.
"""
import base64
import http.server
import json
import pathlib
import re
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
API = "https://api.spotify.com/v1"


def env():
    pairs = (l.split("=", 1) for l in pathlib.Path(".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
    return {k.strip(): v.strip().strip('"') for k, v in pairs}


def call(url, token=None, data=None, basic=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None)
    req.add_header("Authorization", f"Basic {basic}" if basic else f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def login(cid, secret):
    state, got = secrets.token_urlsafe(16), {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200); self.end_headers(); self.wfile.write(b"Done. Close this tab.")
        def log_message(self, *a): pass

    q = urllib.parse.urlencode({"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES, "state": state})
    webbrowser.open(f"https://accounts.spotify.com/authorize?{q}")
    http.server.HTTPServer(("127.0.0.1", 8888), H).handle_request()
    assert got.get("state", [""])[0] == state, "state mismatch"
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    body = {"grant_type": "authorization_code", "code": got["code"][0], "redirect_uri": REDIRECT}
    return call("https://accounts.spotify.com/api/token", data=body, basic=basic)["access_token"]


def pages(url, token):
    while url:
        if not url.startswith(API + "/"):  # `next` comes from the response: token stays on api.spotify.com
            sys.exit(f"Refusing to send the token to {url.split('?')[0]}")
        page = call(url, token)
        yield from page.get("items", [])
        url = page.get("next")


def flatten(rows):
    out = []
    for row in rows:
        t = row.get("item") or row.get("track")  # Feb 2026 rename: track -> item
        if not t or t.get("type", "track") != "track":
            continue
        out.append({"uri": t.get("uri"), "title": t.get("name"),
                    "artists": [a.get("name") for a in t.get("artists", [])],
                    "album": (t.get("album") or {}).get("name"),
                    "duration_ms": t.get("duration_ms"),
                    "isrc": (t.get("external_ids") or {}).get("isrc"),
                    "added_at": row.get("added_at")})
    return out


def find_playlist(arg, token):
    m = re.search(r"(?:playlist[/:])?([A-Za-z0-9]{22})$", arg.split("?")[0])
    if m:
        return m.group(1), arg
    for p in pages(f"{API}/me/playlists?limit=50", token):
        if p and p.get("name", "").lower() == arg.lower():
            return p["id"], p["name"]
    sys.exit(f"No playlist of mine called {arg!r}")


if __name__ == "__main__":
    e = env()
    token = login(e["SPOTIFY_CLIENT_ID"], e["SPOTIFY_CLIENT_SECRET"])
    pid, name = find_playlist(sys.argv[1], token)
    tracks = flatten(pages(f"{API}/playlists/{pid}/items?limit=50", token))
    out = pathlib.Path("inbox") / (re.sub(r"[^\w.-]+", "_", name) + ".json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"playlist_id": pid, "name": name, "tracks": tracks}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(tracks)} tracks -> {out}")
