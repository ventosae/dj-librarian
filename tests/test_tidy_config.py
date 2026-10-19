"""tidy.yaml loading: defaults, validation messages, the roots gate."""

import pytest

from dj.safety import REPO_ROOT
from dj.tidy import TidyError
from dj.tidy import config as cfg_mod

MINIMAL = """
roots: ["{root}"]
profiles:
  - name: p1
    formats: [mp3, flac]
    max_bit_depth: 24
    sample_rates: [44100, 48000]
"""


def write(tmp_path, text):
    p = tmp_path / "tidy.yaml"
    p.write_text(text.replace("{root}", (tmp_path / "music").as_posix()), encoding="utf-8")
    return p


def test_example_tidy_yaml_loads_with_two_profiles():
    cfg = cfg_mod.load_config(REPO_ROOT / "examples" / "tidy.example.yaml")
    assert [p.name for p in cfg.profiles] == ["cdj3000_family", "nxs2_family"]
    assert cfg.default_profiles == ("cdj3000_family", "nxs2_family")
    assert cfg.id3_version == 3 and cfg.naming.title_includes_mix is True
    assert "Original Mix" in cfg.naming.omit_mixes
    assert cfg.bpm_expectations and cfg_mod.expected_bpm_from_name("funk_109_bpm", cfg) == (
        109, cfg.bpm_expectations[0].regex.pattern)


def test_minimal_file_gets_defaults_and_warns_about_missing_root(tmp_path):
    cfg = cfg_mod.load_config(write(tmp_path, MINIMAL))
    assert cfg.default_profiles == ("p1",) and cfg.profiles[0].mp3_min_kbps == 0
    assert cfg.naming.artist_join_two == " & " and cfg.art.embed_max_px == 800
    assert cfg.duplicate_duration_tolerance_s == 2 and cfg.enforce_roots_for_writes is True
    assert any("not a directory" in w for w in cfg.warnings)


@pytest.mark.parametrize("bad, message", [
    (MINIMAL.replace("formats: [mp3, flac]", "formats: [mp3, ogg]"), "unknown"),
    (MINIMAL + "default_profiles: [nope]\n", "unknown profiles"),
    (MINIMAL + "bpm_expectations:\n  - regex: '(unclosed'\n", "does not compile"),
    (MINIMAL + "bpm_expectations:\n  - regex: 'dnb'\n", "needs a `bpm:`"),
    (MINIMAL + "id3_version: 2\n", "id3_version"),
    (MINIMAL.replace("sample_rates: [44100, 48000]", "sample_rates: ['44.1k']"), "integers"),
    ("roots: []\nprofiles: []\n", "at least one"),
    ("just a string", "mapping"),
])
def test_bad_config_names_the_problem(tmp_path, bad, message):
    with pytest.raises(TidyError, match=message):
        cfg_mod.load_config(write(tmp_path, bad))


def test_unknown_profile_lists_the_known_ones(tmp_path):
    cfg = cfg_mod.load_config(write(tmp_path, MINIMAL))
    with pytest.raises(TidyError, match="knows: p1"):
        cfg_mod.profiles_named(cfg, ["cdj"])
    assert [p.name for p in cfg_mod.profiles_named(cfg, [])] == ["p1"]


def test_folder_in_roots_resolves_and_compares(tmp_path):
    (tmp_path / "music" / "sub").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    cfg = cfg_mod.load_config(write(tmp_path, MINIMAL))
    assert cfg_mod.folder_in_roots(tmp_path / "music" / "sub", cfg)
    assert cfg_mod.folder_in_roots(str(tmp_path / "music" / "sub" / ".." / "sub"), cfg)
    assert not cfg_mod.folder_in_roots(tmp_path / "elsewhere", cfg)
    assert not cfg_mod.folder_in_roots(tmp_path, cfg)


def test_fixed_bpm_expectation_and_first_match_wins(tmp_path):
    text = MINIMAL + "bpm_expectations:\n  - regex: '(?i)dnb'\n    bpm: 174\n  - regex: '(?P<bpm>\\d+)_bpm'\n"
    cfg = cfg_mod.load_config(write(tmp_path, text))
    assert cfg_mod.expected_bpm_from_name("DNB_200_bpm", cfg)[0] == 174
    assert cfg_mod.expected_bpm_from_name("funk_109_bpm", cfg)[0] == 109
    assert cfg_mod.expected_bpm_from_name("house_base", cfg) == (None, "")
