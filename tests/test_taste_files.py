"""dj.taste_files: taste files are appended and refined, never regenerated without asking (R-332)."""

from __future__ import annotations

from datetime import date

import pytest

from dj import taste_files as tf
from dj.model import LibraryError
from dj.taste_files import (
    Entry,
    LogEntry,
    Vetoes,
    append_entries,
    read_entries,
    read_feedback,
    read_vetoes,
)

D1, D2, D3 = date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)
PROV = "> Measured by code: dj.analysis.taste from exports/2026-10-20-collection.xml, 2026-10-20."
PROV2 = "> Measured by code: dj.analysis.taste from exports/2026-10-27-collection.xml, 2026-10-27."
ENTRIES = [Entry("lane:a", "119-122 BPM: warm"), Entry("lane:b", "122-127 BPM: peak")]


def text(path) -> str:
    return path.read_bytes().decode("utf-8")


def section(body: str, heading: str) -> str:
    """The lines of one `## ` section, heading excluded, up to the next `#`/`##` heading."""
    out, inside = [], False
    for line in body.split("\n"):
        if line.startswith(("# ", "## ")):
            inside = line.strip() == heading
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip("\n")


def bullets(body: str, heading: str) -> list[str]:
    return [line for line in section(body, heading).split("\n") if line.startswith("- ")]


# -- a new file


def test_new_file_layout(tmp_path):
    path = tmp_path / "lanes.md"
    added = append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two lanes"], provenance=PROV)
    assert added == [
        "- [2026-10-20] 119-122 BPM: warm <!-- key:lane:a -->",
        "- [2026-10-20] 122-127 BPM: peak <!-- key:lane:b -->",
    ]
    assert text(path) == (
        "# BPM lanes\n\n" + PROV + "\n\n## Now\n\n- two lanes\n\n## Log\n\n" + "\n".join(added) + "\n"
    )
    assert read_entries(path) == [
        LogEntry(D1, "119-122 BPM: warm", "lane:a"),
        LogEntry(D1, "122-127 BPM: peak", "lane:b"),
    ]


def test_new_file_without_now_lines_has_no_now_section(tmp_path):
    path = tmp_path / "vetoes.md"
    append_entries(path, "Vetoes", [Entry("veto:16", "never propose: A - B")], today=D1)
    assert text(path) == "# Vetoes\n\n## Log\n\n- [2026-10-20] never propose: A - B <!-- key:veto:16 -->\n"


def test_new_file_with_no_entries(tmp_path):
    path = tmp_path / "x.md"
    assert append_entries(path, "X", [], today=D1, now_lines=["nothing yet"], provenance=PROV) == []
    assert text(path) == "# X\n\n" + PROV + "\n\n## Now\n\n- nothing yet\n\n## Log\n"


# -- append semantics


def test_second_run_adds_nothing_and_the_file_is_byte_identical(tmp_path):
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two lanes"], provenance=PROV)
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    assert append_entries(path, "BPM lanes", ENTRIES, today=D2, now_lines=["two lanes"], provenance=PROV) == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime  # nothing changed, nothing written


def test_second_run_on_a_later_day_keeps_the_log_byte_identical(tmp_path):
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two lanes"], provenance=PROV)
    log = section(text(path), "## Log")
    assert append_entries(path, "BPM lanes", ENTRIES, today=D2, now_lines=["still two"], provenance=PROV2) == []
    body = text(path)
    assert section(body, "## Log") == log
    assert PROV2 in body and PROV not in body  # the provenance line is replaced, not added
    assert bullets(body, "## Now") == ["- still two"]


def test_changed_text_appends_an_updated_line_and_keeps_the_old_one(tmp_path):
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1)
    old = text(path)
    changed = [Entry("lane:a", "119-123 BPM: warm"), ENTRIES[1]]
    added = append_entries(path, "BPM lanes", changed, today=D2)
    assert added == ["- [2026-10-27] updated: 119-123 BPM: warm <!-- key:lane:a -->"]
    assert text(path) == old + added[0] + "\n"  # appended at the end, nothing else touched
    # the same text again: nothing; back to the first text: updated again
    assert append_entries(path, "BPM lanes", changed, today=D3) == []
    again = append_entries(path, "BPM lanes", ENTRIES, today=D3)
    assert again == ["- [2026-11-03] updated: 119-122 BPM: warm <!-- key:lane:a -->"]


