"""Plan -> the DJ's decisions -> apply (tags, same-folder renames) -> undo.

Safety protocol per file: undo record first (written atomically), then the tag write
(temp + replace, see tags.py), then the rename, then the record is completed and the plan
item marked applied. A crash leaves a record with `sha256_after: null`, which both `apply`
and `undo` refuse to touch silently. master.db is never opened here.
"""

from __future__ import annotations

import dataclasses
import errno
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Collection, Sequence

from dj import intake, libfolder
from dj.intake import Paths
from dj.tidy import TidyError, names, tags
from dj.tidy.checks import Item
from dj.tidy.config import TidyConfig
from dj.tidy.report import relocate_md
from dj.tidy.scan import Target

PENDING, YES, NO = intake.PENDING, intake.YES, intake.NO
KIND, UNDO_KIND = "tidy-plan", "tidy-undo"
SKIP_FORMAT = "SKIP_FORMAT"
SKIP_UNREADABLE = "SKIP_UNREADABLE"
SKIP_LOW_CONFIDENCE = "SKIP_LOW_CONFIDENCE"
SKIP_SWAP_SUSPECTED = "SKIP_SWAP_SUSPECTED"
SKIP_OUTSIDE_ROOTS = "SKIP_OUTSIDE_ROOTS"
SKIP_NO_CHANGES = "SKIP_NO_CHANGES"
SKIP_FILE_MISSING = "SKIP_FILE_MISSING"
SKIP_REASONS = {SKIP_FORMAT, SKIP_UNREADABLE, SKIP_LOW_CONFIDENCE, SKIP_SWAP_SUSPECTED, SKIP_OUTSIDE_ROOTS,
                SKIP_NO_CHANGES, SKIP_FILE_MISSING}
ART_MODES = ("local", "none")
HOW_TO = ("Set decision to yes or no per item (pending items are not applied). Then: "
          "dj tidy apply <this file>  (dry-run, prints a preview id), and after a yes add --apply --preview-id <id> "
          "to write the tags. Undo: dj tidy undo <this file> (dry-run), then --apply --preview-id <id>")


# -- paths ---------------------------------------------------------------------------------


def plan_id_for(target: Target) -> str:
    return f"{date.today().isoformat()}-tidy-{target.slug}"


def plan_path_for(target: Target, paths: Paths) -> Path:
    return paths.plans / f"{plan_id_for(target)}.plan.json"


def undo_path_for(plan_path: Path, paths: Paths) -> Path:
    stem = Path(plan_path).name.removesuffix(".plan.json")
    return paths.root / "state" / "tidy" / f"{stem}.undo.json"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else default


# -- building --------------------------------------------------------------------------------


def propose(item: Item, cfg: TidyConfig, known_artists: Collection[str], art_mode: str
            ) -> tuple[dict[str, dict[str, Any]], str | None, list[str]]:
    """-> (changes, skip_reason, notes). Only EMPTY fields get a proposal (v1 rule)."""
    f = item.file
    notes: list[str] = []
    if not f.exists:
        return {}, SKIP_FILE_MISSING, notes
    if f.read_error or f.tags is None or f.stream is None:
        return {}, SKIP_UNREADABLE, notes
    if f.container not in tags.WRITABLE:
        return {}, SKIP_FORMAT, notes
    if cfg.enforce_roots_for_writes and not item.in_roots:
        return {}, SKIP_OUTSIDE_ROOTS, notes

    t, parsed, container = f.tags, item.parsed, f.container
    changes: dict[str, dict[str, Any]] = {}
    tag_skip: str | None = None
    if parsed is not None:
        swap = names.swap_suspected(parsed, item.tag_artist, item.tag_title, known_artists)
        if swap:
            tag_skip = SKIP_SWAP_SUSPECTED
            notes.append("filename may be 'Title - Artist': no tag proposals from it")
        elif parsed.confidence not in (names.HIGH, names.MEDIUM):
            tag_skip = SKIP_LOW_CONFIDENCE
            notes.append(f"filename parse confidence {parsed.confidence} ({parsed.pattern}): no tag proposals")
        else:
            why = f"filename ({parsed.pattern}, confidence {parsed.confidence})"
            notes += list(parsed.notes)

            def change(name: str, new: str) -> None:
                changes[name] = {"frame": tags.frame_name(container, name), "old": t.value(name), "new": new, "why": why}

            if not any(a.strip() for a in t.artist) and parsed.artist:
                change("artist", parsed.artist)
            if not t.title.strip() and parsed.title:
                new_title = parsed.title_for_tag
                if cfg.naming.title_includes_mix and parsed.mix:
                    new_title = f"{new_title} ({parsed.mix})"
                change("title", new_title)
            if not t.mix.strip() and parsed.mix:
                change("mix", parsed.mix)
            if not t.remixer.strip() and parsed.remixer:
                change("remixer", parsed.remixer)

    if art_mode == "local" and not t.has_art and item.local_art is not None:
        changes["art"] = {"frame": tags.frame_name(container, "art"), "old": None, "new": str(item.local_art),
                          "why": "local image next to the track, resized to a baseline JPEG"}
    if not changes:
        return {}, tag_skip or SKIP_NO_CHANGES, notes
    return changes, None, notes


