"""Audio-file tags through mutagen. The only tidy module that opens audio files.

Every write goes: copy the file to `.<name>.tidy-tmp` -> edit the copy -> re-read the copy and
check the change took and the stream length did not move -> `os.replace` over the original.
Any failure removes the temp and leaves the original byte-identical.

v1 writes four neutral fields (artist, title, mix, remixer) and front-cover art.
MP3 / WAV / AIFF -> ID3 (v2.3 by default), FLAC -> Vorbis comments, M4A -> read-only.
BPM and KEY are never written (rekordbox ignores tag BPM; key comes from analysis).
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import mutagen
from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, Frames
from mutagen.mp3 import MP3, BitrateMode
from mutagen.mp4 import MP4
from mutagen.wave import WAVE
from PIL import Image

from dj.tidy import TidyError

FIELDS = ("artist", "title", "mix", "remixer")
ART = "art"
ID3_FRAMES = {"artist": "TPE1", "title": "TIT2", "mix": "TIT3", "remixer": "TPE4", ART: "APIC"}
VORBIS_FIELDS = {"artist": "ARTIST", "title": "TITLE", "mix": "VERSION", "remixer": "REMIXER", ART: "PICTURE"}
MP4_ATOMS = {"artist": "\xa9ART", "title": "\xa9nam", ART: "covr"}  # read only in v1
TMP_SUFFIX = ".tidy-tmp"
WRITABLE = ("mp3", "wav", "aiff", "flac")
_LENGTH_TOLERANCE_S = 0.5


@dataclass(frozen=True)
class ArtInfo:
    mime: str
    width: int
    height: int
    nbytes: int
    progressive: bool | None = None

    @property
    def format(self) -> str:
        return self.mime.split("/")[-1].lower().replace("jpg", "jpeg")


@dataclass(frozen=True)
class StreamInfo:
    container: str
    bitrate_kbps: int | None
    vbr: bool | None
    sample_rate: int | None
    bit_depth: int | None
    duration_s: float | None
    id3_version: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class Tags:
    artist: tuple[str, ...] = ()
    title: str = ""
    mix: str = ""
    remixer: str = ""
    album: str = ""
    genre: str = ""
    bpm: str = ""
    key: str = ""
    comment: str = ""
    year: str = ""
    has_art: bool = False
    raw: dict[str, list[str]] = field(default_factory=dict)

    def value(self, name: str) -> str:
        if name == "artist":
            return " / ".join(self.artist)
        return str(getattr(self, name, ""))


def tag_format(container: str | None) -> str | None:
    return {"mp3": "id3", "wav": "id3", "aiff": "id3", "flac": "vorbis", "m4a": "mp4"}.get(container or "")


def frame_name(container: str | None, name: str) -> str:
    fmt = tag_format(container)
    table = {"id3": ID3_FRAMES, "vorbis": VORBIS_FIELDS, "mp4": MP4_ATOMS}.get(fmt or "", {})
    return table.get(name, name)


def sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- reading -------------------------------------------------------------------------------


def _open(path: Path, container: str | None = None) -> Any:
    opener = {"mp3": MP3, "wav": WAVE, "aiff": AIFF, "flac": FLAC, "m4a": MP4}.get(container or "")
    try:
        f = opener(path) if opener else mutagen.File(path)
    except Exception as exc:  # mutagen raises many unrelated types
        raise TidyError(f"{path.name}: cannot read as audio ({exc.__class__.__name__}: {exc})") from exc
    if f is None:
        raise TidyError(f"{path.name}: not an audio file mutagen knows")
    return f


def _container(f: Any) -> str | None:
    for cls, name in ((MP3, "mp3"), (WAVE, "wav"), (AIFF, "aiff"), (FLAC, "flac"), (MP4, "m4a")):
        if isinstance(f, cls):
            return name
    return None


def container_of(path: Path | str) -> str | None:
    """By content (mutagen's sniffing), not by extension. None = unknown / unreadable."""
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    return _container(f) if f is not None else None


def _art_info(data: bytes, declared_mime: str) -> ArtInfo:
    try:
        im = Image.open(io.BytesIO(data))
        fmt = (im.format or "").lower()
        mime = f"image/{'jpeg' if fmt in ('jpeg', 'jpg') else fmt}" if fmt else declared_mime
        return ArtInfo(mime=mime, width=im.width, height=im.height, nbytes=len(data),
                       progressive=bool(im.info.get("progressive") or im.info.get("progression")))
    except Exception:
        return ArtInfo(mime=declared_mime or "image/unknown", width=0, height=0, nbytes=len(data))


def _texts(frame: Any) -> list[str]:
    text = getattr(frame, "text", None)
    if text is None:
        return [str(frame)]
    return [str(t) for t in text]


def _read_id3(f: Any) -> tuple[Tags, ArtInfo | None, tuple[int, int, int] | None]:
    tags = f.tags
    if tags is None:
        return Tags(), None, None
    raw: dict[str, list[str]] = {}
    for key, frame in tags.items():
        if hasattr(frame, "text"):
            raw[key.split(":")[0] if key.startswith(("TXXX", "COMM")) else key] = _texts(frame)

    def first(frame_id: str) -> str:
        frames = tags.getall(frame_id)
        return _texts(frames[0])[0] if frames and _texts(frames[0]) else ""

    pics = tags.getall("APIC")
    front = next((p for p in pics if getattr(p, "type", 3) == 3), pics[0] if pics else None)
    art = _art_info(front.data, front.mime) if front is not None else None
    comm = tags.getall("COMM")
    year = first("TDRC") or first("TYER")
    artist = tuple(t for t in (_texts(tags.getall("TPE1")[0]) if tags.getall("TPE1") else []) if t)
    return Tags(
        artist=artist, title=first("TIT2"), mix=first("TIT3"), remixer=first("TPE4"),
        album=first("TALB"), genre=first("TCON"), bpm=first("TBPM"), key=first("TKEY"),
        comment=_texts(comm[0])[0] if comm and _texts(comm[0]) else "", year=year,
        has_art=bool(pics), raw=raw,
    ), art, tuple(tags.version) if tags.version else None


def _read_vorbis(f: FLAC) -> tuple[Tags, ArtInfo | None]:
    tags = f.tags or {}
    raw = {k.upper(): [str(v) for v in vals] for k, vals in tags.items()} if tags else {}

    def first(key: str) -> str:
        vals = raw.get(key, [])
        return vals[0] if vals else ""

    pics = list(f.pictures)
    front = next((p for p in pics if p.type == 3), pics[0] if pics else None)
    art = _art_info(front.data, front.mime) if front is not None else None
    return Tags(
        artist=tuple(raw.get("ARTIST", [])), title=first("TITLE"), mix=first("VERSION"),
        remixer=first("REMIXER"), album=first("ALBUM"), genre=first("GENRE"), bpm=first("BPM"),
        key=first("INITIALKEY") or first("KEY"), comment=first("COMMENT") or first("DESCRIPTION"),
        year=first("DATE") or first("YEAR"), has_art=bool(pics), raw=raw,
    ), art


def _read_mp4(f: MP4) -> tuple[Tags, ArtInfo | None]:
    tags = f.tags or {}
    raw: dict[str, list[str]] = {}
    for key, vals in tags.items():
        if key == "covr":
            continue
        raw[key] = [v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v) for v in vals]

    def first(key: str) -> str:
        vals = raw.get(key, [])
        return vals[0] if vals else ""

    covers = tags.get("covr") or []
    art = None
    if covers:
        cover = covers[0]
        fmt = getattr(cover, "imageformat", None)
        declared = "image/png" if fmt == 14 else "image/jpeg"
        art = _art_info(bytes(cover), declared)
    return Tags(
        artist=tuple(raw.get("\xa9ART", [])), title=first("\xa9nam"), mix="", remixer="",
        album=first("\xa9alb"), genre=first("\xa9gen"), bpm=first("tmpo"),
        key=first("----:com.apple.iTunes:initialkey"), comment=first("\xa9cmt"), year=first("\xa9day"),
        has_art=bool(covers), raw=raw,
    ), art


