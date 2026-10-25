"""The one synthetic rekordbox library every test uses (W-11; W-14...W-18 analyse it).

ONE spec (`SPEC`) emits both
  (a) a rekordbox collection XML  -> `write_xml(path, spec)` / `to_xml(spec)`
  (b) an equivalent fake pyrekordbox master.db -> `fake_db(spec)` (+ `write_master_files`)
so `read_xml` and `read_db` can be compared field by field. Everything is invented: no real
artists, labels, paths or playlists.

What is in it (24 tracks):
- formats mp3 / flac / wav / aiff / m4a; bitrates 128, 192, 256, 320 and lossless
- years 1978...2024 across five decades, one unknown (0)
- BPM in three lanes: funk/disco 96-112, house 118-124, techno 126-132
- labels: Paper Lantern, Fathom Disc, Low Ceiling Records, Night Shift Tapes (+ some empty)
- genres Funk, Disco, Deep House, House, Techno (+ one empty), ratings 0-5, play counts,
  dates added 2019...2026, colours, comments with #tags, My Tags (master.db only)
- duplicate candidates: 8 = 22 and 17 = 23 (same artist + title, other file and format)
- one non-ASCII artist and path (4), paths with spaces, '&' and brackets, one NAS path (2)
- POSITION_MARK cues on 1, 9, 13, 17
Tree: 2 top-level folders (House, Gigs), one nested folder (House/Deep, depth 2), 8 plain
playlists incl. an empty one (empty_ideas), a dump (unsorted dump, 16 tracks), an overlapping
pair (1.2_peak / Gig 2025-03 Warehouse, Jaccard 5/9), naming styles `1.1_warm_up` and
`Gig 2025-03 Warehouse`, one KeyType=1 (Location keys) playlist in the XML (deep_rollers),
2 orphans (23, 24). The master.db fake also holds one smart playlist (All Techno: genre
contains Techno) that the XML cannot carry, plus soft-deleted rows the reader must ignore.
Its rule matches orphan 23 on purpose: master.db stores smart rules, not members, so on the db
side 23 stays an orphan (dj.readers.db.DB_NOTES).

Counts: XML `{tracks 24, folders 3, playlists 8, smart 0, orphans 2, entries 51}`; master.db
the same with `smart 1`. `read_xml(xml of SPEC).counts() == read_db(fake_db(without_smart(SPEC)))`
is the equality the tests check (the spec variant without the smart node).

Regenerate tests/fixtures/sample.xml with: `uv run python tests/xml_fixtures.py`.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from dj.readers.common import COLOUR_CODES, RATING_STEP, location_url

SAMPLE_XML = Path(__file__).parent / "fixtures" / "sample.xml"

KIND_TEXT = {"mp3": "MP3 File", "m4a": "M4A File", "flac": "FLAC File", "wav": "WAV File", "aiff": "AIFF File"}
FILE_TYPE = {"mp3": 1, "m4a": 4, "flac": 5, "wav": 11, "aiff": 12}  # pyrekordbox tables.FileType
LOSSLESS = {"flac", "wav", "aiff"}

# id, artist, title, genre, label, year, bpm, key, kind, bitrate, rating, colour, comment,
# date added, play count, cue count, my tags
_ROWS = [
    ("1", "Okoro Lane", "Sunday Sermon", "Funk", "Paper Lantern", 1978, 98.0, "Am", "mp3", 320, 4, "Orange", "#warmup #vocal", "2019-04-12", 14, 3, ("Warm Up", "Vocal")),
    ("2", "The Velvet Ferrymen", "Brass Tide", "Funk", "Paper Lantern", 1979, 101.5, "Dm", "flac", 917, 5, "Orange", "#warmup", "2019-04-12", 22, 0, ("Warm Up",)),
    ("3", "Cassia Drift", "Midnight Roller Rink", "Disco", "Fathom Disc", 1981, 108.0, "F#m", "mp3", 192, 3, "Pink", "", "2019-09-30", 5, 0, ()),
    ("4", "Jørn Ébène", "Søndag på Taget", "Disco", "Fathom Disc", 1983, 110.0, "C", "aiff", 1411, 4, "Pink", "#vocal #closer", "2020-02-02", 9, 0, ("Vocal", "Closer")),
    ("5", "Brother Ferro", "Pocket Change", "Funk", "", 1986, 96.0, "Gm", "mp3", 128, 2, "", "", "2020-07-19", 1, 0, ()),
    ("6", "Lumen Sato", "Glass Elevator", "Disco", "Fathom Disc", 1989, 112.0, "", "m4a", 256, 0, "", "#tbc", "2021-01-08", 0, 0, ()),
    ("7", "Halvard & Nim", "Slow Burn Social", "Funk", "Paper Lantern", 1992, 104.0, "Bbm", "wav", 1411, 3, "Yellow", "#warmup", "2021-05-23", 7, 0, ("Warm Up",)),
    ("8", "Marlo Venn", "Hallway Light", "Deep House", "Low Ceiling Records", 1995, 118.0, "Am", "mp3", 320, 4, "Green", "#warmup #deep", "2021-11-11", 18, 0, ("Warm Up", "Deep")),
    ("9", "Tessa Quorum", "Open Plan", "House", "Low Ceiling Records", 1997, 120.0, "Cm", "flac", 1024, 5, "Green", "#peak", "2022-03-03", 31, 8, ("Peak",)),
    ("10", "Dub Atelier", "Concrete Garden", "Deep House", "Low Ceiling Records", 1999, 121.0, "Fm", "mp3", 320, 4, "Aqua", "#deep", "2022-06-17", 12, 0, ("Deep",)),
    ("11", "Marlo Venn", "Stairwell Echo", "House", "Low Ceiling Records", 2003, 122.0, "Gm", "mp3", 320, 3, "Aqua", "#peak #vocal", "2022-08-29", 25, 0, ("Peak", "Vocal")),
    ("12", "Odelia Strand", "Night Bus Home", "House", "Night Shift Tapes", 2006, 122.5, "C#m", "mp3", 256, 4, "Blue", "#peak", "2023-01-15", 19, 0, ("Peak",)),
    ("13", "The Velvet Ferrymen", "Brass Tide (Club Edit)", "House", "Paper Lantern", 2009, 123.0, "Dm", "mp3", 320, 5, "Blue", "#peak #edit", "2023-04-04", 27, 4, ("Peak",)),
    ("14", "Tessa Quorum", "Floor Plan", "House", "Low Ceiling Records", 2012, 124.0, "Em", "wav", 2304, 4, "Green", "#peak", "2023-07-21", 16, 0, ("Peak",)),
    ("15", "Odelia Strand", "Last Train Social", "House", "Night Shift Tapes", 2014, 124.0, "Am", "mp3", 320, 3, "Purple", "", "2024-02-10", 8, 0, ()),
    ("16", "Kestrel Unit", "Ferrous", "Techno", "Night Shift Tapes", 2016, 126.0, "Fm", "mp3", 320, 4, "Red", "#peak #dark", "2024-05-05", 21, 0, ("Peak", "Dark")),
    ("17", "Grid Saint", "Pressure Vessel", "Techno", "Night Shift Tapes", 2018, 128.0, "Gm", "flac", 880, 5, "Red", "#peak", "2024-09-09", 33, 2, ("Peak",)),
    ("18", "Kestrel Unit", "Ballast", "Techno", "Night Shift Tapes", 2019, 129.0, "Am", "mp3", 256, 3, "Red", "#dark", "2025-01-20", 6, 0, ("Dark",)),
    ("19", "Volta Rook", "Signal Fire", "", "", 2020, 130.0, "Cm", "mp3", 192, 2, "", "", "2025-03-01", 4, 0, ()),
    ("20", "Grid Saint", "Cold Storage", "Techno", "Night Shift Tapes", 2021, 132.0, "Dm", "aiff", 1411, 4, "Purple", "#closer #dark", "2025-06-14", 10, 0, ("Closer", "Dark")),
    ("21", "Mira Kalt", "Late Sun Drive", "Deep House", "Low Ceiling Records", 2024, 119.0, "Bbm", "m4a", 256, 0, "", "#tbc", "2026-01-11", 0, 0, ()),
    ("22", "Marlo Venn", "Hallway Light", "Deep House", "Low Ceiling Records", 1995, 118.0, "Am", "flac", 951, 0, "", "", "2026-03-02", 0, 0, ()),
    ("23", "Grid Saint", "Pressure Vessel", "Techno", "Night Shift Tapes", 2018, 128.0, "Gm", "mp3", 128, 0, "", "", "2026-05-30", 1, 0, ()),
    ("24", "Saffi Wren", "Tape Hiss Lullaby", "Disco", "", 0, 100.0, "", "mp3", 320, 1, "", "", "2026-08-08", 0, 0, ()),
]
_EXT = {"mp3": "mp3", "m4a": "m4a", "flac": "flac", "wav": "wav", "aiff": "aiff"}
_REMIXER = {"13": "Dub Atelier"}
_ALBUM = {"2": "Brass Tide LP", "9": "Open Plan EP", "14": "Open Plan EP", "17": "Vessel"}
_ISRC = {"9": "ZZA011700009", "13": "ZZA012300013", "17": "ZZA021800017"}
_SPECIAL_PATH = {
    "2": "//nas/vinyl rips/Funk/The Velvet Ferrymen - Brass Tide.flac",
    "13": "D:/Music/House/The Velvet Ferrymen - Brass Tide (Dub Atelier Club Edit).mp3",
    "22": "D:/Music/Lossless/Marlo Venn - Hallway Light.flac",
}


def _track(row: tuple) -> dict:
    (tid, artist, title, genre, label, year, bpm, key, kind, bitrate, rating, colour, comment,
     added, plays, cues, tags) = row  # fmt: skip
    duration = 180 + (int(tid) * 37) % 300
    folder = genre or "Unsorted"
    location = _SPECIAL_PATH.get(tid, f"D:/Music/{folder}/{artist} - {title}.{_EXT[kind]}")
    return {
        "id": tid, "artist": artist, "title": title, "album": _ALBUM.get(tid, ""),
        "duration_s": duration, "isrc": _ISRC.get(tid, ""), "bitrate": bitrate,
        "location": location, "kind": kind,
        "bit_depth": (24 if tid == "14" else 16) if kind in LOSSLESS else 0,
        "sample_rate": 48000 if tid == "14" else 44100, "file_size": duration * bitrate * 125,
        "bpm": bpm, "key": key, "genre": genre, "label": label, "remixer": _REMIXER.get(tid, ""),
        "year": year, "rating": rating, "colour": colour, "comment": comment, "date_added": added,
        "play_count": plays, "my_tags": tags, "cue_count": cues, "has_artwork": rating >= 3,
    }  # fmt: skip


def _pl(name: str, ids: list[int], **extra) -> dict:
    return {"kind": "playlist", "name": name, "tracks": [str(i) for i in ids], **extra}


def _folder(name: str, children: list[dict]) -> dict:
    return {"kind": "folder", "name": name, "children": children}


SMART_RAW = (  # genre contains "Techno": matches 16, 17, 18, 20 and the orphan 23
    '<NODE Id="777001" LogicalOperator="1" AutomaticUpdate="0">'
    '<CONDITION PropertyName="genre" Operator="8" ValueUnit="" ValueLeft="Techno" ValueRight=""/>'
    "</NODE>"
)
SMART_MATCHES = ["16", "17", "18", "20", "23"]

SPEC: dict = {
    "product": {"Name": "rekordbox", "Version": "7.2.18", "Company": "AlphaTheta"},
    "tracks": [_track(r) for r in _ROWS],
    "tree": [
        _folder("House", [
            _pl("1.1_warm_up", [8, 21, 10, 11]),
            _pl("1.2_peak", [9, 11, 12, 13, 14, 15]),
            _folder("Deep", [
                _pl("deep_rollers", [10, 21, 22, 14], key_type="location"),
                _pl("empty_ideas", []),
            ]),
        ]),
        _folder("Gigs", [
            _pl("Gig 2025-03 Warehouse", [11, 12, 13, 14, 15, 16, 17, 18]),
            _pl("Gig 2025-11 Rooftop", [1, 2, 4, 9, 13, 17]),
        ]),
        _pl("unsorted dump", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 19, 20, 22]),
        _pl("funk & disco 78-92", [1, 2, 3, 4, 5, 6, 7]),
        {"kind": "smart", "name": "All Techno", "raw": SMART_RAW},  # master.db only
    ],
}  # fmt: skip

EXPECTED_COUNTS = {"tracks": 24, "folders": 3, "playlists": 8, "smart": 0, "orphans": 2, "entries": 51}
ORPHAN_IDS = ["23", "24"]


# -- spec variants -------------------------------------------------------------------------


def spec_copy(spec: dict | None = None) -> dict:
    return copy.deepcopy(SPEC if spec is None else spec)


def _strip_smart(nodes: list[dict]) -> list[dict]:
    out = []
    for node in nodes:
        if node["kind"] == "smart":
            continue
        if node["kind"] == "folder":
            node = {**node, "children": _strip_smart(node["children"])}
        out.append(node)
    return out


def without_smart(spec: dict | None = None) -> dict:
    """The spec minus smart playlists: what an XML export can express."""
    out = spec_copy(spec)
    out["tree"] = _strip_smart(out["tree"])
    return out


# Q-34: two rows rekordbox streams. Their FolderPath is the service's URI (the XML Location is
# `file://localhost` + that URI) and ServiceID is set; every local row above has ServiceID 0.
STREAMED = {"25": ("spotify:track:0Synthetic0Spotify0Row25", 6), "26": ("beatport:tracks:26", 3)}
STREAMED_SERVICES = {"25": "spotify", "26": "beatport"}


def with_streaming(spec: dict | None = None) -> dict:
    """The spec plus the STREAMED rows, in 1.1_warm_up and in a playlist of their own
    ("spotify finds", empty once the readers leave streamed rows out)."""
    out = spec_copy(spec)
    for tid, (uri, service_id) in STREAMED.items():
        row = dict(_track(_ROWS[int(tid) - 21]), id=tid, title=f"Streamed {tid}", location=uri)
        out["tracks"].append(row | {"service_id": service_id, "xml_location": "file://localhost" + uri})
    house = out["tree"][0]["children"]
    house[0]["tracks"].append("25")
    out["tree"].insert(3, _pl("spotify finds", [25, 26]))
    return out


def as_mac(spec: dict | None = None) -> dict:
    """The same library on a Mac: D:/Music -> /Users/dj/Music, //nas -> /Volumes/nas."""
    out = spec_copy(spec)
    for t in out["tracks"]:
        loc = t["location"]
        loc = "/Users/dj/Music/" + loc[len("D:/Music/"):] if loc.startswith("D:/Music/") else loc
        t["location"] = "/Volumes/" + loc[2:] if loc.startswith("//") else loc
    return out