def test_new_keys_are_appended_in_order_old_lines_never_reordered(tmp_path):
    path = tmp_path / "words.md"
    append_entries(path, "Words", [Entry("word:deep", "deep: 2"), Entry("word:gig", "gig: 2")], today=D1)
    # a later run ranks them the other way and brings a new word: order of old lines stays
    added = append_entries(
        path, "Words", [Entry("word:warm", "warm: 3"), Entry("word:gig", "gig: 2"), Entry("word:deep", "deep: 2")],
        today=D2,
    )  # fmt: skip
    assert added == ["- [2026-10-27] warm: 3 <!-- key:word:warm -->"]
    keys = [e.key for e in read_entries(path)]
    assert keys == ["word:deep", "word:gig", "word:warm"]


def test_a_key_that_drops_out_is_never_deleted(tmp_path):
    path = tmp_path / "labels.md"
    append_entries(path, "Labels", ENTRIES, today=D1)
    append_entries(path, "Labels", [ENTRIES[1]], today=D2)
    assert [e.key for e in read_entries(path)] == ["lane:a", "lane:b"]


def test_hand_written_lines_survive_verbatim(tmp_path):
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two lanes"], provenance=PROV)
    hand = [
        "- [2026-10-21] I never play above 128 at a wedding",
        "- loves rolling basslines, no date",
        "*   [2026-10-22]   odd   spacing <!--key: lane:a-->",
        "Free text the DJ typed under the list.",
    ]
    path.write_bytes((text(path) + "\n".join(hand) + "\n\n## My notes\n\nkeep this\n").encode("utf-8"))
    added = append_entries(path, "BPM lanes", ENTRIES + [Entry("lane:c", "100-109 BPM: funk")], today=D2,
                           now_lines=["three lanes"], provenance=PROV)  # fmt: skip
    body = text(path)
    for line in hand:
        assert line in body.split("\n")
    # the DJ's line with key lane:a counts as its latest text, so lane:a gets an updated line
    assert added == [
        "- [2026-10-27] updated: 119-122 BPM: warm <!-- key:lane:a -->",
        "- [2026-10-27] 100-109 BPM: funk <!-- key:lane:c -->",
    ]
    log = section(body, "## Log").split("\n")
    assert log[-2:] == added  # at the end of the Log section ...
    assert section(body, "## My notes") == "keep this"  # ... and the DJ's own section stays after it
    assert body.index("## Log") < body.index(added[0]) < body.index("## My notes")


def test_lines_keep_their_bytes_with_windows_line_ends(tmp_path):
    path = tmp_path / "lanes.md"
    crlf = "# BPM lanes\r\n\r\n## Log\r\n\r\n- [2026-10-20] 119-122 BPM: warm <!-- key:lane:a -->\r\n"
    path.write_bytes(crlf.encode("utf-8"))
    added = append_entries(path, "BPM lanes", ENTRIES, today=D2)
    assert added == ["- [2026-10-27] 122-127 BPM: peak <!-- key:lane:b -->"]
    assert path.read_bytes() == (crlf + added[0] + "\n").encode("utf-8")


def test_an_undated_keyed_line_counts_as_the_latest_text(tmp_path):
    # vetoes may be typed without the dated bullet; read_vetoes reads them, so append_entries must too
    path = tmp_path / "vetoes.md"
    path.write_bytes(b"# Vetoes\n\n## Log\n\nnever propose: A - B <!-- key:veto:16 -->\n")
    assert append_entries(path, "Vetoes", [Entry("veto:16", "never propose: A - B")], today=D1) == []
    added = append_entries(path, "Vetoes", [Entry("veto:16", "lifted: A - B")], today=D2)
    assert added == ["- [2026-10-27] updated: lifted: A - B <!-- key:veto:16 -->"]
    assert read_vetoes(path) == Vetoes()
    assert text(path).startswith("# Vetoes\n\n## Log\n\nnever propose: A - B <!-- key:veto:16 -->\n")


def test_file_without_sections_gets_them_added_at_the_end(tmp_path):
    path = tmp_path / "feedback.md"
    path.write_bytes(b"# My feedback\n\nsome words")
    added = append_entries(path, "ignored", [ENTRIES[0]], today=D1, now_lines=["one"])
    body = text(path)
    assert body.startswith("# My feedback\n\nsome words\n")
    assert body.index("## Now") < body.index("## Log") < body.index(added[0])
    assert bullets(body, "## Now") == ["- one"]


# -- the Now section


