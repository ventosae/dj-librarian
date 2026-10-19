"""Hand-built audio files and fake rekordbox rows for the dj tidy tests.

No encoder is needed: mutagen only parses headers/metadata blocks, so a frame-less FLAC, a
silent WAV, an AIFF with an empty SSND chunk and an MP3 made of empty MPEG frames all read
and write like real files. Imported by tests, not collected."""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

# One MPEG-1 Layer III frame header: 128 kbps, 44.1 kHz, no padding -> 417 bytes per frame.
_MP3_FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)


def make_mp3(path: Path, frames: int = 40) -> Path:
    path.write_bytes(_MP3_FRAME * frames)  # ~1 s, CBR, no tag
    return path


def make_wav(path: Path, seconds: float = 1.0, rate: int = 44100, bits: int = 16, channels: int = 2) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(bytes(int(seconds * rate) * channels * (bits // 8)))
    return path


def _ext80(rate: int) -> bytes:
    exp = math.floor(math.log2(rate))
    mant = int(rate / (2**exp) * (1 << 63))
    return struct.pack(">HQ", 16383 + exp, mant)


def make_aiff(path: Path, seconds: float = 1.0, rate: int = 44100, bits: int = 16, channels: int = 2) -> Path:
    frames = int(seconds * rate)
    comm = struct.pack(">hLh", channels, frames, bits) + _ext80(rate)
    ssnd = struct.pack(">LL", 0, 0) + bytes(frames * channels * (bits // 8))
    body = b"AIFF" + b"COMM" + struct.pack(">L", len(comm)) + comm
    body += b"SSND" + struct.pack(">L", len(ssnd)) + ssnd
    path.write_bytes(b"FORM" + struct.pack(">L", len(body)) + body)
    return path


def make_flac(path: Path, seconds: float = 1.0, rate: int = 44100, bits: int = 16, channels: int = 2) -> Path:
    total = int(seconds * rate)
    si = struct.pack(">HH", 4096, 4096) + (0).to_bytes(3, "big") * 2
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total
    si += packed.to_bytes(8, "big") + bytes(16)
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(si).to_bytes(3, "big") + si)  # STREAMINFO, last block
    return path


def make_audio(path: Path, **kwargs) -> Path:
    maker = {".mp3": make_mp3, ".wav": make_wav, ".aif": make_aiff, ".aiff": make_aiff, ".flac": make_flac}
    return maker[path.suffix.lower()](path, **kwargs)


def jpeg_bytes(size: tuple[int, int] = (1400, 1400), progressive: bool = False, colour=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG", quality=85, progressive=progressive)
    return buf.getvalue()


def png_bytes(size: tuple[int, int] = (600, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 30, 200)).save(buf, "PNG")
    return buf.getvalue()


def make_jpeg(path: Path, size: tuple[int, int] = (1400, 1400)) -> Path:
    path.write_bytes(jpeg_bytes(size))
    return path


# -- fake rekordbox rows -------------------------------------------------------------------


def row(cid: str = "1", path: str = "C:/Music/x/a.mp3", **over) -> SimpleNamespace:
    """A DjmdContent row with every column library.TrackInfo reads."""
    base = dict(
        ID=cid, FolderPath=path, FileNameL=Path(path).name, ArtistName="Artist", Title="Title",
        AlbumName="", Length=200, ISRC="", BitRate=320, FileType=1, BitDepth=0, SampleRate=44100,
        FileSize=8_000_000, ImagePath="", Analysed=105, BPM=12000, KeyName="Am", GenreName="",
        LabelName="", RemixerName="", ReleaseYear=0, Rating=0, Commnt="", Subtitle="", Cues=[],
        rb_local_deleted=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def song(cid: str, track_no: int = 1, deleted: int = 0) -> SimpleNamespace:
    return SimpleNamespace(ContentID=cid, TrackNo=track_no, rb_local_deleted=deleted)


class Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def count(self):
        return len(self._rows)


class TidyDB:
    """get_content() and the playlist tree, nothing else (like conftest.FakeDB)."""

    def __init__(self, contents=(), playlists=()):
        self.contents = list(contents)
        self.playlists = list(playlists)

    def get_content(self, **kwargs):
        assert not kwargs, "tidy reads all content and filters in Python"
        return Query(self.contents)

    def get_playlist(self, **kwargs):
        assert set(kwargs) == {"ParentID"}
        return Query([p for p in self.playlists if p.ParentID == kwargs["ParentID"]])

    def rollback(self):
        pass

    def close(self):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"tidy called db.{name}, which it must never use")


def playlist(pid: str, name: str, parent: str = "root", songs=(), attribute: int = 0, seq: int = 1):
    return SimpleNamespace(ID=pid, Name=name, Attribute=attribute, ParentID=parent, Seq=seq,
                           Songs=list(songs), rb_local_deleted=0)