# -- (a) rekordbox XML ---------------------------------------------------------------------


def _track_element(parent: ET.Element, t: dict) -> None:
    attrs = {
        "TrackID": t["id"], "Name": t["title"], "Artist": t["artist"], "Composer": "",
        "Album": t["album"], "Grouping": "", "Genre": t["genre"], "Kind": KIND_TEXT[t["kind"]],
        "Size": str(t["file_size"]), "TotalTime": str(t["duration_s"]), "DiscNumber": "0",
        "TrackNumber": "0", "Year": str(t["year"]), "AverageBpm": f"{t['bpm']:.2f}",
        "DateAdded": t["date_added"], "BitRate": str(t["bitrate"]),
        "SampleRate": str(t["sample_rate"]), "Comments": t["comment"],
        "PlayCount": str(t["play_count"]), "Rating": str(t["rating"] * RATING_STEP),
        "Location": t.get("xml_location") or location_url(t["location"]), "Remixer": t["remixer"],
        "Tonality": t["key"],
        "Label": t["label"], "Mix": "",
    }  # fmt: skip
    if t["colour"]:
        attrs["Colour"] = COLOUR_CODES[t["colour"]]
    el = ET.SubElement(parent, "TRACK", attrs)
    if t["bpm"]:
        ET.SubElement(el, "TEMPO", Inizio="0.025", Bpm=f"{t['bpm']:.2f}", Metro="4/4", Battito="1")
    for i in range(t["cue_count"]):
        num = str(i) if i < 8 else "-1"
        ET.SubElement(el, "POSITION_MARK", Name="", Type="0", Start=f"{0.025 + 16 * i:.3f}", Num=num)