def test_now_section_holds_at_most_five_lines(tmp_path):
    path = tmp_path / "x.md"
    with pytest.raises(ValueError, match="at most 5"):
        append_entries(path, "X", ENTRIES, today=D1, now_lines=[f"line {i}" for i in range(6)])
    assert not path.exists()
    append_entries(path, "X", ENTRIES, today=D1, now_lines=[f"line {i}" for i in range(5)])
    assert len(bullets(text(path), "## Now")) == 5


def test_now_section_is_replaced_and_empty_now_lines_keep_it(tmp_path):
    path = tmp_path / "x.md"
    append_entries(path, "X", ENTRIES, today=D1, now_lines=["a", "b", "c"], provenance=PROV)
    append_entries(path, "X", ENTRIES, today=D2, now_lines=["d"])
    assert bullets(text(path), "## Now") == ["- d"]
    added = append_entries(path, "X", [Entry("veto:1", "never propose: A")], today=D2)  # a Barber call
    assert added and bullets(text(path), "## Now") == ["- d"]
    assert PROV in text(path)  # empty provenance keeps the line


@pytest.mark.parametrize("log_heading", ["### Log (my notes below)", "", "My log:"])
def test_a_renamed_or_deleted_log_heading_loses_nothing(tmp_path, log_heading):
    """Only the plain bullets right under `## Now` are Now; the DJ's lines below it stay."""
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two lanes"], provenance=PROV)
    body = text(path).replace("## Log\n\n", f"{log_heading}\n\n" if log_heading else "")
    mine = "- [2026-10-21] Sundays never above 122, my own line"
    path.write_bytes((body + mine + "\n").encode("utf-8"))
    before = text(path)
    assert append_entries(path, "BPM lanes", ENTRIES, today=D2, now_lines=["one lane"], provenance=PROV) == []
    after = text(path)
    assert after == before.replace("- two lanes", "- one lane")  # only the Now line changed
    added = append_entries(path, "BPM lanes", ENTRIES + [Entry("lane:c", "c")], today=D2, now_lines=["three"])
    assert added == ["- [2026-10-27] c <!-- key:lane:c -->"]  # lane:a and lane:b are known, not re-added
    after = text(path)
    for line in [mine, "- [2026-10-20] 119-122 BPM: warm <!-- key:lane:a -->"]:
        assert after.count(line) == 1
    assert after.endswith(added[0] + "\n")


def test_lines_under_now_that_are_not_plain_bullets_are_kept(tmp_path):
    path = tmp_path / "x.md"
    path.write_bytes(
        b"# X\n\n## Now\n\n- old now line\n- [2026-10-21] my dated line\n- my undated line after it\n"
        b"- note <!-- key:lane:a -->\nfree text\n\n## Log\n\n"
    )
    added = append_entries(path, "X", ENTRIES, today=D2, now_lines=["new now line"])
    body = text(path)
    assert body.startswith(
        "# X\n\n## Now\n\n- new now line\n\n- [2026-10-21] my dated line\n- my undated line after it\n"
        "- note <!-- key:lane:a -->\nfree text\n\n## Log\n\n"
    )
    # the keyed line under Now counts as lane:a's latest text: lane:a gets an updated line
    assert added == [
        "- [2026-10-27] updated: 119-122 BPM: warm <!-- key:lane:a -->",
        "- [2026-10-27] 122-127 BPM: peak <!-- key:lane:b -->",
    ]
    assert read_entries(path)[0] == LogEntry(date(2026, 10, 21), "my dated line", None)


@pytest.mark.parametrize("own", ["updated: 2 names, e.g. Updated House", "Updated: Records: 4 tracks", "UPDATED: x"])
def test_a_text_that_starts_with_updated_is_stable(tmp_path, own):
    path = tmp_path / "x.md"
    entries = [Entry("word:updated", own)]
    assert append_entries(path, "X", entries, today=D1) == [f"- [2026-10-20] {own} <!-- key:word:updated -->"]
    before = path.read_bytes()
    assert append_entries(path, "X", entries, today=D2) == []  # the second run adds nothing
    assert path.read_bytes() == before
    changed = [Entry("word:updated", own + " and more")]
    added = append_entries(path, "X", changed, today=D2)
    assert added == [f"- [2026-10-27] updated: {own} and more <!-- key:word:updated -->"]
    assert append_entries(path, "X", changed, today=D3) == []  # an update line is read back right
    assert append_entries(path, "X", entries, today=D3) == [
        f"- [2026-11-03] updated: {own} <!-- key:word:updated -->"
    ]
    assert append_entries(path, "X", entries, today=D3) == []