def _stream(f: Any, container: str, id3_version: tuple[int, int, int] | None) -> StreamInfo:
    info = f.info
    bitrate = getattr(info, "bitrate", 0) or 0
    vbr: bool | None = None
    if container == "mp3":
        mode = getattr(info, "bitrate_mode", None)
        if mode == BitrateMode.CBR:
            vbr = False
        elif mode in (BitrateMode.VBR, BitrateMode.ABR):
            vbr = True
    depth = getattr(info, "bits_per_sample", None)
    return StreamInfo(
        container=container,
        bitrate_kbps=round(bitrate / 1000) if bitrate else None,
        vbr=vbr,
        sample_rate=getattr(info, "sample_rate", None) or None,
        bit_depth=int(depth) if depth else None,
        duration_s=float(getattr(info, "length", 0.0) or 0.0) or None,
        id3_version=id3_version,
    )


def read(path: Path | str) -> tuple[Tags, StreamInfo, ArtInfo | None]:
    """Tags, stream facts and front-cover facts. Raises TidyError when mutagen cannot read it."""
    path = Path(path)
    f = _open(path)
    container = _container(f)
    if container is None:
        raise TidyError(f"{path.name}: {type(f).__name__} is not a format dj tidy handles")
    version: tuple[int, int, int] | None = None
    if container in ("mp3", "wav", "aiff"):
        tags, art, version = _read_id3(f)
    elif container == "flac":
        tags, art = _read_vorbis(f)
    else:
        tags, art = _read_mp4(f)
    return tags, _stream(f, container, version), art