def _node_elements(parent: ET.Element, nodes: list[dict], locations: dict[str, str]) -> int:
    written = 0
    for node in nodes:
        if node["kind"] == "smart":
            continue  # the XML schema has no smart playlists
        written += 1
        if node["kind"] == "folder":
            el = ET.SubElement(parent, "NODE", Type="0", Name=node["name"], Count="0")
            el.set("Count", str(_node_elements(el, node["children"], locations)))
            continue
        by_location = node.get("key_type") == "location"
        el = ET.SubElement(parent, "NODE", Name=node["name"], Type="1",
                           KeyType="1" if by_location else "0", Entries=str(len(node["tracks"])))
        for tid in node["tracks"]:
            ET.SubElement(el, "TRACK", Key=location_url(locations[tid]) if by_location else tid)
    return written


def to_xml(spec: dict | None = None) -> str:
    spec = SPEC if spec is None else spec
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", spec["product"])
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(spec["tracks"])))
    for t in spec["tracks"]:
        _track_element(collection, t)
    playlists = ET.SubElement(root, "PLAYLISTS")
    top = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="0")
    locations = {t["id"]: t["location"] for t in spec["tracks"]}
    top.set("Count", str(_node_elements(top, spec["tree"], locations)))
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_xml(path: str | Path, spec: dict | None = None) -> Path:
    path = Path(path)
    path.write_text(to_xml(spec), encoding="utf-8", newline="\n")
    return path