def test_plan_entries_writes_nothing(tmp_path):
    path = tmp_path / "x.md"
    plan = tf.plan_entries(path, "X", ENTRIES, today=D1, now_lines=["one"])
    assert not path.exists() and plan.added == [
        "- [2026-10-20] 119-122 BPM: warm <!-- key:lane:a -->",
        "- [2026-10-20] 122-127 BPM: peak <!-- key:lane:b -->",
    ]
    assert tf.write_plan(plan) is True and text(path) == plan.text
    again = tf.plan_entries(path, "X", ENTRIES, today=D2, now_lines=["one"])
    assert again.text is None and again.added == [] and tf.write_plan(again) is False


def test_words_by_claude_provenance_sits_beside_the_measured_line(tmp_path):
    path = tmp_path / "x.md"
    append_entries(path, "X", ENTRIES, today=D1, provenance=PROV)
    words = "> Words by Claude, from taste/feedback.md."
    append_entries(path, "X", ENTRIES, today=D2, provenance=words)
    head = text(path).split("## ")[0]
    assert PROV in head and words in head


# -- rebuild


def test_rebuild_only_with_the_flag(tmp_path):
    path = tmp_path / "lanes.md"
    append_entries(path, "BPM lanes", ENTRIES, today=D1, now_lines=["two"], provenance=PROV)
    path.write_bytes(path.read_bytes() + b"- [2026-10-21] my own line\n")
    append_entries(path, "BPM lanes", ENTRIES, today=D2, now_lines=["two"], provenance=PROV)
    assert "my own line" in text(path)  # no flag: never rewritten

    added = append_entries(path, "BPM lanes", ENTRIES, today=D2, now_lines=["two"], provenance=PROV, rebuild=True)
    assert added == [
        "- [2026-10-27] 119-122 BPM: warm <!-- key:lane:a -->",
        "- [2026-10-27] 122-127 BPM: peak <!-- key:lane:b -->",
    ]
    assert "my own line" not in text(path)
    assert text(path) == "# BPM lanes\n\n" + PROV + "\n\n## Now\n\n- two\n\n## Log\n\n" + "\n".join(added) + "\n"


# -- input checks


def test_entry_checks(tmp_path):
    path = tmp_path / "x.md"
    for bad in ("bad-->key", "a--b", "<!--k"):
        with pytest.raises(ValueError, match="cannot hold '--'"):
            append_entries(path, "X", [Entry(bad, "t")], today=D1)
    with pytest.raises(ValueError, match="twice"):
        append_entries(path, "X", [Entry("k", "a"), Entry("k", "b")], today=D1)
    with pytest.raises(ValueError, match="twice"):  # one pair, written two ways
        append_entries(path, "X", [Entry("pair:17,1", "a"), Entry("pair:1, 17", "b")], today=D1)
    with pytest.raises(ValueError, match="empty"):
        append_entries(path, "X", [Entry("k", "  ")], today=D1)
    assert not path.exists()
    added = append_entries(path, "X", [Entry("k", "two\nlines <!-- sneaky --> here")], today=D1)
    assert added == ["- [2026-10-20] two lines <!- sneaky -> here <!-- key:k -->"]
    assert read_entries(path) == [LogEntry(D1, "two lines <!- sneaky -> here", "k")]
    added = append_entries(path, "X", [Entry("k2", "arrows ---> and <!--- openers")], today=D1)
    assert added == ["- [2026-10-20] arrows -> and <!- openers <!-- key:k2 -->"]


def test_not_utf8_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "x.md"
    path.write_bytes("# X\n\n## Log\n\n- caf\xe9\n".encode("cp1252"))
    before = path.read_bytes()
    with pytest.raises(LibraryError, match="UTF-8"):
        append_entries(path, "X", ENTRIES, today=D1)
    assert path.read_bytes() == before


def test_writes_go_through_the_atomic_writer(tmp_path, monkeypatch):
    calls = []
    real = tf.write_text
    monkeypatch.setattr(tf, "write_text", lambda p, t: calls.append(p) or real(p, t))
    path = tmp_path / "x.md"
    append_entries(path, "X", ENTRIES, today=D1)
    append_entries(path, "X", ENTRIES + [Entry("lane:c", "c")], today=D2)
    assert calls == [path, path]
    assert list(tmp_path.iterdir()) == [path]  # no temp file left behind


