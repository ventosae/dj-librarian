"""Audit JSON + Markdown, the relocate checklist. Pure builders plus one writer."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from dj import libfolder
from dj.analyze import table
from dj.intake import Paths
from dj.tidy.checks import (
    ERROR,
    INFO,
    WARN,
    Finding,
    Item,
    code_counts,
    severity_counts,
)
from dj.tidy.config import Profile, TidyConfig
from dj.tidy.dupes import DupeGroup
from dj.tidy.scan import Target

CODE_HELP = {
    "FILE_MISSING": "rekordbox points at a file that is not there",
    "FILE_UNREADABLE": "mutagen cannot open the file",
    "NOT_IN_REKORDBOX": "file on disk with no rekordbox row",
    "FMT_UNSUPPORTED": "container not playable on the profile",
    "FMT_DB_MISMATCH": "rekordbox FileType disagrees with the file",
    "BITDEPTH_TOO_HIGH": "bit depth over the profile's limit",
    "SAMPLERATE_UNSUPPORTED": "sample rate not in the profile's list",
    "MP3_BITRATE_LOW": "MP3 under the profile's kbps floor",
    "MP3_VBR": "variable-bitrate MP3",
    "ART_MISSING": "no embedded picture",
    "ART_LOCAL_AVAILABLE": "a cover image sits next to the file",
    "ART_NOT_JPEG": "embedded picture is not JPEG",
    "ART_TOO_LARGE": "picture over the profile's size limit",
    "ART_TOO_SMALL": "picture under the minimum size",
    "PATH_TOO_LONG": "full path over the profile's limit",
    "PATH_BAD_CHARS": "forbidden/control characters or trailing dot",
    "NAME_OFF_CONVENTION": "file name differs from the naming rule",
    "TAG_ARTIST_MISSING": "artist tag empty",
    "TAG_TITLE_MISSING": "title tag empty",
    "TAG_GENRE_MISSING": "genre tag empty",
    "TAG_DB_FILE_MISMATCH": "rekordbox shows other artist/title than the file (Reload Tag)",
    "TAG_ENCODING_ODD": "ID3 version differs from tidy.yaml",
    "SWAP_SUSPECTED": "file name may be Title - Artist",
    "NOT_ANALYSED": "no BPM/grid in rekordbox yet",
    "BPM_SCALE_UNEXPECTED": "DB BPM column not in the expected x100 scale",
    "BPM_HALF_DOUBLE": "rekordbox BPM is half or double the expected",
    "BPM_DB_TAG_DIFFER": "rekordbox BPM differs from the TBPM tag",
}


def _tail(path: str, n: int = 60) -> str:
    return path if len(path) <= n else "..." + path[-n:]


def item_dict(item: Item, findings: Sequence[Finding]) -> dict[str, Any]:
    f = item.file
    out: dict[str, Any] = {
        "file": f.path.as_posix(),
        "exists": f.exists,
        "size": f.size,
        "mtime": f.mtime,
        "sha256": f.sha256,
        "rb_content_id": item.rb.content_id if item.rb else None,
        "crate": item.crate,
        "in_roots": item.in_roots,
        "read_error": f.read_error,
        "stream": dataclasses.asdict(f.stream) if f.stream else None,
        "db": None,
        "tags": None,
        "art": dataclasses.asdict(f.art) if f.art else None,
        "local_art": str(item.local_art) if item.local_art else None,
        "parsed": dataclasses.asdict(item.parsed) if item.parsed else None,
        "findings": [x.as_dict() for x in findings],
    }
    if item.rb:
        rb = item.rb
        out["db"] = {"artist": rb.artist, "title": rb.title, "album": rb.album, "genre": rb.genre, "label": rb.label,
                     "remixer": rb.remixer, "key": rb.key, "bpm": rb.bpm, "bpm_raw": rb.bpm_raw, "analysed": rb.analysed,
                     "file_type": rb.file_type, "bitrate": rb.bitrate, "bit_depth": rb.bit_depth,
                     "sample_rate": rb.sample_rate, "image_path": rb.image_path, "cues": rb.cue_count,
                     "rating": rb.rating, "duration_s": rb.duration_s}
    if f.tags:
        t = f.tags
        out["tags"] = {"artist": list(t.artist), "title": t.title, "mix": t.mix, "remixer": t.remixer, "album": t.album,
                       "genre": t.genre, "bpm": t.bpm, "key": t.key, "year": t.year, "has_art": t.has_art}
    return out


def audit_dict(target: Target, cfg: TidyConfig, profiles: Sequence[Profile], items: Sequence[Item],
               findings: Sequence[Sequence[Finding]], groups: Sequence[DupeGroup], meta: dict[str, Any]) -> dict[str, Any]:
    flat = [x for fs in findings for x in fs]
    counts = severity_counts(flat)
    return {
        "kind": "tidy-audit",
        "version": 1,
        "created": datetime.now().isoformat(timespec="seconds"),
        "target": target.as_dict(),
        "profiles": [p.name for p in profiles],
        "config": {"path": str(cfg.source) if cfg.source else None, "roots": [str(r) for r in cfg.roots],
                   "warnings": list(cfg.warnings)},
        "scan": meta,
        "counts": {
            "items": len(items),
            "clean": sum(1 for fs in findings if not fs),
            "error": counts[ERROR], "warn": counts[WARN], "info": counts[INFO],
            "items_with_errors": sum(1 for fs in findings if any(x.severity == ERROR for x in fs)),
            "by_code": code_counts(flat),
            "duplicate_groups": len(groups),
        },
        "items": [item_dict(it, fs) for it, fs in zip(items, findings)],
        "duplicates": [g.as_dict() for g in groups],
    }


def audit_md(audit: dict[str, Any]) -> str:
    c, scan, target = audit["counts"], audit["scan"], audit["target"]
    L: list[str] = [f"# dj tidy audit: {target['value'] or 'whole collection'}", ""]
    L.append(f"{audit['created'][:16].replace('T', ' ')} · target `{target['kind']}` · profiles: "
             f"{', '.join(audit['profiles'])} · hash mode `{scan['hash_mode']}`")
    L.append("")
    L += table(["items", "clean", "with errors", "errors", "warnings", "infos", "dupe groups",
                "not in rekordbox", "missing files", "unreadable"],
               [[c["items"], c["clean"], c["items_with_errors"], c["error"], c["warn"], c["info"],
                 c["duplicate_groups"], scan["not_in_rekordbox"], scan["missing_files"], scan["unreadable"]]])
    for w in audit["config"].get("warnings", []):
        L += ["", f"> config warning: {w}"]
    L += ["", "## By rule", ""]
    severity_of = {}
    for it in audit["items"]:
        for x in it["findings"]:
            severity_of[x["code"]] = x["severity"]
    L += table(["code", "severity", "count", "meaning"],
               [[code, severity_of.get(code, ""), n, CODE_HELP.get(code, "")] for code, n in c["by_code"].items()])

    by_code: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for it in audit["items"]:
        for x in it["findings"]:
            by_code.setdefault(x["code"], []).append((it, x))
    for code in c["by_code"]:
        rows = by_code.get(code, [])
        L += ["", f"### {code} ({len(rows)})", ""]
        seen: set[tuple[str, str]] = set()
        out_rows = []
        for it, x in rows:
            key = (it["file"], x["message"])
            if key in seen:
                continue
            seen.add(key)
            profiles = sorted({y.get("profile", "") for i2, y in rows if i2["file"] == it["file"] and y["message"] == x["message"]} - {""})
            out_rows.append([_tail(it["file"]), it["rb_content_id"] or "-", x["message"], ", ".join(profiles)])
        L += table(["file", "rekordbox id", "detail", "profile"], out_rows)

    orphans = [it for it in audit["items"] if it["rb_content_id"] is None]
    if orphans:
        L += ["", f"## Not in rekordbox ({len(orphans)})", ""]
        L += table(["file", "artist tag", "title tag"],
                   [[_tail(it["file"]), " / ".join(it["tags"]["artist"]) if it["tags"] else "", it["tags"]["title"] if it["tags"] else ""]
                    for it in orphans])

    if audit["duplicates"]:
        L += ["", f"## Duplicates ({len(audit['duplicates'])} groups, report only)", ""]
        for i, g in enumerate(audit["duplicates"], 1):
            L += [f"### Group {i} ({g['kind']}) - keep: {_tail(g['keeper'] or '-')} ({g['reason']})", ""]
            L += table(["file", "rekordbox id", "format", "kbps", "length s", "cues"],
                       [[_tail(m["file"]), m["rb_content_id"] or "-", m["container"] or "?", m["bitrate_kbps"] or "",
                         m["duration_s"] or "", m["cues"] if m["cues"] is not None else "-"] for m in g["members"]])
            L.append("")
    L += ["", "No file was changed by this audit. Next: `dj tidy plan <same target>` to propose tag fixes.", ""]
    return "\n".join(L)


# The tidy reports name music files by their paths: in a library folder they stay out of git (R-905).
REPORT_IGNORE_LINES = ("reports/tidy/", "reports/*-tidy-relocate-*.md")


def keep_reports_out_of_git(paths: Paths) -> None:
    """In a library folder (the desktop extension, intake.tidy_paths), the tidy report lines go into
    its .gitignore (add only). In the repo its own .gitignore holds /reports/."""
    if paths.library:
        libfolder.ensure_gitignore(paths.root, REPORT_IGNORE_LINES)


def write_audit(audit: dict[str, Any], paths: Paths) -> tuple[Path, Path]:
    keep_reports_out_of_git(paths)
    folder = paths.report_root / "tidy"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}-{audit['target']['slug']}"
    json_path = folder / f"{stem}.audit.json"
    md_path = folder / f"{stem}.audit.md"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(audit_md(audit), encoding="utf-8")
    return json_path, md_path


def relocate_md(plan: dict[str, Any], renames: Sequence[dict[str, Any]]) -> str:
    L = [f"# Relocate checklist: {plan['target']['value'] or 'collection'}", "",
         f"Plan `{plan['plan_id']}`. These files were renamed on disk; rekordbox still points at the old "
         f"name and shows them with `!` until each one is relocated.", "",
         "In rekordbox: Collection -> find the track (it shows `!`) -> right-click -> **Relocate** -> pick the new file.",
         "Cues, grid and playlists survive Relocate. Do them one by one; tick the box when done.", ""]
    L += table(["done", "rekordbox id", "track", "old file", "new file"],
               [["[ ]", r.get("rb_content_id") or "-", r.get("label", ""), r["old"], r["new"]] for r in renames])
    L.append("")
    return "\n".join(L)