# -- (b) fake pyrekordbox master.db ---------------------------------------------------------


class Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def count(self):
        return len(self._rows)


class SpecDB:
    """The read surface of pyrekordbox the readers may use, nothing else. Never commits."""

    def __init__(self, contents, playlists):
        self.contents = list(contents)
        self.playlists = list(playlists)
        self.rollbacks = self.closes = 0

    def get_content(self, **kwargs):
        assert not kwargs, "readers read all content and filter in Python"
        return Query(self.contents)

    def get_playlist(self, **kwargs):
        assert set(kwargs) == {"ParentID"}
        return Query([p for p in self.playlists if p.ParentID == kwargs["ParentID"]])

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1

    def commit(self):
        raise AssertionError("a reader called commit()")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"a reader called db.{name}, which it must never use")


def _cue(deleted: int = 0) -> SimpleNamespace:
    return SimpleNamespace(rb_local_deleted=deleted)


def content_row(t: dict, deleted: int = 0) -> SimpleNamespace:
    """A DjmdContent row: the columns library.to_track_info reads + StockDate, DJPlayCount,
    ColorName, MyTagNames."""
    return SimpleNamespace(
        ID=t["id"], FolderPath=t["location"], FileNameL=PurePosixPath(t["location"]).name,
        ArtistName=t["artist"], Title=t["title"], AlbumName=t["album"], Length=t["duration_s"],
        ISRC=t["isrc"], BitRate=t["bitrate"], FileType=FILE_TYPE[t["kind"]], BitDepth=t["bit_depth"],
        SampleRate=t["sample_rate"], FileSize=t["file_size"],
        ImagePath=f"/PIONEER/Artwork/00001/a{t['id']}.jpg" if t["has_artwork"] else "",
        Analysed=105, BPM=round(t["bpm"] * 100), KeyName=t["key"], GenreName=t["genre"],
        LabelName=t["label"], RemixerName=t["remixer"], ReleaseYear=t["year"], Rating=t["rating"],
        Commnt=t["comment"], Subtitle="", Cues=[_cue() for _ in range(t["cue_count"])],
        StockDate=t["date_added"], DJPlayCount=str(t["play_count"]), ColorName=t["colour"] or None,
        MyTagNames=list(t["my_tags"]), ServiceID=t.get("service_id", 0), rb_local_deleted=deleted,
    )  # fmt: skip


