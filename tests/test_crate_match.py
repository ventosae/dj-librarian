"""Long crates (D-38): dj_match_tracks, and the spec's seed, prefer and exclude."""

from __future__ import annotations

import pytest
import xml_fixtures as fx
from test_crate import big_spec, spec_of

from dj import crate, crate_match
from dj.libfolder import LibraryFolder
from dj.readers.xml import read_xml


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return read_xml(fx.write_xml(tmp_path_factory.mktemp("big") / "big.xml", big_spec()))


def test_match_splits_owned_and_missing(lib, tmp_path):
    result = crate_match.match(lib, ["Ada Arden - Signal 101", "Nobody Real - Ghost Track https://x.test/a"])
    assert result["counts"] == {"candidates": 2, "owned": 1, "missing": 1}
    assert result["owned"][0]["id"] == "101"  # the lowest id of the two copies
    gone = result["missing"][0]
    assert gone["source"] == "https://x.test/a" and "beatport.com/search?q=Nobody+Real+Ghost+Track" in gone["beatport"]
    path = crate_match.write_to_buy(LibraryFolder(tmp_path), "sat", result["missing"])
    assert path.name == "sat.to-buy.md" and "Nobody Real - Ghost Track" in path.read_text(encoding="utf-8")


def _ids(result):
    return {p.id for p in result.picks}


def test_prefer_and_exclude_change_the_picks(lib):
    base = crate.select(lib, spec_of(size=30, genres=["Techno"]))
    spare = base.spares[0].id
    assert spare in _ids(crate.select(lib, spec_of(size=30, genres=["Techno"], prefer=[spare])))
    dropped = base.picks[-1].id
    after = crate.select(lib, spec_of(size=30, genres=["Techno"], exclude=[dropped]))
    assert dropped not in _ids(after) | {p.id for p in after.spares}


def test_seed_is_an_anchor_and_sets_the_window(lib):
    seed = lib.tracks["126"]  # House, 123 BPM
    result = crate.select(lib, spec_of(size=30, seed="126"))
    assert [p.id for p in result.picks if p.anchor] == ["126"]
    assert all(abs(p.bpm - seed.bpm) <= crate.SEED_BPM for p in result.picks)
    assert all("House" in p.genre for p in result.picks)
    with pytest.raises(crate.CrateError):
        crate.select(lib, spec_of(size=30, seed="999999"))