def _current_names(item: Item, changes: dict[str, dict[str, Any]]) -> tuple[list[str], str, str | None]:
    """(artists, title, mix) as they will be after the changes."""
    t = item.file.tags
    artists = [a for a in (t.artist if t else ()) if a.strip()] or (
        [changes["artist"]["new"]] if "artist" in changes else [])
    title = (t.title if t and t.title.strip() else "") or (changes["title"]["new"] if "title" in changes else "")
    mix = (t.mix if t and t.mix.strip() else "") or (changes["mix"]["new"] if "mix" in changes else "")
    return artists, title, mix or None


def planned_rename(item: Item, changes: dict[str, dict[str, Any]], cfg: TidyConfig, rename: bool,
                   rename_imported: bool, taken: set[str]) -> dict[str, Any] | None:
    if not rename or not item.file.exists or item.file.read_error:
        return None
    if item.rb is not None and not rename_imported:
        return None
    if cfg.enforce_roots_for_writes and not item.in_roots:
        return None
    artists, title, mix = _current_names(item, changes)
    if not artists or not title:
        return None
    base, mix_in_title, feat = names.split_title(title)
    new = names.build_filename(names.join_artists(artists, cfg.naming), base, mix or mix_in_title,
                               item.file.path.suffix, cfg.naming, feat=feat)
    current = item.file.name
    if names.same_name(new, current):
        return None
    new = names.collision_free(new, taken)
    taken.add(new)
    return {"old": current, "new": new, "imported": item.rb is not None}


def _listing(folder: Path, cache: dict[Path, set[str]]) -> set[str]:
    if folder not in cache:
        try:
            cache[folder] = {p.name for p in folder.iterdir()}
        except OSError:
            cache[folder] = set()
    return cache[folder]


def build_plan(items: Sequence[Item], target: Target, cfg: TidyConfig, known_artists: Collection[str],
               rename: bool = False, rename_imported: bool = False, art: str = "local") -> dict[str, Any]:
    if art not in ART_MODES:
        raise TidyError(f"--art must be one of {', '.join(ART_MODES)}")
    rename = rename or rename_imported
    listings: dict[Path, set[str]] = {}
    out_items = []
    for item in items:
        changes, skip, notes = propose(item, cfg, known_artists, art)
        taken = _listing(item.file.path.parent, listings) if item.file.exists else set()
        taken_cf = {n for n in taken if not names.same_name(n, item.file.name)}
        ren = planned_rename(item, changes, cfg, rename, rename_imported, taken_cf)
        if ren:
            _listing(item.file.path.parent, listings).add(ren["new"])
        actionable = bool(changes or ren)
        if skip == SKIP_NO_CHANGES and ren:
            skip = None
        f = item.file
        out_items.append({
            "file": f.path.as_posix(),
            "rb_content_id": item.rb.content_id if item.rb else None,
            "label": item.label,
            "sha256": (f.sha256 or tags.sha256(f.path)) if actionable and f.exists else f.sha256,
            "mtime": f.mtime,
            "size": f.size,
            "container": f.container,
            "tag_format": tags.tag_format(f.container),
            "parsed": dataclasses.asdict(item.parsed) if item.parsed else None,
            "changes": changes,
            "rename": ren,
            "skip_reason": skip,
            "notes": notes,
            "decision": PENDING if actionable else None,
            "applied": None,
        })
    plan = {
        "kind": KIND,
        "version": 1,
        "plan_id": plan_id_for(target),
        "created": datetime.now().isoformat(timespec="seconds"),
        "target": target.as_dict(),
        "options": {"rename": rename, "rename_imported": rename_imported, "art": art, "overwrite": False,
                    "id3_version": cfg.id3_version},
        "how_to": HOW_TO,
        "counts": {},
        "items": out_items,
    }
    plan["counts"] = counts(plan)
    return plan