def _tag_link(name: str, link_deleted: int = 0, tag_deleted: int = 0) -> SimpleNamespace:
    """A DjmdSongMyTag row: MyTagName is the association proxy to DjmdMyTag.Name."""
    tag = SimpleNamespace(Name=name, rb_local_deleted=tag_deleted)
    return SimpleNamespace(MyTagName=name, MyTag=tag, rb_local_deleted=link_deleted)


def _song(cid: str, track_no: int, deleted: int = 0) -> SimpleNamespace:
    return SimpleNamespace(ContentID=cid, TrackNo=track_no, rb_local_deleted=deleted)


def _playlist_row(pid: str, name: str, attribute: int, parent: str, seq: int, songs=(), smart=None,
                  deleted: int = 0) -> SimpleNamespace:
    return SimpleNamespace(ID=pid, Name=name, Attribute=attribute, ParentID=parent, Seq=seq,
                           Songs=list(songs), SmartList=smart, rb_local_deleted=deleted)


_ATTRIBUTE = {"playlist": 0, "folder": 1, "smart": 4}  # dj.tree.KIND_BY_ATTRIBUTE


def _playlist_rows(nodes: list[dict], parent: str, ids, out: list) -> None:
    for seq, node in enumerate(nodes, 1):
        pid = str(next(ids))
        songs = [_song(tid, n) for n, tid in enumerate(node.get("tracks", []), 1)]
        out.append(_playlist_row(pid, node["name"], _ATTRIBUTE[node["kind"]], parent, seq, songs,
                                 smart=node.get("raw")))
        if node["kind"] == "folder":
            _playlist_rows(node["children"], pid, ids, out)