# -- parsers


def test_read_entries_skips_now_and_undated_lines(tmp_path):
    path = tmp_path / "x.md"
    path.write_text(
        "# X\n\n## Now\n\n- \\[2026-10-20] a now line that starts with a date\n- top lane\n\n## Log\n\n"
        "- [2026-10-20] measured <!-- key:lane:a -->\n- undated line\n- [2026-13-40] bad date\n"
        "- [2026-10-21] by hand\n- [2026-10-22] updated: measured again <!-- key:lane:a -->\n",
        encoding="utf-8",
    )
    assert read_entries(path) == [
        LogEntry(D1, "measured", "lane:a"),
        LogEntry(date(2026, 10, 21), "by hand", None),
        LogEntry(date(2026, 10, 22), "updated: measured again", "lane:a"),
    ]
    assert read_entries(tmp_path / "missing.md") == []


def test_a_now_line_that_starts_with_a_date_is_escaped(tmp_path):
    path = tmp_path / "x.md"
    append_entries(path, "X", ENTRIES, today=D1, now_lines=["[2026-01-01] Records: 4 tracks"])
    assert bullets(text(path), "## Now") == ["- \\[2026-01-01] Records: 4 tracks"]
    assert [e.key for e in read_entries(path)] == ["lane:a", "lane:b"]  # not read as a log line
    assert append_entries(path, "X", ENTRIES, today=D2, now_lines=["[2026-01-01] Records: 5 tracks"]) == []
    assert bullets(text(path), "## Now") == ["- \\[2026-01-01] Records: 5 tracks"]  # replaced, not kept


VETOES = """\
# Vetoes

> Words by Claude, from the Style Barber session.

## Log

- [2026-10-21] never propose: Kestrel Unit - Ferrous <!-- key:veto:16 -->
- [2026-10-21] never propose: Volta Rook - Signal Fire <!-- key:veto:19 -->
- [2026-10-21] never pair: Grid Saint - Pressure Vessel + Okoro Lane - Sunday Sermon <!-- key:pair:17,1 -->
never propose: Saffi Wren - Tape Hiss Lullaby <!-- key:veto:24 -->
- [2026-10-22] Never Pair: A + B <!-- key:pair: 9 , 13 -->
- [2026-10-22] never pair: broken <!-- key:pair:5 -->
- [2026-10-22] never pair: same twice <!-- key:pair:5,5 -->
- [2026-10-23] never propose: no id <!-- key:veto: -->
- [2026-11-01] lifted: Volta Rook - Signal Fire <!-- key:veto:19 -->
- [2026-11-02] updated: never propose: Okoro Lane - Sunday Sermon <!-- key:veto:1 -->
- [2026-11-02] never propose: something without a key
"""


def test_read_vetoes(tmp_path):
    path = tmp_path / "vetoes.md"
    path.write_text(VETOES, encoding="utf-8")
    vetoes = read_vetoes(path)
    assert vetoes.never_propose == frozenset({"16", "24", "1"})  # 19 was lifted later
    assert vetoes.never_pair == frozenset({frozenset({"1", "17"}), frozenset({"9", "13"})})
    assert vetoes.blocks("16") and not vetoes.blocks("19")
    assert vetoes.blocks_pair("17", "1") and vetoes.blocks_pair("1", "17") and not vetoes.blocks_pair("1", "2")
    assert read_vetoes(tmp_path / "missing.md") == Vetoes()


def test_vetoes_with_copies_cover_every_copy_of_a_vetoed_song():
    from types import SimpleNamespace as T

    tracks = [
        T(id="8", artist="Marlo Venn", title="Hallway Light", remixer=""),
        T(id="22", artist="Marlo  Venn", title="Hallway Light (Original Mix)", remixer=""),  # a copy
        T(id="30", artist="Marlo Venn", title="Hallway Light", remixer="Dub Atelier"),  # a remix: not a copy
        T(id="17", artist="Grid Saint", title="Pressure Vessel", remixer=""),
        T(id="23", artist="Grid Saint", title="Pressure Vessel", remixer=""),
        T(id="1", artist="Okoro Lane", title="Sunday Sermon", remixer=""),
        T(id="40", artist="", title="Untitled", remixer=""),  # no key: a copy of nothing
        T(id="41", artist="", title="Untitled", remixer=""),
    ]
    vetoes = Vetoes(frozenset({"22", "40"}), frozenset({frozenset({"1", "17"})}))
    wide = vetoes.with_copies(tracks)
    assert wide.never_propose == frozenset({"8", "22", "40"})
    assert wide.never_pair == frozenset({frozenset({"1", "17"}), frozenset({"1", "23"})})
    assert wide.blocks("8") and not wide.blocks("30") and not wide.blocks("41")
    assert wide.blocks_pair("23", "1") and not wide.blocks_pair("17", "23")
    assert Vetoes().with_copies(tracks) == Vetoes() and vetoes.with_copies([]) == vetoes