def counts(plan: dict[str, Any]) -> dict[str, int]:
    items = plan["items"]
    return {
        "items": len(items),
        "with_changes": sum(1 for i in items if i["changes"] or i["rename"]),
        "renames": sum(1 for i in items if i["rename"]),
        "pending": sum(1 for i in items if i["decision"] == PENDING),
        "yes": sum(1 for i in items if i["decision"] == YES),
        "no": sum(1 for i in items if i["decision"] == NO),
        "applied": sum(1 for i in items if i["applied"]),
        "skipped": sum(1 for i in items if i["skip_reason"]),
    }


def _same_proposal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return ({k: v["new"] for k, v in a.get("changes", {}).items()} == {k: v["new"] for k, v in b.get("changes", {}).items()}
            and (a.get("rename") or {}).get("new") == (b.get("rename") or {}).get("new"))


def write_plan(plan: dict[str, Any], paths: Paths) -> Path:
    """Decisions (and applied marks) already written today survive a re-plan with the same proposal."""
    path = paths.plans / f"{plan['plan_id']}.plan.json"
    earlier = {i["file"]: i for i in _read_json(path, {}).get("items", [])}
    for item in plan["items"]:
        old = earlier.get(item["file"])
        if old and item["decision"] is not None and _same_proposal(old, item):
            item["decision"] = old.get("decision", PENDING) or PENDING
            item["applied"] = old.get("applied")
    plan["counts"] = counts(plan)
    _write_json_atomic(path, plan)
    return path


# -- loading / validation --------------------------------------------------------------------


def load_plan(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise TidyError(f"Plan not found: {path}")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise TidyError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(plan, dict) or plan.get("kind") != KIND:
        raise TidyError(f"{path.name} is not a dj tidy plan (kind must be {KIND!r}).")
    options = plan.get("options") or {}
    for item in plan.get("items", []):
        label = item.get("file", "?")
        if item.get("decision") not in (None, PENDING, YES, NO):
            raise TidyError(f"decision must be pending, yes or no: {label}")
        if item.get("skip_reason") not in SKIP_REASONS | {None}:
            raise TidyError(f"unknown skip_reason {item.get('skip_reason')!r}: {label}")
        if item.get("decision") == YES and item.get("skip_reason"):
            raise TidyError(f"decision is yes on a skipped item ({item['skip_reason']}): {label}")
        changes = item.get("changes") or {}
        for key, ch in changes.items():
            if key not in tags.FIELDS + (tags.ART,):
                raise TidyError(f"change {key!r} is not one of {tags.FIELDS + (tags.ART,)}: {label}")
            new = ch.get("new")
            if not isinstance(new, str) or not new.strip() or any(ord(c) < 32 for c in new):
                raise TidyError(f"change {key!r} has an empty or control-character value: {label}")
        ren = item.get("rename")
        if ren:
            new = ren.get("new", "")
            if not new or any(sep in new for sep in "/\\") or names.sanitize(new) != new:
                raise TidyError(f"rename target {new!r} is not a clean file name: {label}")
            if ren.get("imported") and not options.get("rename_imported"):
                raise TidyError(f"rename of an imported file without --rename-imported: {label}")
    return plan


# -- apply -----------------------------------------------------------------------------------


class Interrupted(TidyError):
    """apply_plan / undo_plan stopped by an error outside its per-file handling after it began
    writing. `result` holds what was done by then (the file it was on counts as failed;
    `undo_path` is set), so the caller can log it (R-904). The message is the original error's."""

    def __init__(self, cause: BaseException, result: Any):
        super().__init__(str(cause))
        self.result = result


@dataclass
class ApplyResult:
    plan_path: Path
    dry_run: bool
    applied: list[dict[str, Any]] = field(default_factory=list)
    failed: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    skipped: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    already: int = 0
    pending: int = 0
    no: int = 0
    undo_path: Path | None = None
    report_path: Path | None = None
    relocate_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": str(self.plan_path),
            "applied": not self.dry_run,
            "counts": {"applied": len(self.applied), "failed": len(self.failed), "skipped": len(self.skipped),
                       "applied_before": self.already, "pending": self.pending, "no": self.no},
            "items": (
                [{"file": i["file"], "result": "applied", "renamed_to": (i.get("applied") or {}).get("renamed_to")} for i in self.applied]
                + [{"file": i["file"], "result": "failed", "reason": r} for i, r in self.failed]
                + [{"file": i["file"], "result": "skipped", "reason": r} for i, r in self.skipped]
            ),
            "undo": str(self.undo_path) if self.undo_path else None,
            "report": str(self.report_path) if self.report_path else None,
            "relocate_checklist": str(self.relocate_path) if self.relocate_path else None,
        }