def fake_db(spec: dict | None = None, *, deleted: bool = True) -> SpecDB:
    """The spec as pyrekordbox rows. Ids: tracks keep their spec id, playlists count from 500.
    `deleted=True` adds soft-deleted rows (rb_local_deleted=1) the readers must ignore: one
    track, one playlist, one playlist entry, one cue, one My Tag link and one My Tag (a live
    link to a deleted DjmdMyTag). Rows are listed in reverse Seq order on purpose:
    children_of() must sort them."""
    spec = SPEC if spec is None else spec
    contents = [content_row(t) for t in spec["tracks"]]
    playlists: list = []
    _playlist_rows(spec["tree"], "root", iter(range(500, 10_000)), playlists)
    if deleted:
        ghost = dict(spec["tracks"][0], id="99", title="Removed Track")
        contents.append(content_row(ghost, deleted=1))
        by_name = {p.Name: p for p in playlists}
        if "House" in by_name:
            playlists.append(_playlist_row("499", "old stuff", 0, by_name["House"].ID, 9,
                                           [_song("1", 1)], deleted=1))
        if "1.1_warm_up" in by_name:
            by_name["1.1_warm_up"].Songs.append(_song("5", 99, deleted=1))
            by_name["1.1_warm_up"].Songs.append(_song("99", 100, deleted=1))
        first_cued = next((c for c in contents if c.Cues), None)
        if first_cued is not None:
            first_cued.Cues.append(_cue(deleted=1))
        first_tagged = next((c for c in contents if c.MyTagNames), None)
        if first_tagged is not None:
            links = [_tag_link(n) for n in first_tagged.MyTagNames]
            links += [_tag_link("Old Tag", link_deleted=1), _tag_link("Gone Tag", tag_deleted=1)]
            first_tagged.MyTags = links
            first_tagged.MyTagNames = [link.MyTagName for link in links]  # the proxy does not filter
    playlists.reverse()
    return SpecDB(contents, playlists)


def write_master_files(folder: Path, spec: dict | None = None, *, sides: bool = True) -> Path:
    """Stand-ins for master.db (+ -wal, -shm, masterPlaylists6.xml) on disk; returns master.db.
    The bytes are placeholders: tests replace `safety._connect` with `fake_db`."""
    spec = SPEC if spec is None else spec
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "master.db"
    db.write_bytes(b"SQLite format 3\x00 synthetic placeholder")
    if sides:
        (folder / "master.db-wal").write_bytes(b"wal placeholder")
        (folder / "master.db-shm").write_bytes(b"shm placeholder")
    p = spec["product"]
    (folder / "masterPlaylists6.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<MASTER_PLAYLIST Version="1.0.0" AutomaticSync="1">\n'
        f'  <PRODUCT Name="{p["Name"]}" Version="{p["Version"]}" Company="{p["Company"]}"/>\n'
        "  <PLAYLISTS/>\n</MASTER_PLAYLIST>\n",
        encoding="utf-8",
    )
    return db


if __name__ == "__main__":
    SAMPLE_XML.parent.mkdir(parents=True, exist_ok=True)
    print(write_xml(SAMPLE_XML))