def snapshot(tags: Tags, container: str) -> dict[str, list[str]]:
    """The writable frames as they are now, for the undo record (empty list = absent)."""
    out: dict[str, list[str]] = {}
    for name in FIELDS:
        key = frame_name(container, name)
        out[key] = list(tags.raw.get(key, []))
    return out


# -- writing -------------------------------------------------------------------------------


def _edit(path: Path, container: str, mutate: Callable[[Any], None], verify: Callable[[Tags, ArtInfo | None], None],
          id3_version: int) -> None:
    tmp = path.with_name(f".{path.name}{TMP_SUFFIX}")
    if tmp.exists():
        raise TidyError(f"{tmp.name} exists: a previous run stopped half-way. Check it, remove it, retry.")
    _, before, _ = read(path)
    shutil.copy2(path, tmp)
    try:
        f = _open(tmp, container)
        mutate(f)
        if _no_tags_left(f):
            f.delete()  # a file that never had a tag gets none back: byte-identical undo
        elif tag_format(container) == "id3":
            f.save(v2_version=id3_version)
        else:
            f.save()
        tags, after, art = read(tmp)
        if before.duration_s and after.duration_s and abs(before.duration_s - after.duration_s) > _LENGTH_TOLERANCE_S:
            raise TidyError(f"{path.name}: stream length moved from {before.duration_s} to {after.duration_s}")
        verify(tags, art)
        os.replace(tmp, path)
    except TidyError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise TidyError(f"{path.name}: write failed ({exc.__class__.__name__}: {exc}); original untouched") from exc


def _no_tags_left(f: Any) -> bool:
    if isinstance(f, FLAC):
        return not f.tags and not f.pictures
    return f.tags is None or len(f.tags.keys()) == 0


def _set_id3(f: Any, name: str, values: Sequence[str], id3_version: int) -> None:
    if f.tags is None:
        f.add_tags()
    frame_id = ID3_FRAMES[name]
    f.tags.delall(frame_id)
    if values:
        encoding = 1 if id3_version == 3 else 3  # UTF-16 for v2.3, UTF-8 for v2.4
        f.tags.add(Frames[frame_id](encoding=encoding, text=list(values)))


def _set_id3_art(f: Any, data: bytes | None) -> None:
    if f.tags is None:
        f.add_tags()
    f.tags.delall("APIC")
    if data:
        f.tags.add(APIC(encoding=0, mime="image/jpeg", type=3, desc="", data=data))