def _incomplete_records(undo: dict[str, Any]) -> set[str]:
    return {r["file_before"] for r in undo.get("records", []) if r.get("sha256_after") is None and not r.get("error")}


def preflight(plan: dict[str, Any], cfg: TidyConfig, undo: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    """-> (items ready to apply, items that cannot run with the reason). Reads files, writes nothing."""
    ready: list[dict[str, Any]] = []
    blocked: list[tuple[dict[str, Any], str]] = []
    incomplete = _incomplete_records(undo)
    for item in plan["items"]:
        if item.get("decision") != YES or item.get("applied"):
            continue
        path = Path(item["file"])
        reason = None
        if item["file"] in incomplete:
            reason = "an earlier apply stopped half-way on this file (undo record incomplete): check it by hand"
        elif not path.is_file():
            reason = "file is missing"
        elif not _in_roots(path, cfg):  # always: enforce_roots_for_writes only shapes the plan
            reason = "outside tidy.yaml roots"
        elif item.get("sha256") and tags.sha256(path) != item["sha256"]:
            reason = "file changed since the plan was written (re-run dj tidy plan)"
        else:
            container = tags.container_of(path)
            if (item["changes"] and container not in tags.WRITABLE):
                reason = f"{container or 'unknown'} tags are not writable in v1"
            elif path.with_name(f".{path.name}{tags.TMP_SUFFIX}").exists():
                reason = "a .tidy-tmp file from an earlier run sits next to it"
            else:
                try:
                    current, _, _ = tags.read(path)
                except TidyError as exc:
                    reason = str(exc)
                else:
                    for name, ch in item["changes"].items():
                        if name == tags.ART:
                            if current.has_art:
                                reason = "artwork no longer missing"
                            elif not Path(ch["new"]).is_file():
                                reason = f"artwork source {ch['new']} is gone"
                        elif current.value(name).strip():
                            reason = f"{name} is no longer empty ({current.value(name)!r})"
                        if reason:
                            break
                ren = item.get("rename")
                if not reason and ren:
                    target = path.with_name(ren["new"])
                    if target.exists() or any(names.same_name(p.name, ren["new"]) for p in path.parent.iterdir()):
                        reason = f"rename target {ren['new']!r} already exists"
        (blocked.append((item, reason)) if reason else ready.append(item))
    return ready, blocked


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _in_roots(path: Path, cfg: TidyConfig) -> bool:
    """CLAUDE.md: audio file writes stay inside the tidy.yaml roots, for apply and undo alike."""
    return any(_inside(path, r) for r in cfg.roots)


def _rename_new(path: Path, target: Path) -> None:
    """Rename `path` to `target`, never over a file that sits there: the check and the rename are
    one step. os.rename refuses an existing target on Windows (where tidy writes run in v0.1);
    elsewhere a hard link does, and a disk without hard links checks first."""
    if os.name == "nt":
        os.rename(path, target)  # FileExistsError when target exists
        return
    try:
        os.link(path, target)  # FileExistsError when target exists
    except FileExistsError:
        raise
    except OSError:
        if target.exists():
            raise FileExistsError(errno.EEXIST, "File exists", str(target)) from None
        os.rename(path, target)
        return
    os.unlink(path)


def apply_plan(plan: dict[str, Any], plan_path: Path, cfg: TidyConfig, paths: Paths, strict: bool = False,
               dry_run: bool = True) -> ApplyResult:
    plan_path = Path(plan_path)
    undo_path = undo_path_for(plan_path, paths)
    undo = _read_json(undo_path, {"kind": UNDO_KIND, "version": 1, "plan": str(plan_path), "records": []})
    result = ApplyResult(plan_path, dry_run)
    result.already = sum(1 for i in plan["items"] if i.get("applied"))
    result.pending = sum(1 for i in plan["items"] if i.get("decision") == PENDING)
    result.no = sum(1 for i in plan["items"] if i.get("decision") == NO)

    ready, blocked = preflight(plan, cfg, undo)
    result.skipped = blocked
    if strict and blocked:
        return result
    if dry_run:
        result.applied = ready
        return result
    before = len(undo["records"])
    try:
        return _write_ready(plan, plan_path, cfg, paths, undo, undo_path, ready, result)
    except (TidyError, OSError) as exc:  # outside the per-file handling: what was done stays recorded
        started = len(undo["records"]) - before  # one undo record per file it began, in order
        if not started:
            raise
        done = len(result.applied) + len(result.failed)
        if done < started:  # the file it was on: its undo record is there, it may be half-written
            result.failed.append((ready[done], str(exc)))
        result.undo_path = undo_path
        raise Interrupted(exc, result) from exc


def _write_ready(plan: dict[str, Any], plan_path: Path, cfg: TidyConfig, paths: Paths, undo: dict[str, Any],
                 undo_path: Path, ready: list[dict[str, Any]], result: ApplyResult) -> ApplyResult:
    """apply_plan's writes: per ready item the undo record first, then the file."""
    id3_version = int(plan.get("options", {}).get("id3_version", cfg.id3_version))
    renamed: list[dict[str, Any]] = []
    for item in ready:
        path = Path(item["file"])
        container = tags.container_of(path)
        current, stream_before, _ = tags.read(path)
        record: dict[str, Any] = {
            "seq": len(undo["records"]) + 1,
            "at": datetime.now().isoformat(timespec="seconds"),
            "file_before": item["file"],
            "file_after": None,
            "sha256_before": tags.sha256(path),
            "sha256_after": None,
            "id3_version_before": list(stream_before.id3_version) if stream_before.id3_version else None,
            "tags_snapshot": tags.snapshot(current, container or ""),
            "fields_added": [k for k in item["changes"] if k != tags.ART],
            "art_added": tags.ART in item["changes"],
            "renamed": False,
            "undone": None,
            "error": None,
        }
        undo["records"].append(record)
        _write_json_atomic(undo_path, undo)
        try:
            text_changes = {k: v["new"] for k, v in item["changes"].items() if k != tags.ART}
            art_bytes = None
            if tags.ART in item["changes"]:
                art_bytes = tags.prepare_art(Path(item["changes"][tags.ART]["new"]).read_bytes(),
                                             cfg.art.embed_max_px, cfg.art.jpeg_quality)
            if text_changes or art_bytes is not None:
                tags.write(path, text_changes, art_bytes, id3_version)
            ren = item.get("rename")
            if ren:
                target = path.with_name(ren["new"])
                if target.exists():
                    raise TidyError(f"rename target {ren['new']!r} appeared since preflight")
                _rename_new(path, target)
                path = target
                record["renamed"] = True
        except (TidyError, OSError) as exc:
            record["error"] = str(exc)
            record["file_after"] = str(path.as_posix())
            _write_json_atomic(undo_path, undo)
            result.failed.append((item, str(exc)))
            continue
        record["file_after"] = path.as_posix()
        record["sha256_after"] = tags.sha256(path)
        _write_json_atomic(undo_path, undo)
        item["applied"] = {"at": record["at"], "sha256_after": record["sha256_after"],
                           "renamed_to": path.as_posix() if record["renamed"] else None}
        plan["counts"] = counts(plan)
        _write_json_atomic(plan_path, plan)
        result.applied.append(item)
        if record["renamed"]:
            renamed.append({"rb_content_id": item.get("rb_content_id"), "label": item.get("label", ""),
                            "old": item["file"], "new": path.as_posix()})

    result.undo_path = undo_path
    result.report_path = write_apply_report(result, plan, paths)
    imported = [r for r in renamed if r["rb_content_id"]]
    if imported:
        result.relocate_path = write_relocate(plan, imported, paths)
    return result


def write_apply_report(result: ApplyResult, plan: dict[str, Any], paths: Paths) -> Path:
    data = result.as_dict() | {"applied_at": datetime.now().isoformat(timespec="seconds"), "plan_id": plan["plan_id"]}
    # create-only: a second apply on one day gets -2, the first report stays
    return libfolder.write_new_numbered(paths.reports / "tidy", f"{date.today().isoformat()}-tidy-apply-"
                                        f"{plan['target']['slug']}", ".report.json",
                                        json.dumps(data, indent=2, ensure_ascii=False))


def write_relocate(plan: dict[str, Any], renames: Sequence[dict[str, Any]], paths: Paths) -> Path:
    path = paths.reports / f"{date.today().isoformat()}-tidy-relocate-{plan['target']['slug']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = relocate_md(plan, renames)
    if existing:
        text = existing.rstrip("\n") + "\n\n" + text.split("\n\n", 2)[-1]  # append only the new table
    path.write_text(text, encoding="utf-8")
    return path


# -- undo ------------------------------------------------------------------------------------


@dataclass
class UndoResult:
    plan_path: Path
    undo_path: Path
    dry_run: bool
    restored: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    failed: list[tuple[dict[str, Any], str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": str(self.plan_path), "undo": str(self.undo_path), "applied": not self.dry_run,
            "counts": {"restored": len(self.restored), "skipped": len(self.skipped), "failed": len(self.failed)},
            "items": ([{"file": r["file_before"], "result": "restored"} for r in self.restored]
                      + [{"file": r["file_before"], "result": "skipped", "reason": why} for r, why in self.skipped]
                      + [{"file": r["file_before"], "result": "failed", "reason": why} for r, why in self.failed]),
        }


def undo_plan(plan: dict[str, Any], plan_path: Path, cfg: TidyConfig, paths: Paths, dry_run: bool = True,
              force: bool = False) -> UndoResult:
    plan_path = Path(plan_path)
    undo_path = undo_path_for(plan_path, paths)
    result = UndoResult(plan_path, undo_path, dry_run)
    undo = _read_json(undo_path, None)
    if not undo:
        raise TidyError(f"No undo file for this plan ({undo_path}). Nothing was applied, or it was undone already.")
    touching: list[dict[str, Any]] = []  # the record whose file is being restored, until it is counted
    try:
        return _restore(plan, plan_path, cfg, undo, undo_path, result, touching, dry_run, force)
    except (TidyError, OSError) as exc:  # outside the per-file handling: what was done stays recorded
        if touching:
            result.failed.append((touching[0], str(exc)))
        if dry_run or not (result.restored or result.failed):
            raise
        raise Interrupted(exc, result) from exc


def _restore(plan: dict[str, Any], plan_path: Path, cfg: TidyConfig, undo: dict[str, Any], undo_path: Path,
             result: UndoResult, touching: list[dict[str, Any]], dry_run: bool, force: bool) -> UndoResult:
    """undo_plan's loop, newest record first. `touching` holds the record whose file it is changing."""
    id3_version = int(plan.get("options", {}).get("id3_version", cfg.id3_version))
    by_file = {i["file"]: i for i in plan["items"]}
    for record in sorted(undo["records"], key=lambda r: -r["seq"]):
        if record.get("undone"):
            continue
        if record.get("error") and record.get("sha256_after") is None:
            # the write failed before anything changed; nothing to restore
            if not dry_run:
                record["undone"] = {"at": datetime.now().isoformat(timespec="seconds"), "note": "nothing was changed"}
            result.skipped.append((record, "that apply failed before changing the file"))
            continue
        if record.get("sha256_after") is None:
            result.skipped.append((record, "incomplete record (apply stopped half-way): check the file by hand"))
            continue
        path = Path(record["file_after"])
        if not (_in_roots(path, cfg) and _in_roots(Path(record["file_before"]), cfg)):
            result.skipped.append((record, "outside tidy.yaml roots"))
            continue
        if not path.is_file():
            result.failed.append((record, f"{path.name} is missing"))
            continue
        if tags.sha256(path) != record["sha256_after"] and not force:
            result.skipped.append((record, "file changed after the apply (use --force to restore anyway)"))
            continue
        if dry_run:
            result.restored.append(record)
            continue
        touching[:] = [record]
        try:
            if record.get("renamed"):
                back = Path(record["file_before"])
                if back.exists():
                    raise TidyError(f"cannot rename back: {back.name} exists")
                _rename_new(path, back)
                path = back
            before = record.get("id3_version_before")  # put the tag back in the version the file had
            version = before[1] if before and before[0] == 2 and before[1] in (3, 4) else id3_version
            tags.restore(path, record["tags_snapshot"], drop_art=bool(record.get("art_added")), id3_version=version)
        except (TidyError, OSError) as exc:
            record["error"] = f"undo: {exc}"
            _write_json_atomic(undo_path, undo)
            result.failed.append((record, str(exc)))
            touching.clear()
            continue
        record["undone"] = {"at": datetime.now().isoformat(timespec="seconds"), "sha256": tags.sha256(path)}
        _write_json_atomic(undo_path, undo)
        item = by_file.get(record["file_before"])
        if item is not None:
            item["applied"] = None
            plan["counts"] = counts(plan)
            _write_json_atomic(plan_path, plan)
        result.restored.append(record)
        touching.clear()
    return result