def test_vetoes_written_through_append_entries_read_back(tmp_path):
    path = tmp_path / "vetoes.md"
    append_entries(path, "Vetoes", [Entry("veto:16", "never propose: Kestrel Unit - Ferrous"),
                                    Entry("pair:17,1", "never pair: Grid Saint + Okoro Lane")], today=D1)  # fmt: skip
    assert read_vetoes(path) == Vetoes(frozenset({"16"}), frozenset({frozenset({"17", "1"})}))
    append_entries(path, "Vetoes", [Entry("veto:16", "lifted: Kestrel Unit - Ferrous")], today=D2)
    assert read_vetoes(path).never_propose == frozenset()


def test_a_veto_is_lifted_by_the_same_key_in_any_spelling(tmp_path):
    path = tmp_path / "vetoes.md"
    path.write_text(
        "# Vetoes\n\n## Log\n\n"
        "- never pair: A + B <!-- key:pair:17,1 -->\n"
        "- lifted: B + A <!-- key:pair:1,17 -->\n"
        "- never propose: X <!-- key:veto:16 -->\n"
        "- lifted: X <!-- key:veto: 16 -->\n"
        "- never pair: C + D <!-- key:pair: 9 , 13 -->\n"
        "- never propose: Y <!-- key:Veto:20 -->\n",
        encoding="utf-8",
    )
    assert read_vetoes(path) == Vetoes(frozenset({"20"}), frozenset({frozenset({"9", "13"})}))
    # lifting through append_entries: canonical keys match, so the lift is an `updated:` line
    added = append_entries(path, "Vetoes", [Entry("pair:13,9", "lifted: D + C"), Entry("veto:20", "lifted: Y")],
                           today=D2)  # fmt: skip
    assert added == [
        "- [2026-10-27] updated: lifted: D + C <!-- key:pair:13,9 -->",
        "- [2026-10-27] updated: lifted: Y <!-- key:veto:20 -->",
    ]
    assert read_vetoes(path) == Vetoes()
    # and the veto comes back with a later line in yet another spelling
    append_entries(path, "Vetoes", [Entry("pair: 9,13", "never pair: C + D")], today=D3)
    assert read_vetoes(path).never_pair == frozenset({frozenset({"9", "13"})})


def test_canonical_key():
    assert tf.canonical_key("pair: 17 , 1") == tf.canonical_key("pair:1,17") == "pair:1,17"
    assert tf.canonical_key("pair:b,a") == "pair:a,b" and tf.canonical_key("pair:10,9") == "pair:9,10"
    assert tf.canonical_key("veto:  16 ") == tf.canonical_key("VETO:16") == "veto:16"
    assert tf.canonical_key("label:night  shift") == "label:night shift"  # other keys: spaces only
    assert tf.canonical_key("label:B, A") == "label:B, A"
    assert tf.canonical_key("pair:²,1") == "pair:1,²"  # a non-ASCII digit sorts as text, no crash


def test_read_feedback(tmp_path):
    path = tmp_path / "feedback.md"
    path.write_text(
        "# Feedback\n\n## Log\n\n"
        "- [2026-10-22] too dark for a warm-up: Kestrel Unit - Ballast <!-- key:feedback:18 -->\n"
        "- [2026-10-23] more vocals on Fridays\n"
        "a loose note without a date\n",
        encoding="utf-8",
    )
    assert read_feedback(path) == [
        (date(2026, 10, 22), "too dark for a warm-up: Kestrel Unit - Ballast", "feedback:18"),
        (date(2026, 10, 23), "more vocals on Fridays", None),
    ]
    assert read_feedback(tmp_path / "missing.md") == []


def test_module_docstring_documents_the_formats():
    doc = tf.__doc__
    for fragment in ("## Now", "## Log", "- [", "<!-- key:", "updated:", "never propose:", "never pair:",
                     "key:veto:", "key:pair:", "feedback.md", "rebuild=True"):  # fmt: skip
        assert fragment in doc, fragment