def _set_vorbis(f: FLAC, name: str, values: Sequence[str]) -> None:
    key = VORBIS_FIELDS[name]
    if values:
        f[key] = list(values)
    elif key in f:
        del f[key]


def _set_vorbis_art(f: FLAC, data: bytes | None) -> None:
    f.clear_pictures()
    if data:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = ""
        pic.data = data
        try:
            im = Image.open(io.BytesIO(data))
            pic.width, pic.height, pic.depth = im.width, im.height, 24
        except Exception:
            pass
        f.add_picture(pic)


def write(path: Path | str, changes: Mapping[str, str], art: bytes | None = None, id3_version: int = 3) -> None:
    """Set the given fields (and optionally embed `art`, JPEG bytes). Temp + atomic replace."""
    path = Path(path)
    bad = sorted(set(changes) - set(FIELDS))
    if bad:
        raise TidyError(f"{path.name}: fields {bad} are not writable in v1 (only {list(FIELDS)})")
    container = container_of(path)
    if container not in WRITABLE:
        raise TidyError(f"{path.name}: {container or 'unknown'} writes are not in v1 (only {', '.join(WRITABLE)})")
    fmt = tag_format(container)

    def mutate(f: Any) -> None:
        for name, value in changes.items():
            if fmt == "id3":
                _set_id3(f, name, [value], id3_version)
            else:
                _set_vorbis(f, name, [value])
        if art is not None:
            (_set_id3_art if fmt == "id3" else _set_vorbis_art)(f, art)

    def verify(tags: Tags, art_info: ArtInfo | None) -> None:
        for name, value in changes.items():
            got = tags.value(name)
            if got != value:
                raise TidyError(f"{path.name}: wrote {name}={value!r} but read back {got!r}")
        if art is not None and not tags.has_art:
            raise TidyError(f"{path.name}: artwork did not stick")

    _edit(path, container, mutate, verify, id3_version)


def restore(path: Path | str, snap: Mapping[str, Sequence[str]], drop_art: bool, id3_version: int = 3) -> None:
    """Put the writable frames back to `snap` (from `snapshot`); optionally remove the art."""
    path = Path(path)
    container = container_of(path)
    if container not in WRITABLE:
        raise TidyError(f"{path.name}: {container or 'unknown'} writes are not in v1")
    fmt = tag_format(container)
    by_name = {name: list(snap.get(frame_name(container, name), [])) for name in FIELDS}

    def mutate(f: Any) -> None:
        for name, values in by_name.items():
            if fmt == "id3":
                _set_id3(f, name, values, id3_version)
            else:
                _set_vorbis(f, name, values)
        if drop_art:
            (_set_id3_art if fmt == "id3" else _set_vorbis_art)(f, None)

    def verify(tags: Tags, art_info: ArtInfo | None) -> None:
        for name, values in by_name.items():
            want = " / ".join(values) if name == "artist" else (values[0] if values else "")
            if tags.value(name) != want:
                raise TidyError(f"{path.name}: restore of {name} read back {tags.value(name)!r}, wanted {want!r}")
        if drop_art and tags.has_art:
            raise TidyError(f"{path.name}: artwork still present after restore")

    _edit(path, container, mutate, verify, id3_version)


# -- artwork -------------------------------------------------------------------------------


def prepare_art(image: bytes, max_px: int = 800, quality: int = 90) -> bytes:
    """Any image -> baseline RGB JPEG that fits in max_px x max_px (CDJ-friendly)."""
    try:
        im = Image.open(io.BytesIO(image))
        im.load()
    except Exception as exc:
        raise TidyError(f"artwork is not an image Pillow can read ({exc})") from exc
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if im.width > max_px or im.height > max_px:
        im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def find_local_art(path: Path | str, names: Sequence[str]) -> Path | None:
    """cover.jpg / folder.jpg / <stem>.jpg next to the track, first one that exists."""
    path = Path(path)
    for pattern in names:
        candidate = path.with_name(pattern.format(stem=path.stem))
        if candidate.is_file():
            return candidate
    return None
