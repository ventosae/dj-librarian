"""tidy.yaml -> TidyConfig. One file read, no other I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

from dj.safety import REPO_ROOT
from dj.tidy import TidyError

DEFAULT_PATH = REPO_ROOT / "tidy.yaml"
AUDIO_FORMATS = ("mp3", "m4a", "wav", "aiff", "flac")


@dataclass(frozen=True)
class ArtRules:
    formats: tuple[str, ...] = ("jpeg",)
    max_px: int = 800
    min_px: int = 300
    max_bytes: int = 1_048_576


@dataclass(frozen=True)
class Profile:
    name: str
    formats: tuple[str, ...]
    max_bit_depth: int
    sample_rates: tuple[int, ...]
    mp3_min_kbps: int
    mp3_allow_vbr: bool
    art: ArtRules
    max_path: int
    forbidden_chars: str
    notes: str = ""


@dataclass(frozen=True)
class NamingRules:
    template: str = "{artist} - {title}{mix}"
    artist_join_two: str = " & "
    artist_join_many: str = ", "
    omit_mixes: tuple[str, ...] = ("Original Mix", "Original Version", "Original")
    title_includes_mix: bool = True
    nfc: bool = True
    max_path: int = 240


@dataclass(frozen=True)
class ArtConfig:
    local_names: tuple[str, ...] = ("cover.jpg", "cover.jpeg", "folder.jpg", "{stem}.jpg")
    embed_max_px: int = 800
    jpeg_quality: int = 90


@dataclass(frozen=True)
class BpmExpectation:
    regex: re.Pattern[str]
    bpm: int | None  # fixed value, or None when the regex has a `bpm` group


@dataclass(frozen=True)
class TidyConfig:
    roots: tuple[Path, ...]
    enforce_roots_for_writes: bool
    id3_version: int
    naming: NamingRules
    art: ArtConfig
    profiles: tuple[Profile, ...]
    default_profiles: tuple[str, ...]
    bpm_expectations: tuple[BpmExpectation, ...]
    duplicate_duration_tolerance_s: int
    source: Path | None = None
    warnings: tuple[str, ...] = ()

    def profile(self, name: str) -> Profile:
        for p in self.profiles:
            if p.name == name:
                return p
        known = ", ".join(p.name for p in self.profiles)
        raise TidyError(f"Unknown profile {name!r}. tidy.yaml knows: {known}")


def _need(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise TidyError(f"tidy.yaml: {where} needs `{key}`.")
    return mapping[key]


def _tuple_str(values: Any, where: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise TidyError(f"tidy.yaml: {where} must be a list of strings.")
    return tuple(values)


def _profile(raw: dict[str, Any]) -> Profile:
    name = str(_need(raw, "name", "every profile"))
    where = f"profile {name!r}"
    formats = tuple(f.lower() for f in _tuple_str(_need(raw, "formats", where), f"{where}.formats"))
    bad = sorted(set(formats) - set(AUDIO_FORMATS))
    if bad:
        raise TidyError(f"tidy.yaml: {where}.formats has unknown {bad}; known: {list(AUDIO_FORMATS)}")
    art_raw = raw.get("art") or {}
    art = ArtRules(
        formats=tuple(f.lower() for f in art_raw.get("formats", ["jpeg"])),
        max_px=int(art_raw.get("max_px", 800)),
        min_px=int(art_raw.get("min_px", 300)),
        max_bytes=int(art_raw.get("max_bytes", 1_048_576)),
    )
    rates = _need(raw, "sample_rates", where)
    if not isinstance(rates, list) or not all(isinstance(r, int) for r in rates):
        raise TidyError(f"tidy.yaml: {where}.sample_rates must be a list of integers (Hz).")
    return Profile(
        name=name,
        formats=formats,
        max_bit_depth=int(_need(raw, "max_bit_depth", where)),
        sample_rates=tuple(rates),
        mp3_min_kbps=int(raw.get("mp3_min_kbps", 0)),
        mp3_allow_vbr=bool(raw.get("mp3_allow_vbr", True)),
        art=art,
        max_path=int(raw.get("max_path", 240)),
        forbidden_chars=str(raw.get("forbidden_chars", '<>:"/\\|?*')),
        notes=str(raw.get("notes", "")),
    )


def _bpm_expectation(raw: dict[str, Any], index: int) -> BpmExpectation:
    where = f"bpm_expectations[{index}]"
    pattern = str(_need(raw, "regex", where))
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise TidyError(f"tidy.yaml: {where}.regex does not compile: {exc}") from exc
    fixed = raw.get("bpm")
    if fixed is None and "bpm" not in regex.groupindex:
        raise TidyError(f"tidy.yaml: {where} needs a `bpm:` value or a (?P<bpm>...) group.")
    return BpmExpectation(regex=regex, bpm=int(fixed) if fixed is not None else None)


def load_config(path: Path | str = DEFAULT_PATH) -> TidyConfig:
    path = Path(path)
    if not path.is_file():
        raise TidyError(f"Config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise TidyError(f"tidy.yaml is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TidyError("tidy.yaml must be a mapping.")

    warnings: list[str] = []
    roots = tuple(Path(r) for r in _tuple_str(_need(raw, "roots", "the top level"), "roots"))
    if not roots:
        raise TidyError("tidy.yaml: `roots` must name at least one music folder.")
    for root in roots:
        if not root.is_dir():
            warnings.append(f"root {root} is not a directory right now (unplugged drive?)")

    naming_raw = raw.get("naming") or {}
    naming = NamingRules(
        template=str(naming_raw.get("template", NamingRules.template)),
        artist_join_two=str(naming_raw.get("artist_join_two", NamingRules.artist_join_two)),
        artist_join_many=str(naming_raw.get("artist_join_many", NamingRules.artist_join_many)),
        omit_mixes=tuple(naming_raw.get("omit_mixes", list(NamingRules.omit_mixes))),
        title_includes_mix=bool(naming_raw.get("title_includes_mix", True)),
        nfc=bool(naming_raw.get("nfc", True)),
        max_path=int(naming_raw.get("max_path", NamingRules.max_path)),
    )
    art_raw = raw.get("art") or {}
    art = ArtConfig(
        local_names=tuple(art_raw.get("local_names", list(ArtConfig.local_names))),
        embed_max_px=int(art_raw.get("embed_max_px", ArtConfig.embed_max_px)),
        jpeg_quality=int(art_raw.get("jpeg_quality", ArtConfig.jpeg_quality)),
    )

    profiles_raw = raw.get("profiles") or []
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise TidyError("tidy.yaml: `profiles` must be a non-empty list.")
    profiles = tuple(_profile(p) for p in profiles_raw)
    names = [p.name for p in profiles]
    if len(set(names)) != len(names):
        raise TidyError(f"tidy.yaml: profile names must be unique: {names}")
    defaults = tuple(_tuple_str(raw.get("default_profiles", names), "default_profiles"))
    unknown = sorted(set(defaults) - set(names))
    if unknown:
        raise TidyError(f"tidy.yaml: default_profiles names unknown profiles {unknown}")

    bpm_raw = raw.get("bpm_expectations") or []
    expectations = tuple(_bpm_expectation(e, i) for i, e in enumerate(bpm_raw))
    tolerance = int((raw.get("duplicates") or {}).get("duration_tolerance_s", 2))
    id3_version = int(raw.get("id3_version", 3))
    if id3_version not in (3, 4):
        raise TidyError("tidy.yaml: id3_version must be 3 or 4.")

    return TidyConfig(
        roots=roots,
        enforce_roots_for_writes=bool(raw.get("enforce_roots_for_writes", True)),
        id3_version=id3_version,
        naming=naming,
        art=art,
        profiles=profiles,
        default_profiles=defaults,
        bpm_expectations=expectations,
        duplicate_duration_tolerance_s=tolerance,
        source=path,
        warnings=tuple(warnings),
    )


def profiles_named(cfg: TidyConfig, names: Sequence[str]) -> list[Profile]:
    return [cfg.profile(n) for n in (names or cfg.default_profiles)]


def folder_in_roots(path: Path | str, cfg: TidyConfig) -> bool:
    """True when `path` (resolved) sits inside one of the configured roots."""
    try:
        full = Path(path).resolve()
    except OSError:
        return False
    for root in cfg.roots:
        try:
            if full.is_relative_to(root.resolve()):
                return True
        except OSError:
            continue
    return False


def expected_bpm_from_name(name: str, cfg: TidyConfig) -> tuple[int | None, str]:
    """-> (bpm, which rule) from a crate or folder name; first match wins."""
    for exp in cfg.bpm_expectations:
        m = exp.regex.search(name or "")
        if not m:
            continue
        if exp.bpm is not None:
            return exp.bpm, exp.regex.pattern
        try:
            return int(m.group("bpm")), exp.regex.pattern
        except (IndexError, ValueError):
            continue
    return None, ""
